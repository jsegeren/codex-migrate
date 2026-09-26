const { Readable } = require('node:stream');
const { pipeline } = require('node:stream/promises');
const { runtime } = require('../commerce/runtime');
const { CommerceError, configuration, commerceSite, validRelease, releaseContentType } = require('../commerce/config');
const { tokenSession } = require('../commerce/service');

async function fields(req, origin) {
  if (req.headers.origin !== origin) throw new CommerceError('invalid_origin', 403);
  if ((req.headers['content-type'] || '').split(';')[0] !== 'application/x-www-form-urlencoded') {
    throw new CommerceError('invalid_request', 415);
  }
  if (Number(req.headers['content-length']) > 512) throw new CommerceError('invalid_request', 413);
  let data = req.body;
  if (data === undefined) {
    const chunks = [];
    let size = 0;
    for await (const chunk of req) {
      size += chunk.length;
      if (size > 512) throw new CommerceError('invalid_request', 413);
      chunks.push(chunk);
    }
    data = Buffer.concat(chunks);
  }
  if (Buffer.isBuffer(data)) data = data.toString('utf8');
  if (typeof data === 'string') {
    if (Buffer.byteLength(data) > 512) throw new CommerceError('invalid_request', 413);
    const params = new URLSearchParams(data);
    if ([...params.keys()].length !== 2 || params.getAll('credential').length !== 1 ||
        params.getAll('version').length !== 1) throw new CommerceError('invalid_request', 400);
    data = Object.fromEntries(params);
  }
  if (!data || typeof data !== 'object' || Array.isArray(data) ||
      Object.keys(data).length !== 2 || typeof data.credential !== 'string' ||
      !['latest', 'original'].includes(data.version) ||
      JSON.stringify(data).length > 512) throw new CommerceError('invalid_request', 400);
  return data;
}

function makeHandler(load = runtime, request = fetch, env = process.env, configure = configuration) {
  return async (req, res) => {
    if (req.method !== 'POST') {
      res.setHeader('Allow', 'POST'); res.statusCode = 405; return res.end();
    }
    res.setHeader('Cache-Control', 'private, no-store');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('X-Robots-Tag', 'noindex');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    try {
      if ((req.url || '').includes('?')) throw new CommerceError('invalid_request', 400);
      const data = await fields(req, commerceSite(env));
      const config = configure(env);
      tokenSession(data.credential, config);
      const { service } = await load(env);
      const archive = data.version === 'latest'
        ? await service.downloadLatest(data.credential) : await service.download(data.credential);
      const release = config.catalog?.[archive.release];
      if (!validRelease(release, config.live) || archive.sha256 !== release.sha256 ||
          archive.size !== release.size || archive.filename !== release.filename) {
        throw new CommerceError('release_unavailable');
      }
      const url = new URL(archive.url);
      if (url.origin !== `https://${config.blobStore.toLowerCase()}.private.blob.vercel-storage.com` ||
          url.pathname !== `/${release.pathname}` || url.hash || !url.search) {
        throw new CommerceError('release_unavailable');
      }
      const upstream = await request(url, { redirect: 'error', signal: AbortSignal.timeout(60000) });
      if (upstream.status !== 200 || !upstream.body ||
          (upstream.headers.get('content-length') && Number(upstream.headers.get('content-length')) !== release.size)) {
        throw new CommerceError('release_unavailable');
      }
      res.statusCode = 200;
      res.setHeader('Content-Type', releaseContentType(release));
      res.setHeader('Content-Length', String(release.size));
      res.setHeader('Content-Disposition', `attachment; filename="${release.filename}"`);
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
