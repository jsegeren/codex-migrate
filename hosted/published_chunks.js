// Return only exact chunk objects in an already published snapshot of this
// authorized Vault. Staged or other-account objects must never be candidates
// for a remote-aware writer's immutable ciphertext reuse.
const { consumeAuthorizedScope } = require('./access');

const HEX = /^[0-9a-f]{64}$/;
const LOOKUP_SQL = `SELECT id, bytes, sha256 FROM
  hosted.published_chunk_candidates($1::uuid, $2::uuid, $3::text[])`;

class PublishedChunkLookupError extends Error {
  constructor() { super('hosted_chunk_lookup_denied'); }
}

async function lookupPublishedChunks({ scope, ids, query }) {
  if (!consumeAuthorizedScope(scope) || !Array.isArray(ids) ||
      ids.length < 1 || ids.length > 256 ||
      !ids.every(id => typeof id === 'string' && HEX.test(id)) ||
      new Set(ids).size !== ids.length || typeof query !== 'function') {
    throw new PublishedChunkLookupError();
  }
  try {
    const result = await query(LOOKUP_SQL, [scope.accountId, scope.vaultId, ids]);
    const rows = result?.rows;
    if (!Array.isArray(rows) || rows.length > ids.length) {
      throw new PublishedChunkLookupError();
    }
    const candidates = new Set(ids);
    let prior = '';
    const objects = rows.map(row => {
      const bytes = Number(row.bytes);
      if (typeof row.id !== 'string' || !candidates.has(row.id) ||
          row.id <= prior || !Number.isSafeInteger(bytes) || bytes < 1 ||
          bytes > 100_000_000 || typeof row.sha256 !== 'string' ||
          !HEX.test(row.sha256)) throw new PublishedChunkLookupError();
      prior = row.id;
      return Object.freeze({ id: row.id, bytes, sha256: row.sha256 });
    });
    return Object.freeze(objects);
  } catch { throw new PublishedChunkLookupError(); }
}

module.exports = { PublishedChunkLookupError, lookupPublishedChunks,
  LOOKUP_SQL };
