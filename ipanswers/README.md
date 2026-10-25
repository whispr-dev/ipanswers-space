# ipanswers.space — 1.1.0

A self-hosted IP utility, single/bulk website status checker and SkeleTrace Suite showcase for lon1.
Copyright © 2026 whispr.dev. Existing brand artwork remains the property of whispr.dev.

This release supports the actual London setup: **active Nginx on ports 80/443**.
It selects Nginx before checking Caddy and never starts, stops or modifies Caddy on that path.
It creates one isolated Nginx virtual host and keeps existing sites and Litehaus running.
Legacy installations with active host Caddy are also supported.

## Deploy from Windows

Requirements: PowerShell 7, Windows OpenSSH/tar, your existing `ssh lon1` alias and sudo access.
The server needs Ubuntu 22.04+ with an active Nginx or Caddy system service and Python 3.10+.

```powershell
Set-Location "$env:USERPROFILE\Downloads"
tar -xzf .\ipanswers-space-1.1.0.tar.gz
Set-Location .\ipanswers
.\Deploy.ps1
```

Enter your server sudo password when prompted. The first installation downloads approximately
130 MB of unpacked DB-IP Lite databases and installs maxminddb 3.2.0 in a private Python environment.
Missing Ubuntu python3-venv support is installed automatically. The Nginx path also installs the
Ubuntu Certbot package when needed. No Node.js, Docker or geolocation API account is required.

## Domain and HTTPS

Point the ipanswers.space A record at lon1. Add AAAA only if lon1 actually serves that IPv6 address.
HTTP on port 80 must be reachable for Let's Encrypt validation. No www hostname is required.

On Nginx, the installer adds `/etc/nginx/conf.d/ipanswers-space.conf` when the standard conf.d include
is present; otherwise it uses the standard sites-enabled include. It refuses an existing unmanaged
file or an exact ipanswers.space host already owned by another site. It never edits nginx.conf or
another site's configuration.

The new host first exposes only the ACME challenge on HTTP; other requests receive 503 until the
certificate exists. Certbot obtains a certificate with its webroot plugin, without stopping Nginx.
The final host redirects HTTP to HTTPS and proxies HTTPS to 127.0.0.1:8764. Nginx syntax is checked
before each reload. A valid existing certificate can keep HTTPS available during redeployment.

Certbot reuses the server's existing ACME account where possible. If registration is needed,
it registers without an email address and accepts the Let's Encrypt subscriber terms as part of
certificate provisioning. A dedicated timer checks renewal for this hostname twice daily and reloads
Nginx after renewal. Existing certificates are not deleted on rollback.

For Cloudflare: use Full (strict) after origin HTTPS is ready. If Cloudflare forces HTTPS before the
first origin certificate exists and blocks validation, temporarily switch this DNS record to DNS-only,
run deployment, then restore proxying. Keep Pseudo IPv4 off or in Add Header mode.
Do not force edge caching for this hostname: HTML, /api/me and /ip contain each caller's details.
The application sends browser and CDN no-store headers; Nginx proxy caching is explicitly off.

## Preservation and rollback

A dated backup under `/var/backups/ipanswers/` preserves any prior managed site, application units
and HTTPS renewal files. Application health is checked before activating the new virtual host.
If final deployment fails, the prior managed site/configuration and app are restored; a new virtual
host is removed. Other site files are not modified. Reloads let existing Nginx workers finish requests.
The frontend file uses distinct variable names and does not change global real-IP policies.
Installed OS packages, downloaded databases and issued certificates remain available after rollback.
A rollback error is reported explicitly and its backup retained.

## New in 1.1.0: website status checker

The IP page remains at `/`. The new checker is at **https://ipanswers.space/status/**, with a link
from the IP page. This is a complete update of IP Answers, using its existing service/port and domain.
It adds no extra public port, database, app service or DNS record.

- Enter one URL or up to 20, one per line. Bare hostnames default to HTTPS; duplicates are removed.
- Six user-triggered shortcuts: Google, GitHub, Wikipedia, Cloudflare, Microsoft and YouTube.
- Three browser requests run at a time and results appear as each finishes.
- Each result shows its actual HTTP status, response time, redirect count and a clear explanation.
- Individual Copy URL / Copy result buttons, Copy all and CSV export with formula protection.
- The same SkeleTrace Suite advertising and responsive desktop/mobile layout.

