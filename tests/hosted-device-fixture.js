const { randomBytes } = require('node:crypto');
const { tokenHash } = require('../hosted/access');

function mintSessionSecret() {
  const token = `hv1_${randomBytes(32).toString('base64url')}`;
  return Object.freeze({ token, tokenHash: tokenHash(token) });
}

module.exports = { mintSessionSecret };
