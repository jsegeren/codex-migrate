const { CommerceError, SITE } = require('./config');
function reply(res, status, value) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.setHeader('X-Robots-Tag', 'noindex');
  res.end(JSON.stringify(value));
}
function failure(res, error) {
  // Provider errors can carry emails, keys, payloads and download tokens.
  return reply(res, error instanceof CommerceError ? error.status : 503,
    { error: error instanceof CommerceError ? error.code : 'temporarily_unavailable' });
}
function body(req, origin = SITE) {
  if (req.headers.origin !== origin) throw new CommerceError('invalid_origin', 403);
  if ((req.headers['content-type'] || '').split(';')[0] !== 'application/json') throw new CommerceError('invalid_request', 415);
  if (Number(req.headers['content-length']) > 2048) throw new CommerceError('invalid_request', 413);
  const data = req.body;
  if (!data || typeof data !== 'object' || Array.isArray(data) || JSON.stringify(data).length > 2048) {
    throw new CommerceError('invalid_request', 400);
  }
  return data;
}
module.exports = { reply, failure, body };
