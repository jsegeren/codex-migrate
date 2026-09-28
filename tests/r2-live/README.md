# R2 sandbox proof

This is a synthetic-data integration check for the hosted Vault storage adapter.
It is not a customer backup, a deployed Worker, or a release approval. The
configuration binds only the private `codex-vault-sandbox-20260927` bucket.

Run a local simulation first:

```sh
npx --yes wrangler@4.141.0 dev --config tests/r2-live/wrangler.jsonc --local --ip 127.0.0.1 --port 8789 --var PROBE_ENABLED:1
curl --fail --silent --show-error --request POST http://127.0.0.1:8789/probe
curl --fail --silent --show-error --request POST http://127.0.0.1:8789/probe-transport
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

To test against **real R2**, use `wrangler dev` without `--local` and with the
same explicit `--var PROBE_ENABLED:1`; the config's
`remote: true` binding then connects to the sandbox bucket while the Worker
still runs locally. This requires a separate, authorized Cloudflare Wrangler
credential. Do not use a production bucket, expose the local server, commit a
credential, or run against actual Codex data. Verify the sandbox bucket is
empty afterward in Cloudflare. Run both probe routes; a local simulation alone
is not a live-R2 receipt.
