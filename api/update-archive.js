const { Readable } = require('node:stream');
const { pipeline } = require('node:stream/promises');
const { runtime } = require('../commerce/runtime');
const { CommerceError, configuration, releaseContentType, validRelease } = require('../commerce/config');
const { tokenSession } = require('../commerce/service');

function makeHandler(load = runtime, request = fetch, env = process.env, configure = configuration) {
  return async (req, res) => {
    if (req.method !== 'GET') {
      res.setHeader('Allow', 'GET'); res.statusCode = 405; return res.end();
    }
    res.setHeader('Cache-Control', 'private, no-store');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    try {
      const match = /^Bearer (cs_(?:live|test)_[A-Za-z0-9]+\.[a-f0-9]{64})$/.exec(req.headers.authorization || '');
      if (!match || (req.url || '').includes('?')) throw new CommerceError('invalid_link', 403);
      const configured = configure(env);
      const sessionId = tokenSession(match[1], configured);
      const canary = req.headers['x-codex-migrate-canary'];
      if (canary !== undefined && (!configured.live || typeof canary !== 'string' ||
          canary !== env.COMMERCE_UPDATER_CANARY_RELEASE ||
          sessionId !== env.COMMERCE_UPDATER_CANARY_SESSION ||
          !/^[a-f0-9]{64}$/.test(env.COMMERCE_UPDATER_CANARY_SHA256 || ''))) {
        throw new CommerceError('invalid_link', 403);
      }
      const { config, service } = await load(env);
      if (canary !== undefined && (config.mode !== configured.mode || config.secret !== configured.secret ||
          config.release.id !== configured.release.id || config.blobStore !== configured.blobStore)) {
        throw new CommerceError('release_unavailable');
      }
      const selected = canary === undefined ? config.release : config.catalog?.[canary];
      if (canary !== undefined && (!validRelease(selected, false) ||
          selected.sha256 !== env.COMMERCE_UPDATER_CANARY_SHA256 ||
          selected.kind !== 'signed-notarized' || selected.testingOnly !== true ||
          selected.accepted !== false || !selected.sparkleSignature)) {
        throw new CommerceError('release_unavailable');
      }
      const update = canary === undefined
        ? await service.downloadLatest(match[1])
        : await service.downloadCanary(match[1], canary);
      // The purchase release may already be the current one while the buyer's
      // installed app is older (for example after restoring an old Mac backup).
      if (update.release !== selected.id ||
          update.sha256 !== selected.sha256 || update.size !== selected.size ||
          !selected.sparkleSignature) throw new CommerceError('release_unavailable');
      const url = new URL(update.url);
      if (url.origin !== `https://${config.blobStore.toLowerCase()}.private.blob.vercel-storage.com` ||
          url.pathname !== `/${selected.pathname}` || url.hash || !url.search) {
        throw new CommerceError('release_unavailable');
      }
      const upstream = await request(url, { redirect: 'error', signal: AbortSignal.timeout(60000) });
      if (upstream.status !== 200 || !upstream.body ||
          (upstream.headers.get('content-length') && Number(upstream.headers.get('content-length')) !== update.size)) {
        throw new CommerceError('release_unavailable');
      }
      res.statusCode = 200;
      res.setHeader('Content-Type', releaseContentType(selected));
      res.setHeader('Content-Length', String(update.size));
      res.setHeader('Content-Disposition', `attachment; filename="${update.filename}"`);
      await pipeline(Readable.fromWeb(upstream.body), res);
    } catch (error) {
      if (res.headersSent) { res.destroy(); return; }
      res.statusCode = error instanceof CommerceError ? error.status : 503;
      res.end();
    }
  };
}
module.exports = makeHandler();
module.exports.makeHandler = makeHandler;
