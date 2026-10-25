#!/usr/bin/env python3
"""Read-only web-server inventory. Never starts/stops services or edits files."""
import shutil
import subprocess


def diagnose():
    commands = [
        ('Web listeners on ports 80 and 443', ['ss','-ltnp','( sport = :80 or sport = :443 )']),
        ('Caddy system service', ['systemctl','show','caddy','--no-pager','--property=LoadState,ActiveState,SubState,FragmentPath,ExecMainStatus']),
        ('Nginx system service', ['systemctl','show','nginx','--no-pager','--property=LoadState,ActiveState,SubState,FragmentPath']),
        ('Apache system service', ['systemctl','show','apache2','--no-pager','--property=LoadState,ActiveState,SubState,FragmentPath']),
        ('Recent Caddy startup messages', ['journalctl','-u','caddy','-n','20','--no-pager','-o','cat']),
        ('Running web containers', ['docker','ps','--format','{{.Names}}\t{{.Image}}\t{{.Ports}}']),
    ]
    for heading, command in commands:
        print('\n'+heading, flush=True)
        if not shutil.which(command[0]):
            print(command[0]+': not installed', flush=True)
            continue
        try:
            subprocess.run(command, check=False, timeout=15)
        except subprocess.TimeoutExpired:
            print('Command timed out', flush=True)
    print('\nDiagnostic finished. No services or configuration were changed.', flush=True)

if __name__ == '__main__':
    diagnose()
