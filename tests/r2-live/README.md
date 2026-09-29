# R2 sandbox proof

This is a synthetic-data integration check for the hosted Vault storage adapter.
It is not a customer backup, a deployed Worker, or a release approval. The
configuration binds only the private `codex-vault-sandbox-20260927` bucket.

Run a local simulation first:

```sh
npx --yes wrangler@4.141.0 dev --config tests/r2-live/wrangler.jsonc --local --ip 127.0.0.1 --port 8789 --var PROBE_ENABLED:1
curl --fail --silent --show-error --request POST http://127.0.0.1:8789/probe
curl --fail --silent --show-error --request POST http://127.0.0.1:8789/probe-transport
PYTHONPATH=src python3 tests/r2-live/native_transport.py http://127.0.0.1:8789
PYTHONPATH=src python3 tests/r2-live/encrypted_roundtrip.py http://127.0.0.1:8789
```

All nine `/probe` flags and all eight `/probe-transport` flags must be `true`.
The transport probe uses the real capability-protected object Worker handler,
including its streaming upload path, with a random synthetic object and an
ephemeral in-memory signing key. It is still only a transport check: it does
not exercise purchase entitlement, a complete encrypted snapshot, publication,
or clean-Mac recovery. The probes require `PROBE_ENABLED:1` passed only to the
local dev command; the config does not enable it. The original probe writes
two randomly named synthetic keys, checks SHA-256 validation and immutable
reuse, reads the bytes back, proves that a wrong-digest DELETE is blocked,
deletes the exact object, and verifies an already-absent retry. A successful
probe leaves the bucket empty. Both probe routes accept only a loopback
hostname and must never be deployed or exposed through a tunnel.

The native transport proof uses `CapabilityHttpStore` in a separate Python
process. A loopback-only fixture issues ephemeral grants scoped to this sandbox
account and Vault, then the Python client uploads, reuses, downloads, and
deletes one random object through the production Worker handler. The grant
endpoint is test-only and must never be deployed. This detects differences
between Python's HTTP requests and the Worker runtime; it does not prove a
customer enrollment, a full Vault snapshot, or publication. Its cleanup must
succeed before treating the probe as passed.

The encrypted-roundtrip probe compiles the test CryptoKit helper, creates a
disposable synthetic transcript and paginated-history database, and sends a
complete encrypted snapshot through the same capability-protected loopback
Worker. It removes its test Keychain key, imports the one-time recovery key,
downloads and verifies the exact encrypted objects, and restores both sources
into a separate empty test home. It verifies that its own scoped remote objects
are absent after cleanup. The fixture grants only metadata, chunk, manifest,
and reference objects in its fixed synthetic account/Vault. This joins the
client and Worker paths, but the fixture issues its own ephemeral grants: no
authenticated hosted service, real R2, subscription, independent publication,
scheduled wake, or separate macOS-account recovery is proved.

To test against **real R2**, use `wrangler dev` without `--local` and with the
same explicit `--var PROBE_ENABLED:1`; the config's
`remote: true` binding then connects to the sandbox bucket while the Worker
still runs locally. This requires a separate, authorized Cloudflare Wrangler
credential. Do not use a production bucket, expose the local server, commit a
credential, or run against actual Codex data. Verify the sandbox bucket is
empty afterward in Cloudflare. Run both probe routes and both native scripts;
a local simulation alone is not a live-R2 receipt.
