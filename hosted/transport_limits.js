// Shared bounds for the first hosted transport: a Worker with an R2 binding.
const MAX_WORKER_OBJECT_BYTES = 100 * 1000 * 1000;
const VERIFICATION_BATCH_SIZE = 512;

module.exports = { MAX_WORKER_OBJECT_BYTES, VERIFICATION_BATCH_SIZE };
