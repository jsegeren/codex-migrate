# Hosted Vault unit economics — 2026-09-26

Internal working evidence, not a published price or storage entitlement. The
existing $49 app and its checkout are unchanged; hosted backup is not live.

## What is measured

`ops/vault-size-estimate.py` reads only the active and archived transcript trees,
using the same 4 MiB chunk boundaries and LZFSE compression decision as Vault.
It reports aggregate numbers without paths, titles, content, or digests and
does not create a backup. On the older Mac, excluding files modified in the
last 60 seconds:

| Measure | Result |
| --- | ---: |
| Stable transcripts | 2,052 |
| Stable raw transcript bytes | 54,889,827,804 |
| Estimated first-backup encrypted object bytes | 28,875,910,073 |
| Unique 4 MiB-or-smaller objects | 14,449 |
| Recently changing transcripts excluded | 1 (2,132,843,850 raw bytes) |

The same storage-only estimator ran at low CPU priority on the newer Mac,
without creating a backup or changing its Codex files:

| Measure | Newer Mac | Both Macs combined |
| --- | ---: | ---: |
| Stable transcripts | 2,255 | 4,307 |
| Stable raw transcript bytes | 85,681,714,716 | 140,571,542,520 |
| Estimated first-backup encrypted object bytes | 43,313,575,043 | 72,189,485,116 |
| Unique 4 MiB-or-smaller objects | 21,907 | 36,356 |
| Recently changing transcripts excluded | 4 (1,984,877,091 raw bytes) | 5 (4,118,220,941 raw bytes) |

The exact first-backup object total is not proven because five changing
transcripts were omitted and manifests/references are excluded. Even if none
of those five files compressed, the combined object bytes would be at most
about 76.31 GB (plus small encryption/metadata overhead). Stable encrypted
object bytes are 51.4% of stable raw bytes. The two Macs use distinct Vaults:
do not assume cross-Vault deduplication or silently merge their histories.
The sizing tool's new `--storage-only` mode produced the same 28,875,910,073
object bytes as its original full mode on the older Mac, while avoiding the
unneeded text-extraction work. Never extrapolate this user's compression ratio
into a customer quota.

File modification times give an *upper bound on current file sizes touched*,
not bytes appended or new encrypted objects. On the older Mac, the files
modified within one, seven, and thirty days currently total 2.63, 9.10, and
21.51 GB raw respectively. On the newer Mac, those values are 16.35, 31.11,
and 55.63 GB raw. The real daily upload rate requires consecutive snapshots
or an equivalent chunk-inventory comparison; it is not established by mtime.

## Operation pattern

Each novel encrypted chunk is one PUT; a complete independent read-back or
restore is approximately one GET per chunk. Immutable manifests, per-snapshot
metadata, and references add a small number of operations. The older Mac's
14,449 first-backup chunks imply roughly 14,449 writes and the same number of
verification reads. Both Macs together imply about 36,356 of each. At
published R2 Standard rates **before the account-wide free allowance**, those
combined operations cost about $0.164 for writes and $0.013 for reads.
Repeating an unchanged backup should reuse existing chunks; a
rewritten or compacted transcript can create new chunks and must be measured.
Do not count shared free allowances as a per-customer subsidy.

## Published provider rates and a restore month

Rates below are US-dollar public on-demand examples, not a provider invoice.
Actual region, account plan, cache behavior, and ancillary service fees need
verification in a sandbox.

| Provider | Storage | Direct client upload | Direct first-time full restore |
| --- | ---: | ---: | ---: |
| Cloudflare R2 Standard | $0.015/GB-month | No per-GB ingress fee; Class A writes | No direct egress fee; Class B reads |
| Vercel Blob | $0.023/GB-month | No transfer charge; advanced operations | About $0.11/GB when each chunk is a cache miss: $0.05 Blob Data Transfer + $0.06 Fast Origin Transfer, plus simple/edge operations |

At the measured combined first-backup range of **72.19–76.31 GB** (not yet
30-day retention), R2 Standard storage is about **$1.08–$1.14/month** and a
direct full restore has no R2 byte-transfer charge. Vercel Blob storage is
about **$1.66–$1.76/month**, with an approximately **$7.94–$8.39** first
full-restore transfer charge if every object misses the cache. The R2
initial PUT plus one complete verification GET pass is about **$0.18** in
operations before its account-wide free allowance. These are measured-size
pricing calculations, not observed provider invoices or a retention forecast.

Vercel's private signed URLs permit direct PUT/GET without app-server byte
relay. Sending backup bytes *through* a Vercel Function adds transfer and
compute charges and is excluded from the direct-transfer model. The backup
objects are small enough for CDN caching, but the first complete disaster
restore should be budgeted as cache misses. Both providers bill operations;
"Backup and download" still generate requests, though byte storage and
Vercel restore transfer dominate at observed object counts.

Sources: [R2 pricing](https://developers.cloudflare.com/r2/pricing/),
[Vercel Blob pricing](https://vercel.com/docs/vercel-blob/usage-and-pricing/),
[Vercel signed URLs](https://vercel.com/docs/vercel-blob/vercel-signed-urls).

## Subscription contribution before support

For an illustrative $10 US domestic-card subscription, published Stripe
Payments (2.9% + $0.30) and pay-as-you-go Billing (0.7%) total approximately
$0.66, leaving $9.34 before storage, API/DB, observability, support, refunds,
taxes, and retained-version growth. A $20 charge similarly leaves about
$18.98. These are not promises about this account's contracted Stripe rates.
The $49 one-time app purchase funds the first included hosted month only if
the customer opts in; a later subscription must work on its own economics.

`cost + 50%` is not a fat-margin plan: a 50% markup on cost creates only a
33.3% margin *before* Stripe and all non-storage costs. It also turns normal
backup/restore variation into unpredictable customer bills. Prefer simple,
visible capacity tiers based on **total encrypted retained bytes across a
customer's Vaults**, with warning and safe upload pause near the allowance;
never silently charge overages or delete the last good snapshot. Candidate
tiers for evaluation are $10/month up to 100 GB and $20/month up to 200 GB on
R2. At their limits, R2 storage plus the illustrative Stripe fees leave
approximately 78% and 80% of revenue respectively before other costs. The
measured 72–76 GB first backup of this user's two separate Macs would fit the
lower tier initially; retained version growth could later require the higher
tier. This is a capacity choice, not metered or automatic overage billing.
These are **not approved or active** entitlements. Recheck them after real
incremental growth, verification costs, support, and restore testing.

## Still to prove

- Measure 24-hour and seven-day *unique encrypted object growth* with retained
  versions. Existing mtime observations cannot do this.
- Prove an actual provider's immutable PUT, exact-byte integrity verification,
  quota enforcement, signed direct restore, and clean-Mac recovery. Neither an
  ETag nor a client receipt alone proves the server has the intended bytes.
- Set an explicit retention policy and capacity behavior, and record provider
  spend and per-account retained bytes before offering a paid tier.
