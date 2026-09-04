# Desktop release readiness

The downloadable paid app is **not released**. Publishing source and the
informational website does not open checkout or certify a customer download.

See the [September 4 audit](release-audit-2026-09-04.md) for current automated
results, accessibility findings, and pre-signing work still open.

## Candidate checks completed on the development Mac

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
