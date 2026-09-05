(() => {
  'use strict';
  const status = document.getElementById('purchase-status');
  const download = document.getElementById('purchase-download');
  const retry = document.getElementById('purchase-retry');
  const checksum = document.getElementById('purchase-checksum');
  const integrity = document.getElementById('purchase-integrity');
  // Fragment credentials never reach server access logs or analytics. Remove
  // them from this history entry immediately; keep only in this page's memory.
  const credential = location.hash.slice(1);
  if (location.hash) history.replaceState(null, '', location.pathname);
  let token = credential.startsWith('session=') ? null : credential;
  let busy = false;
  async function call(action, value) {
    // Keep same-origin hosting authentication on protected previews. Purchase
    // authority still comes from the explicit credential and fresh Stripe read.
    const response = await fetch('/api/purchase', { method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, credential: value }),
      signal: AbortSignal.timeout(15000) });
    if (response.status === 429) throw new Error('rate_limited');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'temporarily_unavailable');
    return data;
  }
  async function check(startDownload = false) {
    if (busy) return;
    const initiatingControl = document.activeElement;
    busy = true; download.disabled = true; retry.disabled = true;
    status.textContent = 'Checking your purchase…';
    try {
      if (!token) token = (await call('status', credential.slice('session='.length))).token;
      const result = await call('download', token);
      const url = new URL(result.url);
      if (url.protocol !== 'https:' || !/^[a-z0-9]{8,64}\.private\.blob\.vercel-storage\.com$/.test(url.hostname) ||
          url.port || url.username || url.password || url.hash || !url.search ||
          !/^[a-f0-9]{64}$/.test(result.sha256) ||
          !/^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.zip$/.test(result.filename) ||
          !['live', 'sandbox'].some(mode => url.pathname === `/${mode}/${result.sha256}/${result.filename}`) ||
          !Number.isSafeInteger(result.expiresAt) || result.expiresAt <= 0) throw new Error('temporarily_unavailable');
      status.textContent = 'Your purchase is verified. Keep your delivery email to return to this download.';
      checksum.textContent = `Archive SHA-256: ${result.sha256}`; integrity.hidden = false;
      download.hidden = false; retry.hidden = true;
      if (startDownload) {
        status.textContent = 'Download requested. Check your browser’s downloads. If it stops, use Download for Mac to try again.';
        location.assign(url.toString());
      }
    } catch (error) {
      const messages = {
        rate_limited: 'Too many download checks. Wait a minute, then select Check again. Do not purchase again.',
        checkout_closed: 'Checkout is not open yet. If you have a payment receipt, email Josh for help.',
        release_unavailable: 'Your download is temporarily unavailable. Please email Josh; do not purchase again.',
        invalid_link: 'This download link is invalid. Reopen the link from your purchase email or email Josh.',
        purchase_not_verified: 'We could not verify a completed payment yet. Check again shortly or email Josh. Do not purchase again.',
        purchase_requires_support: 'This purchase needs review. Please email Josh for help.',
      };
      status.textContent = messages[error.message] || 'We couldn’t check your download right now. Try again or email Josh. Do not purchase again.';
      download.hidden = true; retry.hidden = false; integrity.hidden = true;
    } finally {
      busy = false; download.disabled = false; retry.disabled = false;
      if ((document.activeElement === initiatingControl && initiatingControl.hidden) ||
          ([download, retry].includes(initiatingControl) && document.activeElement === document.body)) {
        (download.hidden ? retry : download).focus();
      }
    }
  }
  download.addEventListener('click', () => check(true));
  retry.addEventListener('click', () => check());
  // Opening another delivery link in this same tab must consume the new
  // fragment, rather than keep the previous purchase in memory.
  window.addEventListener('hashchange', () => { if (location.hash) location.reload(); });
  if (credential) check();
})();