Checks run from London using server-side HTTP GET requests. Only headers are consumed; response
bodies are neither downloaded by the client code nor relayed to visitors. No remote JavaScript is run.
A 2xx reply is Available. 401/403/429 are Access limited, because a service may block this checker.
Other 4xx/5xx replies are HTTP errors, which means the endpoint was reachable. DNS, TLS, timeout,
network and checker failures are distinct. A single check is not a global outage verdict or proof
that the target application works. Timing measures DNS/TCP/TLS/headers, not an ICMP ping.

### Safety and resource limits

Public HTTP/HTTPS targets only; standard ports 80/443. Login credentials, private/reserved addresses,
cloud metadata addresses and IPv6 transition paths are blocked. Every DNS answer is checked; mixed
public/private responses are rejected. The connection pins a validated numeric IP, while HTTPS uses
the original hostname with normal certificate verification. Every redirect is revalidated; at most
three are followed. Local/shared VPC endpoints are not supported.

Each probe is a killable subprocess with an eight-second wall timeout. On Linux it also has a CPU
limit of four seconds and an address-space limit of 128 MiB. Four probes run concurrently, with at
most 24 reserved/queued jobs. Limits are 60 URL checks per IP/minute and 240 globally/minute, with
bounded in-memory counters. The existing app service retains its 256 MiB cgroup memory limit.
Busy or rate-limited requests receive an explicit error. The frontend never bypasses TLS verification.
The server ignores environment HTTP proxies and sends no visitor cookies, login data or credentials.
Only fixed checker headers are sent to targets. Browser requests use same-origin JSON POST;
cross-origin browser requests are rejected and no CORS allowance is enabled.

URLs and results exist in memory only, and are not saved as lookup history. Short-lived IP counters
enforce limits. Targets see London's server IP and the checker user-agent, not the visitor's cookies.
The privacy dialog explains that submitted URLs are sent to this server; visitors should not submit
confidential/credential-bearing links. No checks run automatically on page load, and no monitoring
or recurring external automation is installed.

The endpoint accepts `POST /api/status` with JSON `{"urls":["https://example.com/"]}` and returns
`results`, `vantage` and `method`. Direct API batches allow 1–20 URLs and at most 64 KiB JSON.
The browser checks individually for progressive results. Batches can take longer than one URL;
Nginx/Caddy response timeouts accommodate the bounded queue.

## What visitors get

- Public IPv4 or IPv6 used for the current connection, rendered in the initial HTML.
- Approximate location and routing organisation/ASN from local DB-IP Lite databases.
- User-agent string, safely escaped.
- Separate copy buttons for IP, IP version, location, ISP/network, ASN and user-agent.
- Copy all, refresh, JSON at /api/me and a plain address at /ip.
- A 50:50 desktop layout, stacked on phones; actual whispr.dev and SkeleTrace logos.
- SkeleTrace, OSINTropy, Maxwell's Demon Detector and CrowdWatch summaries and download links.

No app cookies, analytics, remote fonts, third-party advertising scripts or visitor lookup history.
Geolocation happens locally; individual visitor IPs are not sent to geolocation services.
DB-IP Lite city/ASN data are CC BY 4.0. The required attribution appears in the footer/privacy dialog.
A daily timer downloads each new monthly release once, verifies both databases and activates them
atomically. The app picks them up without a restart. It retains two releases and flags stale data.

An estimate may identify a VPN exit or ISP gateway. The routing organisation may differ from the
retail ISP. This page reports one connection's protocol; it does not test both or detect DNS/VPN leaks.
Hosting/Cloudflare may keep infrastructure logs or set security cookies under their own settings.

## Visitor-IP handling

The app binds only to loopback. Its proxy header is overwritten on every request.
Nginx uses the original socket peer, even if another site's global real-IP rules rewrite remote_addr.
Only official Cloudflare peers may supply CF-Connecting-IP; direct callers' spoofed headers are ignored.
No client-supplied arbitrary IP lookup endpoint is exposed. Missing data is shown as unavailable.
Application request concurrency is bounded and its systemd memory limit is 256 MB.

