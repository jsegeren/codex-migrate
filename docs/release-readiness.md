# Desktop release readiness

The downloadable paid app is **not released**. Publishing source and the
informational website does not open checkout or certify a customer download.

See the [September 4 audit](release-audit-2026-09-04.md) for current automated
results, accessibility findings, and pre-signing work still open.

## Candidate checks completed on the development Mac

- Guided recovery is implemented in source: the collapsed browser panel now
  requires a checked backup, enabled changes, and explicit scope confirmation.
  Restoration keeps displaced destination files separately, then verifies both
  restored and preserved entries. A durable source checkpoint binds the exact
  transaction before any request; reconnect checks never automatically retry
  mutation or infer success from an absent pending record. Missing/malformed
  saved proof blocks ordinary migration actions. Restore completion is labelled
  as restoration of the previous destination, not a completed migration.
  The independent reviewer identified and verified fixes for misleading actual
  presence reports and unexpected preserved/prepared entries. Guided UI review
  also found a missing-proof bypass and stale progress/item displays; all were
  fixed and the reviewer accepted this bounded checkpoint. Independent review
  passed 67 focused tests and inspected actual fixture restoration at desktop
  and 320px, including confirmation, protected controls, focus, current item,
  hidden percentage, preserved-entry mapping, and the recovery-backup label.
  Main verification passed 355 Python tests (354 passed, one filesystem skip),
  10 signup tests, Swift typecheck and diff checks; 45 final focused tests also
  passed after the final display and packaged-regression assertions. Playwright
  verified confirmation dismissal, actual restore, keyboard focus, and 320px
  wrapping with no browser console errors. All data was disposable; no actual
  account data or real SSH migration was used. Review fixtures were cleaned up.
  See [the restoration contract](restore-engine.md). This is not Apple release
  certification, VoiceOver conformance, or real packaged cross-Mac acceptance.

- The preceding internal post-crash restoration checkpoint restored frozen destination
  backups while retaining displaced current entries in a separate, indexed
  recovery directory. It was not exposed by the CLI or browser at that checkpoint. Explicit
  apply authority and the inspected transaction ID/backup/scope are required.
  Immutable plan/ready/completion evidence and per-entry checks allow tested
  interrupted restores to resume. Destination identity is preserved, including
  a newer logout; unsupported missing prior Codex roots fail closed. No current
  entry is deleted. Atomic Darwin exclusive renames reject newly appearing
  destination entries; this also hardens shared recovery-record publication.
  Independent `public_release_review` reproduced and verified fixes for stale
  identity resurrection, process checks too far from mutation, evidence replay
  without a renewed flush, and a check-then-rename overwrite race. Disposable
  APFS fixtures exercise actual copies, moves, process interruption, preservation,
  corruption, Unicode/skill links, insufficient space, and resume. See the
  [internal engine contract](restore-engine.md). Final local checks: 325 Python
  tests (324 passed, one existing filesystem skip), including 22 restoration
  tests; 10 signup tests; Swift typecheck and diff checks passed. Independent
  review accepted the final code and engineering documentation. These are
  source-engine checks, not a packaged guided-restore proof. The new source slice
  above addresses guided confirmation, progress and reconnect handling; real
  cross-Mac/drive power-loss acceptance and Intel coverage remain gates. This is not a claim
  that the downloadable app can perform guided restoration yet.
  Clean source `ad49883` also built a local unsigned arm64 engineering app;
  all eight bundled-engine regression tests passed and packaging verified the
  ad-hoc signature. ZIP SHA-256:
  `eb908bff5026b443b53bcf2e4818eeb47ef5c1793180a3abb7b12f9f87f5dee4`.
  That older build did not include restore in the customer flow; those
  checks cover the existing bundled controls, not packaged guided restoration.
  No running app or actual workspace was changed. The prior inactive engineering
  build was moved to Trash, not permanently deleted.

