(() => {
  "use strict";

  const MEASUREMENT_ID = "G-1MZ87MY2X4";
  const STORAGE_KEY = "codex-migrate.analytics-consent.v1";
  const GRANTED = "granted";
  const DENIED = "denied";
  const PUBLIC_HOSTS = new Set(["migrate.segeren.com", "codex-migrate.vercel.app"]);
  let consentNotice = null;
  let analyticsMode = "consent";
  let currentChoice = null;
  const pendingEvents = [];

  function readConsent() {
    try {
      return window.localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  }

  function writeConsent(value) {
    currentChoice = value;
    try {
      window.localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // A blocked storage API should not prevent the visitor from using the site.
    }
  }

  function clearAnalyticsCookies() {
    const streamSuffix = MEASUREMENT_ID.replace("G-", "");
    const names = ["cm_ga", `cm_ga_${streamSuffix}`, `_ga_${streamSuffix}`];
    const host = window.location.hostname;
    const hostParts = host.split(".");
    const parentDomain = hostParts.length > 2 ? hostParts.slice(-2).join(".") : "";
    for (const name of names) {
      document.cookie = `${name}=; Max-Age=0; Path=/; SameSite=Lax`;
      document.cookie = `${name}=; Max-Age=0; Path=/; Domain=${host}; SameSite=Lax`;
      if (parentDomain && parentDomain !== host) {
        document.cookie = `${name}=; Max-Age=0; Path=/; Domain=.${parentDomain}; SameSite=Lax`;
      }
    }
  }

  function consentValues(granted) {
    return {
      analytics_storage: granted ? "granted" : "denied",
      ad_storage: granted ? "granted" : "denied",
      ad_user_data: granted ? "granted" : "denied",
      ad_personalization: "denied",
    };
  }

  function sendEvent(name) {
    if (typeof name !== "string" || !/^[a-z][a-z0-9_]{0,39}$/.test(name)) return;
    if (typeof window.gtag !== "function") {
      if (pendingEvents.length < 20) pendingEvents.push(name);
      return;
    }
    window.gtag("event", name, { transport_type: "beacon" });
  }

  function startGoogleTag(granted) {
    window.dataLayer = window.dataLayer || [];
    window.gtag = function gtag() { window.dataLayer.push(arguments); };
    window.gtag("consent", "default", consentValues(granted));
    window.gtag("set", "ads_data_redaction", true);
    window.gtag("js", new Date());
    window.gtag("config", MEASUREMENT_ID, {
      cookie_domain: "none",
      cookie_expires: 60 * 60 * 24 * 425,
      cookie_prefix: "cm",
      cookie_update: true,
    });

    const script = document.createElement("script");
    script.async = true;
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(MEASUREMENT_ID)}`;
    document.head.appendChild(script);

    const pageEvent = document.body.dataset.analyticsEvent;
    if (pageEvent) sendEvent(pageEvent);
    for (const name of pendingEvents.splice(0)) sendEvent(name);
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
      <strong>Analytics cookies?</strong>
      <p>Allow Google Analytics to measure visits, audience, and conversions. It never sees your Codex workspace. <a href="/privacy.html#website-analytics">Details</a></p>
      <div class="analytics-consent-actions">
        <button class="button button-primary" type="button" data-analytics-accept>Allow</button>
        <button class="button button-secondary" type="button" data-analytics-decline>Decline</button>
      </div>`;
    document.body.appendChild(consentNotice);
    consentNotice.querySelector("[data-analytics-accept]").addEventListener("click", () => {
      writeConsent(GRANTED);
      if (typeof window.gtag === "function") {
        window.gtag("consent", "update", consentValues(true));
      }
      hideConsentNotice();
    });
    consentNotice.querySelector("[data-analytics-decline]").addEventListener("click", () => {
      writeConsent(DENIED);
      if (typeof window.gtag === "function") {
        window.gtag("consent", "update", consentValues(false));
      }
      clearAnalyticsCookies();
      hideConsentNotice();
    });
  }

  function reopenPreferences() {
    showConsentNotice();
    consentNotice.querySelector("button").focus();
  }

  document.addEventListener("click", (event) => {
    const preferenceButton = event.target.closest("[data-analytics-preferences]");
    if (preferenceButton) {
      event.preventDefault();
      reopenPreferences();
      return;
    }
    const trackedLink = event.target.closest("[data-analytics-event]");
    if (trackedLink) sendEvent(trackedLink.dataset.analyticsEvent);
  });

  // Purchase verification happens asynchronously after the page loads. Keep
  // that signal on the same validated, consent-aware path as ordinary CTA
  // events instead of exposing gtag as a global application API.
  document.addEventListener("codex-migrate:analytics-event", (event) => {
    sendEvent(event.detail);
  });

  async function initialize() {
    if (!PUBLIC_HOSTS.has(window.location.hostname)) return;
    try {
      const response = await fetch("/api/analytics-region", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("region lookup failed");
      const policy = await response.json();
      analyticsMode = policy.mode === "default" ? "default" : "consent";
    } catch {
      analyticsMode = "consent";
    }

    const savedConsent = currentChoice || readConsent();
    const granted = savedConsent === GRANTED || (savedConsent !== DENIED && analyticsMode === "default");
    startGoogleTag(granted);
    if (analyticsMode === "consent" && savedConsent !== GRANTED && savedConsent !== DENIED) {
      showConsentNotice();
    }
  }

  // Keep Google Analytics out of the critical rendering path. Event handlers
  // are already active, so an unusually fast CTA click is queued above and
  // flushed after the page has painted and GA is ready.
  if (document.readyState === "complete") initialize();
  else window.addEventListener("load", initialize, { once: true });
})();
