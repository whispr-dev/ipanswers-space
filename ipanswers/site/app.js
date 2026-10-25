'use strict';
const byId = id => document.getElementById(id);
let toastTimer;
function notify(message) {
  byId('toast').textContent = message;
  byId('toast').classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => byId('toast').classList.remove('visible'), 3200);
}
async function copy(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const input = document.createElement('textarea');
      input.value = text; input.style.position = 'fixed'; input.style.opacity = '0';
      document.body.append(input); input.select();
      const success = document.execCommand('copy'); input.remove();
      if (!success) throw new Error('Copy unavailable');
    }
    notify('Copied to clipboard');
  } catch (_) { notify('Copy unavailable. Select the text to copy it manually.'); }
}
function ready() {
  const valid = !byId('ip').textContent.includes('@@') && byId('ip').textContent !== 'Unavailable';
  byId('copy-ip').disabled = !valid; byId('copy-all').disabled = !valid;
  byId('copy-ua').disabled = false;
  byId('copy-family').disabled = !valid;
  for (const field of ['location', 'isp', 'asn']) {
    const value = byId(field).textContent.trim();
    byId('copy-' + field).disabled = !value || value.includes('@@') || value === 'Not available' || value === 'Unavailable' || value === 'Network record not available' || value === 'No verified connection address';
  }
  byId('ip').classList.toggle('ipv6', byId('family').textContent === 'IPv6');
}
byId('copy-ip').addEventListener('click', () => copy(byId('ip').textContent));
for (const field of ['family', 'location', 'isp', 'asn']) {
  byId('copy-' + field).addEventListener('click', () => copy(byId(field).textContent));
}
byId('copy-ua').addEventListener('click', () => copy(byId('ua').textContent));
byId('copy-all').addEventListener('click', () => copy([
  `Public IP: ${byId('ip').textContent}`, `Protocol: ${byId('family').textContent}`,
  `Location estimate: ${byId('location').textContent}`, `ISP / network: ${byId('isp').textContent}`,
  byId('asn').textContent, `User agent: ${byId('ua').textContent}`
].join('\n')));
byId('refresh').addEventListener('click', async () => {
  const button = byId('refresh'); button.disabled = true; button.textContent = 'Refreshing…';
  try {
    const response = await fetch('/api/me', {cache:'no-store', signal:AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('Lookup failed');
    const data = await response.json();
    for (const [id, key] of Object.entries({ip:'ip',family:'family',location:'location',isp:'isp',asn:'asn_label',ua:'user_agent','connection-note':'note','lookup-note':'database_note'})) {
      byId(id).textContent = data[key];
    }
    ready(); notify('Connection details refreshed');
  } catch (_) { notify('Could not refresh. Your previous details are still shown.'); }
  finally { button.disabled = false; button.textContent = '↻ Refresh details'; }
});
const dialog = byId('privacy');
byId('privacy-open').addEventListener('click', () => dialog.showModal());
byId('privacy-close').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => { if (event.target === dialog) { const r=dialog.getBoundingClientRect(); if(event.clientX<r.left || event.clientX>r.right || event.clientY<r.top || event.clientY>r.bottom) dialog.close(); } });
ready();