- Read-only recovery inspection is now available through the collapsed browser
  recovery panel and `codex-migrate recovery`. It opens the existing destination
  lock read-only, reports a live writer as busy, validates bounded saved scope,
  checks frozen backups, and never clears a record or restores files. Reports
  distinguish absent/legacy evidence and historical terminal receipts from
  current usability; no digest or credential contents leave the remote helper.
  Browser checks preserve the migration state, support local Stop, recover from
  an interrupted check, and record only allowlisted status in diagnostic events.
  Independent `public_release_review` caught and accepted fixes for a late-child
  cancellation race, lost keyboard focus, and mobile path overflow. Rendered
  desktop/320px checks verified disclosures, Check → status → Check focus, and
  expanded long-path wrapping. Final focused checks and corrected copy passed;
  full suite: 303 tests (302 passed, one existing filesystem skip), 10 signup
  tests, and Swift typecheck. Real local subprocess tests cover cancellation
  before launch and during registration; no real SSH migration/user data was
  used. VoiceOver and clean second-Mac behavior remain open; the newer slice
  above adds guided restoration. Clean source `4c894c2` built
  an unsigned arm64 engineering app, passed eight bundled-engine checks, and
  rejected bundled `recovery --apply` before connecting. Packaging verified
  its ad-hoc signature. ZIP SHA-256:
  `7bda4456769a5a13df5e6fea0e3fb21f6123d9a326bd92767ec2a559945bc728`.
  This is a local-test build, not an Apple-signed/notarized release or a real
  packaged SSH migration proof.

- Frozen backup integrity now uses version-2 destination recovery records. Each
  existing backup and original must match before replacement; all backups are
  rechecked before normal rollback can remove current destination data, and
  restored files must match the frozen checksums. Existing absent items remain
  explicitly absent. Legacy or malformed records do not authorize recovery.
  The shared tree algorithm covers file bytes, names, permission bits, empty
  directories, and link text without displaying digests. This caught and fixed
  backup/rollback copies losing permission bits under the restrictive umask.
  Twenty-two local transaction tests pass, including corruption, missing/extra
  entries, permission and link changes, special files, legacy evidence, and
  preserving installed data when a backup is damaged. The final full suite ran
  285 tests (284 passed, one filesystem skip), including the 22-test transaction
  suite. Ten signup
  tests and Swift typecheck passed. Independent `public_release_review` caught
  a Unicode-home regression, then accepted its filesystem-byte/JSON-path fix
  after independent accented, Chinese, and decomposed-path fixtures and 91
  focused tests (90 passed, one skip). No real user data or SSH migration was
  used. Clean source `40fa834` built an unsigned arm64 engineering app and passed
  all eight bundled-engine checks; packaging verified its ad-hoc signature.
  ZIP SHA-256: `549027d5dc03a26f4721075bdb9366bf4a668e87ca4d86ce66f91426c84f2d8c`.
  The build is local-test-only, not Apple signed/notarized. Its startup/config
  checks do not exercise a real packaged SSH migration. CI was still running
  when this local checkpoint was recorded.
  Guided post-crash recovery that preserves displaced current data remains
  release-blocking; this change supplies its integrity prerequisite, not the UI
  or a clean second-Mac/power-loss proof.

- Durable destination recovery evidence now precedes replacement. Backup
  files/directories and the atomically published pending record are fsynced,
  followed by the macOS `F_FULLFSYNC` barrier. Full and skills installers record
  scope and original existence; pending/malformed records block new writes.
  Normal rollback now verifies original contents/absence and saves a synced
  terminal receipt before clearing the pending record. Startup/shutdown copy
  no longer claims rollback happened merely because the local process ended.
  Fourteen disposable local transaction tests cover SIGKILL after removal,
  failed rollback, durability and terminal-evidence failures, final cleanup,
  private/corrupt records, missing originals, prerequisite probes, and Codex
  reopening during the backup flush. Independent `public_release_review` caught
  and accepted the corrected zsh helper-failure/rollback-trap regression, then
  accepted final code and recovery wording. Full local suite: 277 Python tests
  (276 passed, one explicit skip), 10 signup tests, and native Swift typecheck.
  A final clear failure may leave a durable terminal receipt without a pending
  file; it is still reported as an error. This is tested containment and normal
  rollback, not guided post-crash recovery or actual hardware power-cut proof.
  The guided restore/reconciliation flow now has local fixture coverage above;
  real packaged cross-Mac acceptance remains release-blocking work.
  Clean source `7bdce3a` produced an unsigned arm64 app and passed eight bundled
  engine startup/configuration checks; packaging verified its ad-hoc signature.
  ZIP SHA-256: `09a8cad7624a5defd94e8c0aa201ad5fdab114eb8cc84305d0cd8a42fa29cf7c`.
  This does not certify an actual packaged SSH migration or clean second Mac.
  This earlier format-1 checkpoint recorded durable scope and outcome but no
  frozen backup integrity. Format 2 adds that evidence; the guided checkpoint
  above now preserves current destination data separately.

