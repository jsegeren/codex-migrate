// Return only the analytics policy mode needed by the browser. Vercel supplies
// the country header; no IP address or country value is retained or returned.
const CONSENT_REQUIRED = new Set([
  'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR',
  'HU', 'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK',
  'SI', 'ES', 'SE', 'IS', 'LI', 'NO', 'GB', 'CH',
]);

function handler(req, res) {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.setHeader('Allow', 'GET, HEAD');
    res.statusCode = 405;
    return res.end();
  }

  const rawCountry = req.headers['x-vercel-ip-country'];
  const country = typeof rawCountry === 'string' ? rawCountry.trim().toUpperCase() : '';
  // An unknown edge location fails closed into consent-required mode.
  const mode = country && !CONSENT_REQUIRED.has(country) ? 'default' : 'consent';
  res.statusCode = 200;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'private, no-store');
  res.setHeader('Vary', 'X-Vercel-IP-Country');
  if (req.method === 'HEAD') return res.end();
  return res.end(JSON.stringify({ mode }));
}

module.exports = handler;
