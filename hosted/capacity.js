// Plan the physical bytes a verified snapshot would add to one account.
// This is not quota enforcement by itself. The caller must lock the account's
// usage row, load its current object inventory, and commit the new inventory,
// usage, and last-good reference in one database transaction. An upload grant
// also needs a reservation/limit: a rejected publish must not permit unlimited
// orphan objects to accumulate in storage.

class HostedCapacityError extends Error {
  constructor() { super('hosted_capacity_invalid'); }
}

function validBytes(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function validObject(item) {
  return item && typeof item === 'object' && !Array.isArray(item) &&
    typeof item.key === 'string' && item.key.length > 0 &&
    Number.isSafeInteger(item.bytes) && item.bytes > 0 &&
    typeof item.sha256 === 'string' && /^[0-9a-f]{64}$/.test(item.sha256);
}

function planRetainedAddition(currentBytes, allowanceBytes, verifiedObjects, existingByKey) {
  if (!validBytes(currentBytes) || !validBytes(allowanceBytes) ||
      currentBytes > allowanceBytes || !Array.isArray(verifiedObjects) ||
      !(existingByKey instanceof Map)) throw new HostedCapacityError();

  let addedBytes = 0;
  const newObjects = [];
  const seen = new Set();
  for (const item of verifiedObjects) {
    if (!validObject(item) || seen.has(item.key)) throw new HostedCapacityError();
    seen.add(item.key);
    const prior = existingByKey.get(item.key);
    if (prior !== undefined) {
      if (!validObject(prior) || prior.key !== item.key ||
          prior.bytes !== item.bytes || prior.sha256 !== item.sha256) {
        throw new HostedCapacityError();
      }
      continue;
    }
    addedBytes += item.bytes;
    if (!Number.isSafeInteger(addedBytes) ||
        currentBytes + addedBytes > allowanceBytes) throw new HostedCapacityError();
    newObjects.push(Object.freeze({ key: item.key, bytes: item.bytes,
      sha256: item.sha256 }));
  }
  return Object.freeze({ addedBytes, retainedBytes: currentBytes + addedBytes,
    newObjects: Object.freeze(newObjects) });
}

module.exports = { HostedCapacityError, planRetainedAddition };
