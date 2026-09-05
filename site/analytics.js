(() => {
  "use strict";

  const MEASUREMENT_ID = "G-1MZ87MY2X4";
  const STORAGE_KEY = "codex-migrate.analytics-consent.v1";
  const GRANTED = "granted";
  const DENIED = "denied";
  const PUBLIC_HOSTS = new Set(["migrate.segeren.com", "codex-migrate.vercel.app"]);
  let tagLoaded = false;
  let consentNotice = null;

  function readConsent() {
    try {
      return window.localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  }

  function writeConsent(value) {
    try {
      window.localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // A blocked storage API should not prevent the visitor from using the site.
    }
  }

  function clearAnalyticsCookies() {
    const names = ["_ga", `_ga_${MEASUREMENT_ID.replace("G-", "")}`];
    for (const name of names) {
      document.cookie = `${name}=; Max-Age=0; Path=/; SameSite=Lax`;
    }
  }

  function sendEvent(name) {
    if (readConsent() !== GRANTED || typeof window.gtag !== "function") return;
    window.gtag("event", name, { transport_type: "beacon" });
  }

  function loadGoogleTag() {
    if (tagLoaded || readConsent() !== GRANTED || !PUBLIC_HOSTS.has(window.location.hostname)) return;
    tagLoaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function gtag() { window.dataLayer.push(arguments); };
    window.gtag("js", new Date());
    window.gtag("config", MEASUREMENT_ID);

    const script = document.createElement("script");
    script.async = true;
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(MEASUREMENT_ID)}`;
    document.head.appendChild(script);

    const pageEvent = document.body.dataset.analyticsEvent;
    if (pageEvent) sendEvent(pageEvent);
  }

  function hideConsentNotice() {
    if (!consentNotice) return;
    consentNotice.remove();
    consentNotice = null;
  }

  function showConsentNotice() {
    if (consentNotice) return;
    consentNotice = document.createElement("section");
    consentNotice.className = "analytics-consent";
    consentNotice.setAttribute("role", "region");
    consentNotice.setAttribute("aria-label", "Website analytics choice");
    consentNotice.innerHTML = `
      <div>
        <strong>Help us improve this website?</strong>
        <p>Optional Google Analytics counts visits and launch-email conversions. It never sees your Codex workspace. <a href="/privacy.html#website-analytics">Privacy details</a></p>
      </div>
      <div class="analytics-consent-actions">
        <button class="button button-primary" type="button" data-analytics-accept>Accept analytics</button>
        <button class="button button-secondary" type="button" data-analytics-decline>No thanks</button>
      </div>`;
    document.body.appendChild(consentNotice);
    consentNotice.querySelector("[data-analytics-accept]").addEventListener("click", () => {
      writeConsent(GRANTED);
      hideConsentNotice();
      loadGoogleTag();
    });
    consentNotice.querySelector("[data-analytics-decline]").addEventListener("click", () => {
      writeConsent(DENIED);
      window[`ga-disable-${MEASUREMENT_ID}`] = true;
      clearAnalyticsCookies();
      hideConsentNotice();
      if (tagLoaded) window.location.reload();
    });
  }

  document.addEventListener("click", (event) => {
    const preferenceButton = event.target.closest("[data-analytics-preferences]");
    if (preferenceButton) {
      event.preventDefault();
      showConsentNotice();
      consentNotice.querySelector("button").focus();
      return;
    }
    const trackedLink = event.target.closest("[data-analytics-event]");
    if (trackedLink) sendEvent(trackedLink.dataset.analyticsEvent);
  });

  const consent = readConsent();
  if (consent === GRANTED) loadGoogleTag();
  else if (consent !== DENIED) showConsentNotice();
})();
