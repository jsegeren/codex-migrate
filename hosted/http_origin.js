// Browser requests may come from the public backup site or the older Mac-app
// origin. Native clients omit Origin and authenticate with a device bearer.
const BROWSER_ORIGINS = new Set([
  'https://codexbackup.segeren.com',
  'https://migrate.segeren.com',
]);

function allowedBrowserOrigin(origin) {
  return origin === undefined || BROWSER_ORIGINS.has(origin);
}

module.exports = { allowedBrowserOrigin };
