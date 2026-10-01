// A reserved upload can lose the race to another verified snapshot. This is
// the only database exception we expose as an actionable publication result.
class HostedPublicationStaleError extends Error {
  constructor() { super('hosted_publication_stale'); }
}

function isStalePublication(error) {
  return error?.code === 'HV001' &&
    error?.message === 'hosted_publication_base_changed';
}

module.exports = { HostedPublicationStaleError, isStalePublication };
