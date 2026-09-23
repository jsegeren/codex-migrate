const { configuration, CommerceError, SITE, validRelease } = require('../commerce/config');
const { releaseVersion } = require('../commerce/service');

function makeHandler(configure = configuration, env = process.env) {
  return (req, res) => {
    if (req.method !== 'GET') {
      res.setHeader('Allow', 'GET'); res.statusCode = 405; return res.end();
    }
    try {
      const { release, live } = configure(env);
      if (!live) throw new CommerceError('release_unavailable');
      const version = releaseVersion(release);
      // An unsigned archive must never be advertised as an installable update.
      if (!validRelease(release, true) || !version || !release.sparkleSignature || version.architecture !== 'arm64') {
        throw new CommerceError('release_unavailable');
      }
      const build = version.numbers[3];
      const shortVersion = version.numbers.slice(0, 3).join('.');
      const xml = `<?xml version="1.0" encoding="UTF-8"?>\n` +
        `<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">\n` +
        `<channel><title>Codex Migrate updates</title><link>${SITE}</link>` +
        `<description>Signed Mac app updates</description><item>` +
        `<title>Codex Migrate ${shortVersion} (build ${build})</title>` +
        `<sparkle:version>${build}</sparkle:version>` +
        `<sparkle:shortVersionString>${shortVersion}</sparkle:shortVersionString>` +
        `<sparkle:minimumSystemVersion>13.0.0</sparkle:minimumSystemVersion>` +
        `<sparkle:hardwareRequirements>arm64</sparkle:hardwareRequirements>` +
        `<enclosure url="${SITE}/api/update-archive" sparkle:edSignature="${release.sparkleSignature}" ` +
        `length="${release.size}" type="application/zip"/></item></channel></rss>\n`;
      res.statusCode = 200;
      res.setHeader('Content-Type', 'application/rss+xml; charset=utf-8');
      res.setHeader('Cache-Control', 'no-store');
      res.setHeader('X-Content-Type-Options', 'nosniff');
      res.end(xml);
    } catch {
      res.statusCode = 503;
      res.setHeader('Cache-Control', 'no-store');
      res.end();
    }
  };
}
module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