- Destination-wide exclusion now covers staging directory/marker writes, rsync
  receivers, and the entire full/skills backup-install-verify-rollback phase.
  An owner-only, no-follow persistent lock file is held by the destination
  kernel, inherited through child processes, and never unlinked or reclaimed
  by age/PID. Actual local process tests prove exclusion after parent death
  while a child lives, release after completion, rejection of unsafe lock paths,
  and full/skills/CLI staging boundaries. Real local rsync protocol tests prove
  a held lock blocks copying and release allows copying; a separate 256 KiB
  binary roundtrip checks command-mode stdin. Independent reviewer
  `public_release_review` accepted implementation and recovery wording with no
  blocking findings. Local suite: 263 Python tests (262 passed, one explicit
  skip), 10 signup tests, and native Swift typecheck. This is not a real
  cross-Mac disconnect test or power-loss recovery certification. Old versions
  and manual filesystem writes do not participate in this lock.
  Clean source `5fc092a` produced an unsigned arm64 app; all eight bundled-engine
  checks passed and packaging verified its ad-hoc signature. ZIP SHA-256:
  `20f59981f6e85cfc73c25ab9aa1245ef1114ef6c3aa8e2c2e176d7db6416dd59`.
  These startup/configuration tests do not exercise a real packaged SSH transfer
  or certify a clean second Mac.

- Same-source-Mac rejection now runs before every migration remote-shell body
  and rsync receiver. It compares ephemeral salted platform identities, rejects
  unknown identities, and retains strict SSH host-key verification. Stable
  hardware identifiers are not saved or emitted. Local real-shell and real
  Apple openrsync protocol fixtures verify both rejection and allowed copying
  with spaces/quotes in paths; a separate source-entry regression runs without
  inherited Python paths. Independent reviewer `public_release_review` caught
  and then accepted the corrected launcher issue. Local suite: 254 Python tests
  (253 passed, one explicit skip). No real cross-Mac transfer was performed;
  classic rsync argument conventions are unit-tested, not a separately installed
  client. This does not identify an unintended *other* trusted Mac, certify
  virtual machines, or cover the unused benchmark helper. Destination-wide
  locking and power-loss reconciliation remain open in the failure-mode matrix.
  Clean source `45829eb` also built an unsigned arm64 engineering app and passed
  eight packaged-engine tests, including internal SSH-adapter rejection before
  connection. Packaging verified its ad-hoc signature. ZIP SHA-256:
  `dc3d691220b44475f03ac175f1e158386c8a033c74f3e7b0a45f136689a99a93`.
  This is bundled-entry/startup evidence, not a full packaged cross-Mac transfer
  or an Apple-signed release.

- In-app Help now offers a support email draft and an opt-in diagnostic report
  with preview/manual attachment. A bounded, persistent 60-event stream records
  phase/status/failure-category changes without raw console output or private
  paths. Missing/corrupt state no longer silently resets to idle. Longer UI
  explanations use collapsed, keyboard-operable disclosures while status,
  errors, backup state, and replacement warnings remain visible. Independent
  review checked setup/dashboard at 1280px and 320px, all 16 disclosures with
  Enter/Space, and report preview focus/scroll. Local suite: 243 Python tests
  (242 passed, one explicit skip), 10 signup tests, and native Swift typecheck.
  These checks do not certify native rendering, VoiceOver, email-client delivery,
  or the remaining migration-safety scenarios.

- The existing Stripe sandbox now has a clearly labelled $50 one-time test
  product. Its real hosted checkout completed a fictional card payment; the
  transaction was independently visible as Succeeded, then Refunded after a full
  test refund. The test link was deactivated afterward. No live product, real
  charge, app delivery, receipt email or public checkout was enabled. This is
  basic sandbox payment/refund evidence, not purchase-and-delivery acceptance.
  See [website operations](website-operations.md) for the remaining commerce gates.

