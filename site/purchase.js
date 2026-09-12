(() => {
  'use strict';
  const status = document.getElementById('purchase-status');
  const download = document.getElementById('purchase-download');
  const retry = document.getElementById('purchase-retry');
  const checksum = document.getElementById('purchase-checksum');
  const integrity = document.getElementById('purchase-integrity');
  // Strip private fragments from history. A short-lived, tab-scoped recovery
  // token survives reload; it is never payment authority without a server check.
  const storageKey = 'codex-migrate-purchase-v1';
  const recoveryLifetime = 30 * 60 * 1000;
  const validToken = value => typeof value === 'string' && value.length <= 330 &&
    /^cs_(?:live|test)_[A-Za-z0-9]+\.[a-f0-9]{64}$/.test(value);
  const forget = () => { try { sessionStorage.removeItem(storageKey); } catch {} };
  let savedAt = Date.now();
  const fragment = location.hash.slice(1);
  let credential = fragment;
  if (fragment) forget(); // A different/invalid link must never reuse an old purchase.
  else {
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey));
      const age = Date.now() - saved?.savedAt;
      if (validToken(saved?.token) && Number.isSafeInteger(saved.savedAt) &&
          age >= 0 && age < recoveryLifetime) {
        credential = saved.token; savedAt = saved.savedAt;
      } else forget();
    } catch { forget(); }
  }
  if (location.hash) history.replaceState(null, '', location.pathname);
  let token = credential.startsWith('session=') ? null : credential;
  let busy = false;
  let linkLifetime = 0, requestWallTime = 0, requestMonotonicTime = 0;
  function trackVerifiedPurchase() {
    let alreadyTracked = false;
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey));
      alreadyTracked = saved?.token === token && saved?.analyticsTracked === true;
      if (!alreadyTracked && validToken(token)) {
        sessionStorage.setItem(storageKey, JSON.stringify({ token, savedAt, analyticsTracked: true }));
      }
    } catch {
      // Analytics must never block a buyer whose browser disables storage.
    }
    if (!alreadyTracked) {
      document.dispatchEvent(new CustomEvent('codex-migrate:analytics-event', { detail: 'purchase' }));
    }
  }
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
  async function check() {
    if (busy) return;
    const initiatingControl = document.activeElement;
    busy = true; download.removeAttribute('href'); download.setAttribute('aria-disabled', 'true'); retry.disabled = true;
    status.textContent = 'Checking your purchase…';
    try {
      if (!token) token = (await call('status', credential.slice('session='.length))).token;
      // Measure age from before the request, conservatively including network
      // time. A wrong calendar clock does not invalidate a server-issued link;
      // wall elapsed time covers sleep, monotonic elapsed time clock rollback.
      requestWallTime = Date.now(); requestMonotonicTime = performance.now();
      const result = await call('download', token);
      const url = new URL(result.url);
      if (url.protocol !== 'https:' || !/^[a-z0-9]{8,64}\.private\.blob\.vercel-storage\.com$/.test(url.hostname) ||
          url.port || url.username || url.password || url.hash || !url.search ||
          !/^[a-f0-9]{64}$/.test(result.sha256) ||
          !/^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.zip$/.test(result.filename) ||
          !['live', 'sandbox'].some(mode => url.pathname === `/${mode}/${result.sha256}/${result.filename}`) ||
          !Number.isSafeInteger(result.expiresAt) || result.expiresAt <= 0 ||
          !Number.isSafeInteger(result.expiresInMs) || result.expiresInMs <= 0 || result.expiresInMs > 300000) {
        throw new Error('temporarily_unavailable');
      }
      linkLifetime = result.expiresInMs;
      if (validToken(token)) {
        try {
          const saved = JSON.parse(sessionStorage.getItem(storageKey));
          const analyticsTracked = saved?.token === token && saved?.analyticsTracked === true;
          sessionStorage.setItem(storageKey, JSON.stringify({ token, savedAt, analyticsTracked }));
        } catch {}
      }
      status.textContent = 'Your purchase is verified. Select Download for Mac to save the file.';
      checksum.textContent = `Archive SHA-256: ${result.sha256}`; integrity.hidden = false;
      download.setAttribute('href', url.toString()); download.removeAttribute('aria-disabled');
      download.hidden = false; retry.hidden = true;
      trackVerifiedPurchase();
    } catch (error) {
      if (['invalid_link', 'purchase_requires_support', 'purchase_not_verified'].includes(error.message)) forget();
      const messages = {
        rate_limited: 'Too many download checks. Wait a minute, then select Check again. Do not purchase again.',
        checkout_closed: 'Checkout is not open yet. If you have a payment receipt, email Joshua for help.',
        release_unavailable: 'Your download is temporarily unavailable. Please email Joshua; do not purchase again.',
        invalid_link: 'This download link is invalid. Reopen the link from your purchase email or email Joshua.',
        purchase_not_verified: 'We could not verify a completed payment yet. Check again shortly or email Joshua. Do not purchase again.',
        purchase_requires_support: 'This purchase needs review. Please email Joshua for help.',
      };
      status.textContent = messages[error.message] || 'We couldn’t check your download right now. Try again or email Joshua. Do not purchase again.';
      download.removeAttribute('href'); download.setAttribute('aria-disabled', 'true');
      download.hidden = true; retry.hidden = false; integrity.hidden = true;
      retry.textContent = 'Check again';
    } finally {
      busy = false; retry.disabled = false;
      if ((document.activeElement === initiatingControl && initiatingControl.hidden) ||
          ([download, retry].includes(initiatingControl) && document.activeElement === document.body)) {
        (download.hidden ? retry : download).focus();
      }
    }
  }
  download.addEventListener('click', event => {
    if (busy) { event.preventDefault(); return; }
    if (!download.getAttribute('href')) { event.preventDefault(); check(); return; }
    const age = Math.max(Date.now() - requestWallTime, performance.now() - requestMonotonicTime);
    if (age >= linkLifetime - 5000) { event.preventDefault(); check(); return; }
    status.textContent = 'Download requested. Check your browser’s downloads. If it stops, select Get a fresh link below.';
    retry.textContent = 'Get a fresh link'; retry.hidden = false;
  });
  retry.addEventListener('click', () => check());
  // Opening another delivery link in this same tab must consume the new
  // fragment, rather than keep the previous purchase in memory.
  window.addEventListener('hashchange', () => { if (location.hash) location.reload(); });
  if (credential) check();
})();
