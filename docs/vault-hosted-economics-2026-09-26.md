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

Each novel encrypted chunk is one PUT. The proposed R2 Worker adapter uses
HEAD before each upload and HEAD after a successful conditional PUT, rather
than a full read-back: the older Mac's 14,449 chunks imply roughly 14,449
writes and 28,898 metadata reads; both Macs together imply about 36,356
writes and 72,712 metadata reads. At published R2 Standard rates **before the
account-wide free allowance and billable-unit rounding**, the metered amounts
are about $0.164 for writes and $0.026 for HEADs. A full restore adds about
36,356 GETs, or $0.013 in metered R2 read operations, with no direct egress
fee. Cloudflare applies monthly account-wide free allowances and rounds
billable operations up to the next million; these fractional amounts are
cost-allocation estimates, not invoice predictions. Immutable manifests,
per-snapshot metadata, and references add a small number of operations.
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
initial PUT plus two metadata HEAD passes is about **$0.19** in
operations before its account-wide free allowance. These are measured-size
pricing calculations, not observed provider invoices or a retention forecast.

Vercel's private signed URLs permit direct PUT/GET without app-server byte
relay. Sending backup bytes *through* a Vercel Function adds transfer and
compute charges and is excluded from the direct-transfer model. The backup
objects are small enough for CDN caching, but the first complete disaster
restore should be budgeted as cache misses. Both providers bill operations;
"Backup and download" still generate requests, though byte storage and
Vercel restore transfer dominate at observed object counts.

R2's S3 presigned PUT URL is reusable until expiry and does not by itself
provide the SHA-256 and immutable-write proof this product requires. The
leading R2 path is a small authenticated Cloudflare Worker using the R2
binding's `put(..., { sha256, onlyIf })`, followed by a metadata check. This
must be proved against a real R2 sandbox; an ETag or a mocked binding is not
enough. The Worker can stream encrypted objects directly to R2 without
relaying them through Vercel. Its inbound 100 MB limit on a Free Cloudflare
account accommodates ordinary encrypted chunks, but an oversized manifest
must fail safely or use a separately proven path.

Workers Free allows 100,000 requests/day. One initial upload of this user's
two Vaults entails about 36,356 object requests. A naive daily retry of every
unchanged object through the upload route would create about 1.09 million
Worker requests/month for this one customer; do not ship that behavior. The
draft bounded proof instead needs about 29 + 43 = **72 Worker batch requests**
to check both unchanged Vaults, while still making roughly 36,356 R2 HEAD
subrequests per daily proof. Over 30 daily proofs that is about 2,160 Worker
requests and 1.09 million R2 Class B HEADs (about $0.39 at the unrounded
metered rate, before the account-wide allowance). New or changed chunks still
need individual upload requests. A few initial uploads on one day can exceed
the Free daily request ceiling; do not build the offer around it. The batch
network endpoint and actual provider behavior remain unproved. Workers Paid has a **$5/month account
minimum**, including 10 million monthly requests and 30 million CPU-ms, then
$0.30/million requests and $0.02/million CPU-ms. This $5 is shared fixed
overhead, not a per-customer charge. R2 read/write operations are separate.
At one $10 subscriber using the full 100 GB allowance, the earlier 78% figure
falls to about **28% contribution before support, database/API, retries, and
taxes** if the whole $5 Worker minimum is assigned to that customer. At ten
such subscribers, the same fixed overhead is about $0.50 each and the
corresponding contribution is roughly 73% before those omitted costs. These
figures are illustrative, not observed invoices or final plan margins.

Sources: [R2 pricing](https://developers.cloudflare.com/r2/pricing/),
[Vercel Blob pricing](https://vercel.com/docs/vercel-blob/usage-and-pricing/),
[Vercel signed URLs](https://vercel.com/docs/vercel-blob/vercel-signed-urls),
[R2 Workers API](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/),
[Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/),
[Workers limits](https://developers.cloudflare.com/workers/platform/limits/).

## Subscription contribution before support

For an illustrative $10 US domestic-card subscription, published Stripe
Payments (2.9% + $0.30) and pay-as-you-go Billing (0.7%) total approximately
$0.66, leaving $9.34 before storage, API/DB, observability, support, refunds,
taxes, and retained-version growth. A $20 charge similarly leaves about
$18.98. These are not promises about this account's contracted Stripe rates.
The $49 one-time app purchase funds the first included hosted month only if
the customer opts in; a later subscription must work on its own economics.

`cost + 50%` is not a fat-margin plan: a 50% markup on cost creates only a
33.3% margin *before* Stripe and all non-storage costs. A single unlimited
price also makes light histories subsidize very large ones. The current
**unapproved proposal** is $10/month including 50 GB, then $0.08 per
additional GB-month of actual retained encrypted bytes across all of a
customer's Vaults. At 72 GB this is about $11.76/month; 200 GB is $22;
500 GB is $46; 1 TB is $86. These are illustrative charges, not published
prices, and do not include taxes or the first included hosted month. R2
Standard storage is $0.015/GB-month before operations; the $0.08 incremental
rate leaves 81.25% gross *storage-only* margin before payment fees, Worker,
database, support, and other costs. The $10 base covers those fixed service
costs only as subscriber count grows; one subscriber alone does not prove
healthy unit economics.

The proposed billing unit is retained **encrypted object bytes**, not raw
Codex-folder size, upload volume, thread count, snapshot count, or number of
Macs. A reused object is counted once within its Vault; separate Vaults are
counted together at the account level, with no unproved cross-Vault dedupe.
Use average daily retained bytes for the monthly GB-month charge, matching
R2's published daily-peak averaging convention. Show the current retained
size, estimated second-month bill, and the customer's chosen hard spending
ceiling before the first upload. Translate that ceiling conservatively to a
maximum instantaneous byte allowance: when full, new uploads pause while the
last verified snapshot remains intact and the UI clearly marks protection
stale. Self-managed backups remain available without hosting fees.

The promised first hosted month included with a $49 app purchase needs a
published maximum capacity. **1 TB is a candidate ceiling, not an approved
entitlement**: at R2 Standard's published rate, a full month of 1 TB storage
costs about $15 before requests, Worker, database, and support. Larger Vaults
would need a separate explicit quote rather than an unlimited free trial.
Cancellation, proration, taxes, retention, and the exact first-month limit
must be approved before any customer-facing checkout or invoice changes.

The current SQL prototype enforces a byte allowance, **not metered billing**.
No subscription, rate, or allowance is approved or live. Before charging,
prove the daily-average meter and cap mapping against real provider storage,
measure incremental growth, and recheck verification, support, and restore
costs.

## Still to prove

- Measure 24-hour and seven-day *unique encrypted object growth* with retained
  versions. Existing mtime observations cannot do this.
- Prove an actual provider's immutable PUT, exact-byte integrity verification,
  quota enforcement, signed direct restore, and clean-Mac recovery. Neither an
  ETag nor a client receipt alone proves the server has the intended bytes.
- Set an explicit retention policy and capacity behavior, and record provider
  spend and per-account retained bytes before offering a paid tier.
