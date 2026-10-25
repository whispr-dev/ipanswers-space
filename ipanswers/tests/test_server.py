import json
import sys
import threading
import unittest
from unittest.mock import patch, call
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import GeoDatabase, Handler, Server, details, parse_address, render
from deploy_server_import import load_deployer


class DummyDatabase:
    def lookup(self, address):
        return {'city':{'names':{'en':'Cardiff'}},'subdivisions':[{'names':{'en':'Wales'}}],
                'country':{'names':{'en':'United Kingdom'}}}, {
                'autonomous_system_organization':'Example ISP','autonomous_system_number':64500}, True, 9999999999


class Contracts(unittest.TestCase):
    def test_ipv6_and_ipv4_mapped(self):
        self.assertEqual(str(parse_address('::ffff:8.8.8.8')), '8.8.8.8')
        self.assertEqual(details('2606:4700:4700::1111','test',DummyDatabase())['family'],'IPv6')

    def test_reserved_ip_does_not_geolocate(self):
        data = details('127.0.0.1','test',DummyDatabase())
        self.assertEqual(data['location'],'Not available')
        self.assertIn('reserved', data['database_note'])

    def test_location_and_network_schema(self):
        data=details('8.8.8.8','test',DummyDatabase())
        self.assertEqual(data['location'],'Cardiff, Wales, United Kingdom')
        self.assertEqual(data['isp'],'Example ISP')
        self.assertIn('64500',data['asn_label'])

    def test_user_agent_is_escaped_once(self):
        data=details('8.8.8.8','<script>@@IP@@</script>',DummyDatabase())
        result=render('@@UA@@ @@IP@@',data).decode()
        self.assertEqual(result,'&lt;script&gt;@@IP@@&lt;/script&gt; 8.8.8.8')

    def test_malformed_forwarded_value_is_not_accepted(self):
        self.assertEqual(details('8.8.8.8, 1.1.1.1','test',DummyDatabase())['ip'],'Unavailable')

    def test_missing_database_fails_honestly(self):
        with TemporaryDirectory() as directory:
            data=details('8.8.8.8','test',GeoDatabase(Path(directory)))
            self.assertEqual(data['ip'],'8.8.8.8')
            self.assertEqual(data['location'],'Not available')
            self.assertIn('temporarily unavailable',data['database_note'])

    def test_inactive_caddy_reports_before_installing(self):
        d=load_deployer()
        with TemporaryDirectory() as directory:
            config=Path(directory)/'Caddyfile'
            config.write_text('example.test {}')
            with patch.object(d,'CADDY',config), patch.object(d.os,'geteuid',return_value=0), \
                 patch.object(d.shutil,'which',return_value='/usr/bin/tool'), \
                 patch.object(d.subprocess,'run') as command, patch.object(d,'diagnose') as diagnostic:
                command.return_value.returncode=3
                with self.assertRaisesRegex(RuntimeError,'not active'):
                    d.main()
                diagnostic.assert_called_once()
                self.assertEqual(command.call_args_list,[
                    call(['systemctl','is-active','--quiet','nginx'],check=False),
                    call(['systemctl','is-active','--quiet','caddy'],check=False)])
                self.assertEqual(config.read_text(),'example.test {}')

    def test_managed_caddy_block_preserves_other_sites(self):
        d=load_deployer()
        original='lon.litehaus.online {\n reverse_proxy localhost:8080\n}\n'
        first=d.replace_block(original,d.site_block(d.CF_FALLBACK))
        again=d.replace_block(first,d.site_block(d.CF_FALLBACK))
        self.assertTrue(first.startswith(original.rstrip()))
        self.assertEqual(first,again)
        self.assertEqual(first.count('ipanswers.space {'),1)
        self.assertIn('header_up X-IPAnswers-IP {http.request.remote.host}',first)


class HTTP(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.server=Server(('127.0.0.1',0),Handler,GeoDatabase(Path(self.tmp.name)),False)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def get(self,path,headers=None):
        return urllib.request.urlopen(urllib.request.Request(self.base+path,headers=headers or {}))

    def test_untrusted_headers_cannot_spoof_ip(self):
        with self.get('/api/me',{'X-IPAnswers-IP':'8.8.8.8','CF-Connecting-IP':'1.1.1.1','X-Forwarded-For':'9.9.9.9'}) as r:
            self.assertEqual(json.load(r)['ip'],'127.0.0.1')
            self.assertIn('no-store',r.headers['Cache-Control'])
            self.assertEqual(r.headers['Cloudflare-CDN-Cache-Control'],'no-store')

    def test_trusted_local_caddy_header(self):
        self.server.trusted_proxy=True
        with self.get('/api/me',{'X-IPAnswers-IP':'8.8.8.8'}) as r:
            self.assertEqual(json.load(r)['ip'],'8.8.8.8')

    def test_html_escapes_agent_and_finishes_template(self):
        with self.get('/',{'User-Agent':'<img src=x onerror=alert(1)>'}) as r:
            page=r.read().decode()
            self.assertIn('&lt;img',page)
            self.assertNotIn('<img src=x',page)
            self.assertNotIn('@@',page)
            self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy'])
            self.assertNotIn('Set-Cookie',r.headers)

    def test_static_ip_and_traversal(self):
        for path in ['/assets/skeletrace-mark.svg','/assets/whispr-logo.svg','/style.css','/app.js']:
            with self.get(path) as r:
                self.assertEqual(r.status,200)
        with self.get('/ip') as r:
            self.assertEqual(r.read(),b'127.0.0.1\n')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.get('/../../server.py')
        self.assertEqual(error.exception.code,404)

if __name__=='__main__':
    unittest.main()
