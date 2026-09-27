# R2 sandbox proof

This is a synthetic-data integration check for the hosted Vault storage adapter.
It is not a customer backup, a deployed Worker, or a release approval. The
configuration binds only the private `codex-vault-sandbox-20260927` bucket.

Run a local simulation first:

```sh
npx --yes wrangler@4.141.0 dev --config tests/r2-live/wrangler.jsonc --local --ip 127.0.0.1 --port 8789 --var PROBE_ENABLED:1
curl --fail --silent --show-error --request POST http://127.0.0.1:8789/probe
```

All six JSON flags must be `true`. The probe requires `PROBE_ENABLED:1` passed
only to the local dev command; the config does not enable it. The probe writes two randomly named,
synthetic keys, checks SHA-256 validation and immutable reuse, reads the bytes
back, and deletes only those exact keys. A successful probe leaves the bucket
empty. The `/probe` route accepts only a loopback hostname and must never be
deployed or exposed through a tunnel.

To test against **real R2**, use `wrangler dev` without `--local` and with the
same explicit `--var PROBE_ENABLED:1`; the config's
`remote: true` binding then connects to the sandbox bucket while the Worker
still runs locally. This requires a separate, authorized Cloudflare Wrangler
credential. Do not use a production bucket, expose the local server, commit a
credential, or run against actual Codex data. Verify the sandbox bucket is
empty afterward in Cloudflare. A local simulation alone is not a live-R2
receipt.
