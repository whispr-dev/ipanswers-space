#!/usr/bin/env python3
"""IP Answers: local MMDB lookup, server-rendered HTML, no visitor history."""
from __future__ import annotations
import argparse
import html
import ipaddress
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import maxminddb
import checker

ROOT = Path(__file__).resolve().parent
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


def parse_address(value: str):
    address = ipaddress.ip_address(value.strip())
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


class GeoDatabase:
    """Serialize reader replacement against lookups; mmap old files until reload."""
    def __init__(self, directory: Path):
        self.directory = directory
        self.lock = threading.Lock()
        self.generation = None
        self.city = self.asn = None
        self.epoch = 0

    def lookup(self, address: str):
        with self.lock:
            try:
                stamp = (self.directory / 'current.json').stat().st_mtime_ns
                if stamp != self.generation:
                    manifest = json.loads((self.directory / 'current.json').read_text())
                    paths = [self.directory / manifest[k] for k in ('city', 'asn')]
                    if any(p.parent != self.directory or p.suffix != '.mmdb' for p in paths):
                        raise ValueError('Invalid database manifest')
                    city = maxminddb.open_database(str(paths[0]))
                    try:
                        asn = maxminddb.open_database(str(paths[1]))
                    except Exception:
                        city.close()
                        raise
                    old = self.city, self.asn
                    self.city, self.asn = city, asn
                    self.epoch = min(city.metadata().build_epoch, asn.metadata().build_epoch)
                    self.generation = stamp
                    for reader in old:
                        if reader:
                            reader.close()
            except (OSError, ValueError, maxminddb.InvalidDatabaseError, KeyError, TypeError):
                pass  # Keep the last working readers during an interrupted update.
            try:
                city = self.city.get(address) if self.city else None
                asn = self.asn.get(address) if self.asn else None
                return city or {}, asn or {}, bool(self.city and self.asn), self.epoch
            except (ValueError, maxminddb.InvalidDatabaseError):
                return {}, {}, False, 0


def details(ip_text: str, user_agent: str, database: GeoDatabase):
    try:
        address = parse_address(ip_text)
    except ValueError:
        return dict(ip='Unavailable', family='Unknown', location='Unavailable', isp='Unavailable',
                    asn_label='No verified connection address', user_agent=user_agent,
                    note='We could not verify this connection address. Please refresh.', database_note='')
    city, asn, available, epoch = database.lookup(str(address)) if address.is_global else ({}, {}, False, 0)
    name = lambda value: value.get('names', {}).get('en', '') if isinstance(value, dict) else ''
    subdivisions = city.get('subdivisions') or []
    if isinstance(subdivisions, dict):
        subdivisions = [subdivisions]
    parts = [name(city.get('city')), name(subdivisions[0]) if subdivisions else '', name(city.get('country'))]
    location = ', '.join(dict.fromkeys(p for p in parts if p))
    org = asn.get('autonomous_system_organization')
    number = asn.get('autonomous_system_number')
    dbnote = ''
    if not address.is_global:
        dbnote = 'Local or reserved connection address. Public location and network data are unavailable.'
    elif not available:
        dbnote = 'Location and network data are temporarily unavailable. Your connection address is still shown.'
    elif time.time() - epoch > 70 * 86400:
        dbnote = 'Location data is older than two months; estimates may be out of date.'
    return dict(ip=str(address), family=f'IPv{address.version}', location=location or 'Not available',
                isp=org or 'Not available', asn_label=f'AS{number} · Routing organisation' if number else 'Network record not available',
                user_agent=user_agent or 'Not supplied by this browser',
                note='The address this site sees. A VPN, proxy or mobile network can change it.', database_note=dbnote)