- Release packaging now names ZIPs with the app version, build number and
  architecture, rejects packaged engine/app version mismatches, and rechecks
  clean source before notarization. It saves Apple's submission ID before
  waiting, requires an explicit matching `Accepted` receipt, and keeps stapling,
  ticket validation and Gatekeeper assessment ahead of archive publication.
  The final ZIP is exposed only after its copy, checksum and receipt succeed;
  partial archive failures do not leave a release-named download in the output.
  Six mocked orchestration tests cover rejection, ambiguous responses, failed
  commands, version/source drift and downstream packaging failures. These tests
  do not contact Apple and do not establish successful signing or notarization.
  Independent review accepted the fix after reproducing the partial-ZIP defect.
  Final local suite: 230 tests run, 229 passed, one explicit skip. Clean source
  `417431f` produced a versioned unsigned ZIP; checksum/ad-hoc signature checks
  and seven packaged-engine checks passed against its extracted contents.

- Codex process checks are now scoped to the migration account, including the
  known app and CLI/background-engine executable names. Unrelated logged-in
  accounts no longer require closing Codex. UID/home-ownership mismatches and
  failed or malformed process inspection block installation. Full and component
  installers recheck before backup and replacement; disposable APFS tests prove
  that a process reopening during backup leaves existing files and staging
  untouched. Background cross-Mac acceptance still requires isolated accounts
  on both Macs and has not yet been performed. Independent code/docs and rendered
  desktop/320px review accepted the change. Local verification ran 224 Python
  tests (223 passed, one explicit skip), plus 10 passing signup tests. Clean
  source `3bb894c` built a fresh unsigned app and passed all seven development-Mac
  packaged-engine checks; this does not certify a full packaged migration.

- Search Console ownership is verified for `https://migrate.segeren.com/`.
  Its sitemap was accepted with **Success** and six discovered pages, and Google
  accepted a homepage indexing request after its live check. The six live pages
  have matching canonicals and return HTTP 200 without a `noindex` directive.
  This establishes submission and discovery, not indexing or ranking.

- Retained Codex state now has frozen source-to-staged and source-to-installed
  content/tree checks, fixing the reproduced configuration/organization-state
  corruption acceptance defect. Twelve focused tests cover config, rules,
  automations, valid-but-changed databases, rollback, missing receipts, literal
  rsync filter equivalence and protected identity paths. Source identity names
  with noncanonical capitalization fail before SSH/copy/hash; staged identity
  symlinks fail before replacement. Independent code/docs and desktop/320px
  review accepted the bounded change. The new source pass is safely stoppable;
  six local browser checks found no overflow or selected axe A/AA violations.
  Installed byte comparison precedes SQLite validation and does not certify
  semantic configuration validity or that restored tasks open in Codex.
  Full local verification passed 211 Python tests (one explicit filename-support
  skip) and 10 signup tests. Clean source `1b8bb35` built successfully, and seven
  packaged-engine checks passed on the development Mac. No valid signing
  identity is currently installed in this Mac's keychain.

- Full selected-workspace and managed-worktree content verification now rejects
  corrupted staged Git refs/objects and files before replacement and rolls back
  installed mismatches against the same frozen source snapshots. Twenty focused
  tests cover content/tree changes, receipts, special files and source Stop
  cleanup/races. The complete local suite passes 196 Python tests (one explicit
  filesystem filename-support skip) and 10 signup tests. Independent code,
  documentation and desktop/320px review accepted this bounded checkpoint.
  Local browser checks at 1280/390/320px found no overflow or selected axe A/AA
  violations, and keyboard Stop left Resume available. This resolves the
  reproduced workspace-corruption acceptance defect below, not the remaining
  Git operational, different-username or clean-Mac acceptance gates.
  Clean source `abbcd7a` built a fresh unsigned engineering app; seven checks
  passed against the bundled engine. These package checks cover startup,
  configuration and inventory, not a complete packaged migration.

- Three additional disposable full-install Git fixtures make the original home
  unavailable before checking restored work. They prove representative branch,
  stash, index, dirty-file and managed-worktree continuity with the documented
  compatibility alias, plus shared object pools/absolute alternates. Strict Git
  validation passes for those ordinary layouts. A linked-refs fixture preserves
  a source-existing strict-fsck limitation without claiming clean integrity.
  These checks do not replace separate clean-Mac or cross-Mac acceptance.