## Operations

```powershell
ssh lon1 'systemctl status ipanswers.service ipanswers-update.timer ipanswers-tls-renew.timer --no-pager'
ssh lon1 'curl -fsS http://127.0.0.1:8764/healthz'
ssh lon1 'sudo journalctl -u ipanswers.service -u ipanswers-update.service -n 60 --no-pager'
Invoke-RestMethod https://ipanswers.space/api/me
```

A read-only web-stack diagnostic remains available:

```powershell
.\Deploy.ps1 -Diagnose
```

## Development and checks

Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe .\update_data.py --data-dir .\data
.\.venv\Scripts\python.exe .\server.py --data-dir .\data
```

Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python update_data.py --data-dir data
.venv/bin/python server.py --data-dir data
```

Open http://127.0.0.1:8764. A local preview correctly shows loopback, not an external public address.
With Node.js installed, `node tests/test_controls.mjs
node --test tests/status-format.test.mjs tests/status-controls.test.mjs` checks all clipboard controls and refreshed values.
`--behind-proxy` (legacy alias --behind-caddy) is exclusively for the installed loopback reverse proxy.

## Validation and limits

42 Python tests cover backend contracts, header trust, source escaping, unavailable data, path safety,
Nginx selection, managed/unmanaged host protection, challenge bootstrap and rollback isolation.
Node clipboard checks verify each field, refreshed values, Copy all and disabled unavailable fields.
Real DB-IP databases were downloaded and queried for IPv4 and IPv6. Desktop and 390 px mobile layout,
copy, refresh rendering and privacy dialog were inspected in Chrome in prior verification.
Nginx 1.26.3 also validated the generated configuration in live local HTTPS-to-app tests.
Both direct and simulated Cloudflare requests resisted spoofing even with inherited real-IP rewriting;
ACME challenge serving and an adjacent Litehaus-shaped virtual host continued to work.
Additional verified local HTTP/TLS fixtures test pinned connection addresses, original-hostname SNI,
certificate acceptance/rejection, actual 403 responses and rejection of a private redirect. The status
POST endpoint was exercised through real Nginx HTTPS in both direct and simulated Cloudflare modes;
it ran the subprocess worker and blocked a private target. Five Node tests cover input parsing,
progressive form submission, copy/export contents, formula escaping, same-origin request behaviour
and bulk limits. Original IP-page clipboard contract checks still pass.
Chrome desktop/mobile UI flows were checked against clearly labelled, local test responses. The
build environment cannot resolve public targets, so it was not used to claim live service availability.
Public probes, DNS behaviour and results from lon1 must be verified after deployment.
Components are tested locally; the full root installer, live certificate issuance and final public-domain
verification require execution on lon1.

## References

Branding: https://skeletrace.com/home/ and https://whispr.dev/products/
Downloads: https://skeletrace.com/download/ and https://skeletrace.com/works-with/
Logos: whisprer-specops/skeletrace assets/skeletrace-mark.svg; whispr-dev/website-whispr-dev
whispr-dev-site/site/assets/whispr-logo.svg. The graph illustration contains no visitor telemetry.

Database: https://db-ip.com/db/download/ip-to-city-lite and https://db-ip.com/db/download/ip-to-asn-lite
Reader: https://pypi.org/project/maxminddb/3.2.0/
Proxy: https://nginx.org/en/docs/http/ngx_http_proxy_module.html
Peer preservation: https://nginx.org/en/docs/http/ngx_http_realip_module.html
Geo/map: https://nginx.org/en/docs/http/ngx_http_geo_module.html and https://nginx.org/en/docs/http/ngx_http_map_module.html
TLS: https://eff-certbot.readthedocs.io/en/stable/using.html#webroot
Cloudflare ranges: https://www.cloudflare.com/ips-v4 and https://www.cloudflare.com/ips-v6

Status-checker reference APIs:
https://docs.python.org/3.10/library/http.client.html
https://docs.python.org/3.10/library/socket.html
https://docs.python.org/3.10/library/ssl.html
https://docs.python.org/3.10/library/subprocess.html
https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch
