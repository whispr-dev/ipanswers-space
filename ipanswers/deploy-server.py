#!/usr/bin/env python3
"""Root installer for Ubuntu + active Nginx or Caddy. Preserves unrelated routes.

On LON1 (Caddy since 30 Oct 2026) the lon1-caddy-kit already has an ipanswers.space block. If
that block sends the site to 127.0.0.1:8764, it is accepted and left exactly as it is; only the
app is deployed. A site block this script manages itself (BEGIN/END markers) is still updated.
"""
from __future__ import annotations
import argparse
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import urllib.request
from diagnose_server import diagnose
from caddy_site import fetch_https, route_targets

SOURCE = Path(__file__).resolve().parent
BASE = Path('/opt/ipanswers')
DATA = Path('/var/lib/ipanswers')
CADDY = Path('/etc/caddy/Caddyfile')
UNITS = Path('/etc/systemd/system')
BEGIN = '# BEGIN IPANSWERS.SPACE (managed by ipanswers)'
END = '# END IPANSWERS.SPACE'
CF_FALLBACK = '''173.245.48.0/20 103.21.244.0/22 103.22.200.0/22 103.31.4.0/22 141.101.64.0/18 108.162.192.0/18 190.93.240.0/20 188.114.96.0/20 197.234.240.0/22 198.41.128.0/17 162.158.0.0/15 104.16.0.0/13 104.24.0.0/14 172.64.0.0/13 131.0.72.0/22 2400:cb00::/32 2606:4700::/32 2803:f800::/32 2405:b500::/32 2405:8100::/32 2a06:98c0::/29 2c0f:f248::/32'''.split()
NAMES = ['ipanswers.service','ipanswers-update.service','ipanswers-update.timer']


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def atomic(path: Path, content: str):
    tmp = path.with_name(path.name+'.ipanswers-tmp')
    tmp.write_text(content)
    tmp.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o644)
    os.replace(tmp, path)


def cloudflare_ranges():
    try:
        ranges = []
        for family in ('v4','v6'):
            req = urllib.request.Request('https://www.cloudflare.com/ips-'+family, headers={'User-Agent':'IPAnswers installer'})
            with urllib.request.urlopen(req, timeout=15) as response:
                values = response.read(16384).decode().split()
            if len(values) < 5:
                raise ValueError('Incomplete Cloudflare ranges')
            ranges.extend(str(ipaddress.ip_network(value)) for value in values)
        return ranges
    except Exception:
        print('Cloudflare range download unavailable; using official ranges verified 2026-10-25.')
        return CF_FALLBACK


def site_block(ranges):
    return BEGIN + '\n' + '''ipanswers.space {
    encode zstd gzip
    header {
        Cache-Control "private, no-store, max-age=0"
        CDN-Cache-Control "no-store"
        Cloudflare-CDN-Cache-Control "no-store"
        -Server
    }
    @cloudflare remote_ip ''' + ' '.join(ranges) + '''
    handle @cloudflare {
        reverse_proxy 127.0.0.1:8764 {
            transport http {
                response_header_timeout 65s
            }
            header_up X-IPAnswers-IP {http.request.header.CF-Connecting-IP}
        }
    }
    handle {
        reverse_proxy 127.0.0.1:8764 {
            transport http {
                response_header_timeout 65s
            }
            header_up X-IPAnswers-IP {http.request.remote.host}
        }
    }
}
''' + END + '\n'


def replace_block(original, block):
    if BEGIN in original:
        if original.count(BEGIN) != 1 or original.count(END) != 1:
            raise RuntimeError('Ambiguous managed block; Caddyfile was not changed')
        start, finish = original.index(BEGIN), original.index(END)+len(END)
        if finish < start:
            raise RuntimeError('Invalid managed block')
        return original[:start] + block.rstrip() + original[finish:]
    return original.rstrip()+'\n\n'+block