- Git dependency inspection now blocks missing main/shared storage, worktree
  folders and intermediate metadata aliases before SSH. Root-anchored runtime
  exclusions preserve complete managed-workspace branches, reflogs and files.
  Twenty-one disposable Git tests and independent desktop/mobile review cover
  this checkpoint; it does not certify destination Git integrity/usability or
  whole-machine discovery. See the audit for the reproduced and fixed defects.
  Clean source `afa795b` also built successfully; all seven desktop tests passed
  against its unsigned bundled engine, including a real-process Git dependency
  inventory test. No destination transfer ran in that packaged check.

- Source `7838fd9`: 154 Python tests passed, including simulated low-space,
  failed-copy, corrupted-backup, rollback, component export, and dashboard
  boundaries. Disposable local rsync tests also exercise skills-only pause and
  safe stop after file data is staged, followed by resume with the same owner.
- Active/archived transcript bytes and relative paths are frozen and checked
  before replacement and after installation. Thirteen focused tests include
  same-count corruption, missing/extra entries, named pipes, failed scans,
  and post-install rollback. This does not prove chat reopening or Git usability.
- Native Swift shell type-checks on Apple Silicon macOS.
- A self-contained local app bundles the Python engine and offline recovery
  documentation; build receipts identify the source revision and build mode.
- The engine subprocess smoke test can run against the packaged executable with
  only system tools on PATH. It checks startup on a free loopback port, token
  protection, mandatory-backup UI, read-only mutation rejection, and shutdown.
  All six desktop tests passed against the unsigned bundled engine built from
  clean source `7838fd9`; browser skills-only configuration was exercised without
  contacting a destination. See the audit for the artifact checksum.
- Browser setup supports full migration or selected skill categories. A
  disposable local browser skills flow completed staging, explicit finalization,
  backup and verification. Independent desktop/320px review accepted it after
  fixing long-path wrapping and undersized button labels. Automated completion
  checks at 1280/390/320px found no selected axe WCAG A/AA violations or overflow.
  Native accessibility, VoiceOver, and real cross-Mac behavior remain unverified.
- Website checked at 1280px and 390px widths: upright headline, purple accents,
  separate attributed Codex product reference, $50 one-time planned price,
  no preorders or live checkout, and best-effort support disclosure.
- Launch interest uses an explicit-consent form and a fixed-recipient SendGrid
  endpoint, protected by a production Vercel Firewall rate limit. Ten Node tests
  cover validation, consent, fixed delivery destination, configuration failure,
  and ambiguous provider errors. Early unsigned-build requests remain email-only.
  No automated newsletter or paid download is enabled.

These are local checks, not proof of clean-Mac installation or a complete
cross-Mac migration. Failure tests use disposable fixtures, not user data.

## Remaining paid-release gates

- Complete the safety/configuration checks in the [failure-mode matrix](failure-mode-matrix.md),
  particularly wrong-machine rejection, cross-source destination locking,
  power-loss reconciliation, and compatibility-alias conflicts. These are
  engineering gaps, not merely Apple/account dependencies.

- Validate destination Git operational usability and historical path continuity,
  including linked worktrees, refs, status and different usernames. Workspace
  content verification fixes the corruption-acceptance defect reproduced against
  `04e3ffa`, but matching bytes alone do not establish usable destination paths.
- Open representative restored chats and verify settings/project organization
  through Codex on the separate Mac. Frozen retained-state checks fix the
  configuration-copy corruption defect reproduced against `ddd598d`; matching
  files do not establish application-level compatibility.
- Confirm Apple Developer membership activation and the intended account.
- Create Developer ID signing credentials and notarization access securely.
- Produce, notarize, staple, and verify the exact committed release artifact.
- Verify quarantined download and first launch on a separate clean Mac without
  developer-installed Python or Xcode.
- Exercise full and skills-only transfers, permissions, different usernames,
  network interruption, restart, and recovery with cross-Mac fixtures.
- Finish native UI/accessibility review against the exact release build.
- Configure and test private purchase support, refund handling, payment, and
  delivery of the exact artifact before enabling checkout.

No unsigned engineering ZIP is advertised or sold as a release. Automatic
route selection, exhaustive discovery, and automatic updating are not claimed
as delivered. See [the desktop setup guide](desktop-setup.md).
