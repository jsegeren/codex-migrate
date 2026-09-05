(() => {
  'use strict';
  const button = document.getElementById('checkout-button');
  const status = document.getElementById('checkout-status');
  const panel = document.getElementById('checkout-panel');
  if (!button || !status || !panel) return;
  let busy = false;
  // Reuse the same request ID on uncertain retries, including a reload in this
  // tab. This is local checkout state, not an analytics/user identifier.
  const key = 'codex-migrate-checkout-attempt';
  let attempt;
  try { attempt = JSON.parse(sessionStorage.getItem(key)); } catch { /* Storage may be unavailable. */ }
  const now = Date.now();
  if (!attempt || !/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(attempt.id || '') ||
      !Number.isSafeInteger(attempt.at) || now < attempt.at || now - attempt.at > 30 * 60 * 1000) {
    attempt = { id: crypto.randomUUID(), at: now };
  }
  button.addEventListener('click', async () => {
    if (busy) return;
    const hadFocus = document.activeElement === button;
    busy = true; button.disabled = true;
    status.textContent = 'Opening secure checkout…';
    try {
      try { sessionStorage.setItem(key, JSON.stringify(attempt)); } catch { /* In-memory retry remains usable. */ }
      const response = await fetch('/api/checkout', { method: 'POST', credentials: 'omit', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requestId: attempt.id }),
        signal: AbortSignal.timeout(45000) });
      const data = await response.json();
      if (!response.ok) throw Error(data.error || 'unavailable');
      const url = new URL(data.url);
      if (url.origin !== 'https://checkout.stripe.com' || url.username || url.password) throw Error('unavailable');
      location.assign(url.toString());
    } catch (error) {
      status.textContent = error.message === 'checkout_closed'
        ? 'Sales are not open right now. Please email Josh for help.'
        : 'Checkout could not open. Try again or email Josh. If you already paid, use your delivery email—do not pay again.';
    } finally {
      busy = false; button.disabled = false;
      if (hadFocus && document.activeElement === document.body) button.focus();
    }
  });
  fetch('/api/availability', { credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(8000) })
    .then(async response => {
      if (!response.ok) return;
      const data = await response.json();
      if (data.available !== true || data.priceUSD !== 50 || !['arm64', 'x86_64'].includes(data.architecture)) return;
      const platform = data.architecture === 'arm64' ? 'Apple silicon Macs' : 'Intel Macs';
      document.getElementById('checkout-platform').textContent = `For ${platform}. $50 USD plus applicable tax. Secure checkout through Stripe.`;
      document.getElementById('edition-state').textContent = 'Available now';
      document.getElementById('edition-signed').textContent = 'Signed and notarized Mac app';
      document.getElementById('edition-disclosure').hidden = true;
      // A slow readiness response must not remove a form someone is using.
      const launch = document.getElementById('launch-email');
      if (!launch.contains(document.activeElement) && !document.getElementById('launch-address').value) launch.hidden = true;
      document.getElementById('hero-availability').textContent = 'Open source · Mac app available';
      document.getElementById('purchase-faq').textContent = `Yes. The packaged app is $50 USD for ${platform}, including best-effort support. The CLI and source remain free.`;
      const hero = document.getElementById('hero-paid-link');
      hero.href = '#founding-edition'; hero.textContent = 'Get the Mac app — $50'; hero.removeAttribute('data-analytics-event');
      panel.hidden = false;
    }).catch(() => { /* Launch-email fallback stays usable when readiness cannot be checked. */ });
})();