def main():
    os.umask(0o022)
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo python3 deploy-server.py')
    for name in ('systemctl','python3','useradd','runuser'):
        if not shutil.which(name):
            raise RuntimeError(f'Required command missing: {name}')
    nginx = None
    keep_caddy = False
    nginx_state = subprocess.run(['systemctl','is-active','--quiet','nginx'],check=False)
    if nginx_state.returncode == 0:
        if not shutil.which('nginx'):
            raise RuntimeError('Nginx service is active but its executable is unavailable')
        from nginx_frontend import NginxFrontend
        nginx = NginxFrontend()
        nginx.preflight()
    else:
        for command in ('caddy',):
            if not shutil.which(command):
                raise RuntimeError(f'Required command missing: {command}')
        if not CADDY.is_file():
            raise RuntimeError('/etc/caddy/Caddyfile is missing; existing Caddy installation required')
        if CADDY.is_symlink():
            raise RuntimeError('Caddyfile is a symlink; installer will not replace it')
        state = subprocess.run(['systemctl','is-active','--quiet','caddy'], check=False)
        if state.returncode != 0:
            diagnose()
            raise RuntimeError('The host caddy.service is not active. No application or web configuration was changed. '
                               'The diagnostic above identifies the existing web server; do not start a competing server.')
        run('caddy','validate','--config',str(CADDY),'--adapter','caddyfile')
        original = CADDY.read_text()
        adapted = run('caddy','adapt','--config',str(CADDY),'--adapter','caddyfile',capture_output=True,text=True).stdout
        # Inspect the active adapter output, including imported snippets, before adding a new host.
        def hosts(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == 'host' and isinstance(child, list):
                        yield from child
                    else:
                        yield from hosts(child)
            elif isinstance(value, list):
                for child in value:
                    yield from hosts(child)
        if BEGIN not in original and 'ipanswers.space' in set(hosts(json.loads(adapted))):
            dials = route_targets('ipanswers.space', json.loads(adapted))['dial']
            if not any(d in ('127.0.0.1:8764', 'localhost:8764', '[::1]:8764') for d in dials):
                raise RuntimeError('ipanswers.space already has a Caddy route, but it goes to '
                                   + (', '.join(dials) or 'no local app') + ', not 127.0.0.1:8764. Nothing was changed.')
            keep_caddy = True
            print('Caddy already sends ipanswers.space to 127.0.0.1:8764 (lon1-caddy-kit block); leaving the Caddyfile as it is.')
    prior_service = (UNITS/'ipanswers.service').exists()
    # Do not steal a port from another program.
    if not prior_service:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',8764))
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = Path('/var/backups/ipanswers')/stamp
    backup.mkdir(parents=True)
    if nginx:
        nginx.snapshot(backup)
        if nginx.path.exists():
            shutil.copy2(nginx.path, backup/'nginx-site.conf')
    else:
        shutil.copy2(CADDY, backup/'Caddyfile')
    for name in NAMES:
        if (UNITS/name).exists():
            shutil.copy2(UNITS/name, backup/name)
    previous = os.readlink(BASE/'current') if (BASE/'current').is_symlink() else None
    if (BASE/'current').exists() and previous is None:
        raise RuntimeError('/opt/ipanswers/current must be a managed symlink')
    (backup/'state.json').write_text(json.dumps({'previous_release':previous,'prior_service':prior_service}))
    release = BASE/'releases'/stamp
    release.mkdir(parents=True)
    for name in ('server.py','checker.py','update_data.py','requirements.txt'):
        shutil.copy2(SOURCE/name, release/name)
    shutil.copytree(SOURCE/'site',release/'site')
    if subprocess.run(['id','-u','ipanswers'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        run('useradd','--system','--home-dir','/nonexistent','--shell','/usr/sbin/nologin','ipanswers')
    DATA.mkdir(parents=True,exist_ok=True)
    shutil.chown(DATA,user='ipanswers',group='ipanswers')
    # Install only the missing Ubuntu venv support; never upgrade the host runtime.
    probe = subprocess.run(['python3','-c','import venv, ensurepip'],capture_output=True)
    if probe.returncode:
        run('apt-get','update')
        run('apt-get','install','-y','python3-venv')
    run('python3','-m','venv',str(release/'venv'))
    python = str(release/'venv/bin/python')
    run(python,'-m','pip','install','--disable-pip-version-check','-r',str(release/'requirements.txt'))
    # Stop any previous updater to prevent simultaneous monthly database writes.
    subprocess.run(['systemctl','stop','ipanswers-update.timer','ipanswers-update.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        run('runuser','-u','ipanswers','--',python,str(release/'update_data.py'),'--data-dir',str(DATA))
    except Exception:
        if (backup/'ipanswers-update.timer').exists():
            subprocess.run(['systemctl','start','ipanswers-update.timer'])
        raise
    service = '''[Unit]
Description=IP Answers connection information
After=network.target
[Service]
Type=simple
User=ipanswers
Group=ipanswers
WorkingDirectory=/opt/ipanswers/current
ExecStart=/opt/ipanswers/current/venv/bin/python /opt/ipanswers/current/server.py --behind-proxy --data-dir /var/lib/ipanswers
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
MemoryMax=256M
TasksMax=64
UMask=0027
[Install]
WantedBy=multi-user.target
'''
    updater = '''[Unit]
Description=Refresh local DB-IP Lite databases
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
User=ipanswers
Group=ipanswers
ExecStart=/opt/ipanswers/current/venv/bin/python /opt/ipanswers/current/update_data.py --data-dir /var/lib/ipanswers
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/ipanswers
TimeoutStartSec=20min
UMask=0022
'''
    timer = '''[Unit]
Description=Keep IP Answers geolocation data current
[Timer]
OnCalendar=*-*-* 04:25:00 UTC
RandomizedDelaySec=2h
Persistent=true
[Install]
WantedBy=timers.target
'''
    ranges = cloudflare_ranges()
    config = None if (nginx or keep_caddy) else replace_block(original, site_block(ranges))
    changed = False
    try:
        changed = True
        link = BASE/'current-next'
        link.unlink(missing_ok=True)
        link.symlink_to(release)
        os.replace(link,BASE/'current')
        for name, content in zip(NAMES,(service,updater,timer)):
            atomic(UNITS/name,content)
        if config is not None:
            atomic(CADDY,config)
            run('caddy','validate','--config',str(CADDY),'--adapter','caddyfile')
        run('systemctl','daemon-reload')
        run('systemctl','enable','--now','ipanswers.service','ipanswers-update.timer')
        run('systemctl','restart','ipanswers.service')
        import time
        for attempt in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8764/healthz',timeout=2) as response:
                    if json.load(response).get('ok'):
                        break
            except Exception:
                time.sleep(.5)
        else:
            raise RuntimeError('Application health check failed')
        if nginx:
            nginx.activate(ranges)
        elif config is not None:
            run('systemctl','reload','caddy')
        if not nginx:
            try:
                status, _ = fetch_https('ipanswers.space', '/healthz')
                print(f'Checked through Caddy: https://ipanswers.space/healthz answered {status}.')
            except Exception as check_error:
                print('WARNING: could not check the site through Caddy ('+str(check_error)+'); the app itself is healthy on 127.0.0.1:8764.', file=sys.stderr)
        print('\nInstalled successfully: https://ipanswers.space')
        print('Backup: '+str(backup))
        print('DNS must point ipanswers.space to lon1. Cloudflare SSL mode: Full (strict).')
    except Exception:
        if changed:
            print('Installation failed. Restoring prior web configuration and application.')
            if nginx:
                try:
                    nginx.restore()
                except Exception as restore_error:
                    print('Web rollback needs attention: '+str(restore_error),file=sys.stderr)
            elif config is not None:
                shutil.copy2(backup/'Caddyfile',CADDY)
            subprocess.run(['systemctl','stop','ipanswers.service','ipanswers-update.timer'])
            if previous:
                (BASE/'current').unlink(missing_ok=True)
                (BASE/'current').symlink_to(previous)
            else:
                (BASE/'current').unlink(missing_ok=True)
            for name in NAMES:
                if (backup/name).exists():
                    shutil.copy2(backup/name,UNITS/name)
                else:
                    subprocess.run(['systemctl','disable',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    (UNITS/name).unlink(missing_ok=True)
            subprocess.run(['systemctl','daemon-reload'])
            if prior_service:
                subprocess.run(['systemctl','restart','ipanswers.service','ipanswers-update.timer'])
            if config is not None:
                subprocess.run(['systemctl','reload','caddy'])
        raise

if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('--diagnose', action='store_true')
        args = parser.parse_args()
        if args.diagnose:
            diagnose()
        else:
            main()
    except Exception as error:
        print('ERROR: '+str(error), file=sys.stderr)
        sys.exit(1)