def render(template: str, data: dict) -> bytes:
    tokens = {'IP':'ip', 'FAMILY':'family', 'LOCATION':'location', 'ISP':'isp', 'ASN':'asn_label',
              'UA':'user_agent', 'NOTE':'note', 'DBNOTE':'database_note'}
    # One regex pass prevents visitor data from being interpreted as template tokens.
    import re
    result = re.sub(r'@@([A-Z]+)@@', lambda m: html.escape(str(data[tokens[m[1]]])), template)
    return result.encode('utf-8')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64
    def __init__(self, address, handler, database, trusted_proxy):
        self.database = database
        self.trusted_proxy = trusted_proxy
        self.slots = threading.BoundedSemaphore(48)
        self.template = (ROOT / 'site/index.html').read_text()
        self.static = { '/style.css': ('text/css; charset=utf-8', (ROOT/'site/style.css').read_bytes()),
                        '/app.js': ('text/javascript; charset=utf-8', (ROOT/'site/app.js').read_bytes()) }
        self.static['/status/'] = ('text/html; charset=utf-8', (ROOT/'site/status/index.html').read_bytes())
        for name, mime in [('style.css','text/css'),('app.js','text/javascript'),('format.js','text/javascript')]:
            self.static['/status/'+name] = (mime+'; charset=utf-8', (ROOT/'site/status'/name).read_bytes())
        for path in (ROOT/'site/assets').iterdir():
            if path.suffix == '.svg':
                self.static['/assets/'+path.name] = ('image/svg+xml', path.read_bytes())
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        print('IP Answers: request failed (visitor details omitted)', flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = 'IPAnswers'
    sys_version = ''
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        pass

    def send_error(self, code, message=None, explain=None):
        self.reply(code, 'text/plain; charset=utf-8', b'Request rejected\n')

    def reply(self, status: int, content_type: str, content: bytes):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'private, no-store, max-age=0')
        self.send_header('CDN-Cache-Control', 'no-store')
        self.send_header('Cloudflare-CDN-Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', CSP)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Permissions-Policy', 'geolocation=(), camera=(), microphone=()')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(content)

    def do_POST(self):
        def error(code, message):
            self.reply(code,'application/json; charset=utf-8',json.dumps({'error':message}).encode())
        if urlsplit(self.path).path != '/api/status':
            error(404,'Not found')
            return
        origin=self.headers.get('Origin')
        host=self.headers.get('Host','')
        if origin and origin not in ('https://'+host,'http://'+host):
            error(403,'Use this endpoint from its own site.')
            return
        if self.headers.get_content_type() != 'application/json':
            error(415,'Send application/json.')
            return
        lengths=self.headers.get_all('Content-Length',[])
        if len(lengths)!=1 or self.headers.get('Transfer-Encoding'):
            error(411,'A single Content-Length is required.')
            return
        try:
            length=int(lengths[0])
            if not 0<length<=65536:
                error(413,'Request too large.')
                return
            data=json.loads(self.rfile.read(length))
            values=data.get('urls') if isinstance(data,dict) else None
            if not isinstance(values,list) or not 1<=len(values)<=checker.MAX_URLS or any(not isinstance(v,str) or not v.strip() or len(v)>checker.MAX_URL_LENGTH for v in values):
                error(400,'Send between 1 and 20 URLs, at most 2048 characters each.')
                return
        except (ValueError,UnicodeError):
            error(400,'Invalid JSON.')
            return
        peer=parse_address(self.client_address[0])
        ip=self.headers.get('X-IPAnswers-IP','') if self.server.trusted_proxy and peer.is_loopback else str(peer)
        try:key=str(parse_address(ip))
        except ValueError:
            error(400,'The connection address could not be verified.')
            return
        if not checker.authorize(key,len(values)):
            error(429,'Check limit reached. Wait a minute and try again.')
            return
        results=checker.check_batch(values)
        if results is None:
            error(503,'The checker is busy. Try again shortly.')
            return
        self.reply(200,'application/json; charset=utf-8',json.dumps({'results':results,'vantage':'London server','method':'HTTP GET headers'},ensure_ascii=True).encode())

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/status':
            self.send_response(308)
            self.send_header('Location','/status/')
            self.send_header('Content-Length','0')
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            return
        if path in self.server.static:
            mime, body = self.server.static[path]
            self.reply(200, mime, body)
            return
        if path == '/healthz':
            _, _, available, _ = self.server.database.lookup('8.8.8.8')
            self.reply(200 if available else 503, 'application/json', json.dumps({'ok':available}).encode())
            return
        if path == '/robots.txt':
            self.reply(200, 'text/plain', b'User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /ip\n')
            return
        if path not in ('/', '/api/me', '/ip'):
            self.reply(404, 'text/plain', b'Not found\n')
            return
        peer = parse_address(self.client_address[0])
        # Only our loopback reverse proxy may set this header; it overwrites every request.
        ip = self.headers.get('X-IPAnswers-IP', '') if self.server.trusted_proxy and peer.is_loopback else str(peer)
        data = details(ip, self.headers.get('User-Agent', '')[:4096], self.server.database)
        if path == '/api/me':
            self.reply(200, 'application/json; charset=utf-8', json.dumps(data, ensure_ascii=False).encode())
        elif path == '/ip':
            self.reply(200, 'text/plain; charset=utf-8', (data['ip']+'\n').encode())
        else:
            self.reply(200, 'text/html; charset=utf-8', render(self.server.template, data))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8764)
    parser.add_argument('--data-dir', type=Path, default=ROOT/'data')
    parser.add_argument('--behind-proxy', '--behind-caddy', dest='behind_caddy', action='store_true', help='Trust a proxy-set header from loopback only')
    args = parser.parse_args()
    database = GeoDatabase(args.data_dir.resolve())
    server = Server(('127.0.0.1', args.port), Handler, database, args.behind_caddy)
    print(f'IP Answers listening on 127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
