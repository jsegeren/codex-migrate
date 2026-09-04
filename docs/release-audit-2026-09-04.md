# Release audit — September 4, 2026

## Outcome

The informational website and open-source alpha are public. The paid desktop
app is **not release-ready**. Passing automated tests or Lighthouse is not a
guarantee of migration safety, accessibility conformance, or clean-Mac support.

This was a focused readiness audit, not an exhaustive security assessment.
No real user migration, remote installation, payment, or signing operation ran.

Latest search follow-up: ownership verification and sitemap submission are now
complete; Google accepted the homepage indexing request. The earlier pending
search entries below are historical. See **Search Console completion** near the
end for the authoritative result. The paid-release outcome remains unchanged.

## Evidence

- Baseline: commit `5b73b698126d709bcdafe486ce9607e12534f6f3`.
- Baseline Python suite: 79 passing tests, including disposable local APFS
  backup/install/rollback fixtures and real dashboard subprocess checks.
- Website update candidate: 82 passing Python tests after adding screenshot,
  transfer-method, and Windows FAQ regression checks.
- Signup endpoint: 10 passing Node tests. Live inbox delivery was verified in
  the earlier launch check; this audit did not send another signup email.
- Native Swift shell: `xcrun swiftc -typecheck -parse-as-library` passed.
- Baseline GitHub CI succeeded for the deployed commit.
- Six public pages return HTTP 200, have one H1, and do not overflow at 320px.
  Visible HTML text measured at least 14px. Homepage and guide canonicals are
  correct. The three legal pages lack explicit canonicals.
- Tab navigation had visible focus outlines; FAQ expansion works with Enter;
  invalid email input is rejected by browser validation. These are focused
  checks, not full keyboard or screen-reader certification.

### Lighthouse 13.4.1, production baseline

Measured September 4, 2026 at approximately 07:42 UTC. Single lab runs, not
field Core Web Vitals. These measurements precede the new lazy-loaded UI
screenshots and FAQ additions.

| Category | Mobile | Desktop |
| --- | ---: | ---: |
| Performance | 88 | 100 |
| Accessibility | 100 | 100 |
| Best practices | 100 | 100 |
| SEO | 100 | 100 |

Mobile LCP was 3.9 seconds; desktop LCP was 0.7 seconds. CLS was zero.
The unmodified 630 KB product-reference PNG is oversized for its display size;
Lighthouse estimates roughly 600 KB of avoidable image transfer. Optimize
delivery without changing the artwork or confusing it with our own branding.

### Accessibility is not finished

- axe-core 4.13.0 found no automatic violations across all six pages using
  WCAG 2 A/AA, 2.1 A/AA, and 2.2 A/AA rule tags at narrow width.
- axe requested manual review of `aria-label` on the generic
  `.product-reference` div. Give it appropriate semantics or remove the label.
- Lighthouse's experimental, unweighted label-in-name audit flagged the home
  brand link: the visible decorative `CM` mark is hidden from the accessibility
  tree. Review with assistive technology rather than treating the score as
  proof that the flag is harmless or a confirmed conformance failure.
- A 200% text-only enlargement stress test caused horizontal overflow in the
  closing CTA at 1280px. Its fixed non-shrinking action group needs correction.
- VoiceOver, broader keyboard flows, text-spacing overrides, and native-app
  accessibility still need testing. Do not publish a WCAG-conformance claim.

## Search and helpful content

Two informative guides are live and linked from the homepage:

- `/moving-to-a-new-mac`: selection scope, identity preservation, SSH setup,
  interruption, different usernames, and verification before retiring a Mac.
- `/backup-and-recovery`: free space, verified backups, recovery paths, and
  limits of same-disk protection.

`robots.txt` and `sitemap.xml` return HTTP 200 and advertise the canonical site.
The sitemap includes the homepage, both guides, and three legal pages. The
Search Console property list in the inspected account did not contain this
site or its parent domain. Registration, ownership verification, sitemap
submission, and URL inspection remain pending. No indexing is claimed.

## Pre-signing app work

Independent read-only review: `public_release_review`.

1. **Operation-specific safe cancellation.** Inspection/export sets `running`,
   disables controls and prevents Quit, but the close control requires a
   dashboard URL those commands never create. Quit instructions point to a
   nonexistent dashboard. Avoid unsafe termination during replacement.
2. **Restore migration configuration after relaunch.** The native form resets
   but the state directory depends on its values. Add an owner-only saved
   configuration/recent-migration flow, without storing credentials.
3. **Contextual accessible labels.** Repeated workspace `Remove` buttons need
   their folder in the accessible name; verify with VoiceOver and keyboard.
4. **Offline recovery access.** Guides are bundled, but visible help links open
   GitHub. Expose the bundled documents from the app.
5. **Clean-Mac matrix.** Verify the entire packaged runtime on the minimum
   advertised macOS version; Swift's target alone does not prove Python/runtime
   compatibility. Exercise full/skills-only migration, interruption/reboot,
   different usernames, low space, permissions, and rollback on disposable Macs.
6. **Purchase readiness.** Test payment, delivery of the exact artifact,
   private support, and refunds before opening checkout.

These can advance before Developer membership activation. The build script
already supports Developer ID signing, hardened runtime/timestamps,
notarytool submission, stapling, Gatekeeper assessment, checksums, and source
receipts. That path still needs a successful real signed release run.

At audit time this Mac had zero valid code-signing identities. Once Apple
access is resolved, produce and test the exact signed/notarized artifact;
activation alone does not satisfy the other release gates.

## Web-first direction

Founder direction: local data, browser-based experience, Mac-only initially.

- Keep the existing local migration engine authoritative.
- Move guided setup, scope selection, status, resume and recovery into the
  local browser experience; retain a small signed launcher/helper.
- Preserve loopback binding, token checks, explicit mutation confirmation,
  native folder permissions and SSH host verification. No public unauthenticated
  endpoint controlling a Mac and no workspace upload to our servers.
- Current delivery remains native setup plus a browser dashboard. The unified
  browser setup flow is planned, not implemented by this website update.
- A Windows version requires platform-specific implementation and validation;
  neither Windows nor cross-platform migration is currently supported.

## Screenshot provenance

New homepage/backup-guide screenshots use the current dashboard HTML directly
from `src/codex_migrate/dashboard.py`, rendered in a real browser with disposable
sample states. The fixture has no migration engine or SSH and rejects POSTs.
They are labeled as sample data, not evidence of a live 184 GB transfer or
clean-Mac certification. No customer paths, credentials or conversations appear.

## Follow-up implementation — September 4

Implemented after the baseline audit; this does not change the overall
**not release-ready** outcome:

- Inspection and skills-export controls now request cooperative cancellation.
  Skills backup/replacement defers cancellation through verification, receipt
  output, and lock release. Shutdown messages do not assert an unverified
  pre-replacement state. Force Quit and power loss are not covered by this
  cooperative guarantee.
- Transport abort cleanup terminates and reaps the local process group with
  bounded pipe draining, including when its leader has already exited.
- The native shell restores the last launched non-secret setup from an
  owner-only atomic local file. Changes reset to disabled; SSH key selection
  and dashboard tokens are not persisted. Multiple saved migrations and the
  browser-first setup flow remain outstanding.
- Workspace Remove controls have contextual accessibility labels. Bundled
  setup, recovery, and security guides have offline entry points.
- Closing CTA and narrow header wrapping were corrected. Homepage text-only
  200% stress checks at 1280, 390, and 320 CSS pixels have no page overflow.
  The offscreen, clipped honeypot is intentionally excluded from visible-layout
  interpretation. Normal mobile rendering was also inspected.
- Legal-page canonicals were added; unnecessary homepage ARIA labels removed.
- Verification: 95 Python tests, 10 signup tests, and native Swift typechecking
  passed. Tests include actual subprocess signal cleanup, exited-leader pipe
  cleanup, late-stop receipt reporting, and compiled Swift persistence checks
  for permissions, corruption, symlinks, and replacement.
- Independent review by `public_release_review` found the exited-leader cleanup
  and late-stop reporting bugs; both received fixes and regression tests.
  Native rendered/VoiceOver checks remain unverified because native UI access
  failed. A local unsigned engineering build succeeded, but it predates the
  final transport corrections and is not a release artifact.
- The independent reviewer also verified normal and enlarged-text website
  rendering at all three widths. A stop/exit race finding was fixed using the
  known process-group ID and an already-exited guard, with a regression test.

Still open: full browser-first setup/recovery, icon delivery performance,
comprehensive accessibility checks, real clean-Mac/cross-Mac recovery tests,
signing/notarization, Search Console verification/submission, and tested paid
purchase/delivery/refund flow. The baseline Lighthouse results above have not
been represented as measurements of these changes.

## Browser-first follow-up

- `launch` and the native **Open browser setup** button now open real local
  setup. Destination/folder selection, explicit per-session change permission,
  private saved setup, and navigation to the existing migration dashboard are
  implemented. No destination connection or transfer runs during configuration.
- Browser refresh retains the tab-scoped control token. Setup APIs require the
  loopback Host, a matching Origin when supplied, and the control token.
- Inspection is asynchronous and has cancellation checkpoints during local
  scans; Stop remains responsive. Setup/action requests are serialized against
  normal shutdown. Stale setup tabs cannot open a picker after attachment.
- Independent review found and prompted fixes for synchronous inspection
  blocking Stop, restored-root ordering invalidating staging credit, and stale
  picker requests blocking actions. Regression tests cover each case.
- Current local suite: 113 Python tests passed; Swift shell typechecking passed.
  Real HTTP fixtures cover token/origin rejection, path validation, planning
  guards, state reuse, secret-field exclusion, stop responsiveness, and shutdown
  serialization. A browser fixture with SSH disabled passed setup → dashboard
  → refresh; Start remained disabled. Setup rendering had no page overflow at
  1280/390/320px and axe-core found zero violations in the selected WCAG A/AA tags.
- Independent rendered review at 1280/320px confirmed readable controls and
  recovery limitations. Its key-copy wording finding was corrected: selecting
  an SSH key does not add it to scope, but workspace-contained keys are included.
- CI exposed a Darwin process-exit signalling race after the prior follow-up.
  The correction in `4a476e8` passed both Python 3.9 and 3.12 CI. This is not a
  claim that the new browser candidate has already passed hosted CI.

At that checkpoint, remaining browser work included integrated skills-only
exports (addressed below), richer saved migration
selection/import, and complete recovery/accessibility checks. Existing native
and CLI migrations must resume using their original state/entry point; the new
browser flow does not import them or adopt their staging. Native folder-picker
permissions, VoiceOver, and clean-Mac/cross-Mac behavior remain unverified.
The overall project remains **not release-ready**.

The previously identified full-flow personal-skill coverage gap is addressed
in the follow-up below. This does not close the other release gates.

### Full-migration personal skills

- Full inspection now discovers current and legacy personal custom skills,
  includes materialized sizes in incoming-space estimates, and lists their
  individual destination paths. Current-location skills win same-name ties.
  Ordinary root metadata and `.system` are excluded from the personal pass;
  invalid skill directories and broken aliases stop inspection rather than
  silently disappear. The full `.codex` copy remains otherwise unchanged.
- Skills share the full staging/backup/install/rollback transaction. Existing
  destination skill aliases are backed up as links without following them;
  unrelated destination skills remain intact. Personal skills receive frozen
  SHA-256 regular-file and exact directory-tree verification before backup and
  after installation. No file contents or checksum values are logged.
- Skills cannot silently expand the confirmed replacement scope after staging
  or restart. Changed scope or older staging without a scope record requires
  Resume, review, and a fresh Finalize confirmation.
- Real disposable local rsync/APFS fixtures cover different home names,
  materialized file links, current-versus-legacy precedence, destination backup,
  corrupted staging, installed corruption with rollback, and destination aliases.
  Additional tests cover scope collisions, metadata, unsupported names, broken
  aliases, protected credential references (including relocated SSH roots), and
  unexpected special files. No real workspace or remote Mac was transferred.
- Independent reviewer `public_release_review` found and prompted fixes for
  silent omission, relocated protected paths, special-file validation, and
  confirmation-scope expansion. A corruption fixture exposed zsh ERR_EXIT
  inside a verifier function bypassing the caller's EXIT trap; explicit
  function returns and top-level exits now trigger rollback, with regression
  proof. Review outcome: accepted with fixes, no remaining blocking finding
  within this bounded change. Independent focused suite: 61 tests passed.
- Actual dashboard fixture at 1280/390/320px showed skill counts, destinations,
  and selected-versus-verified status with no page overflow. Axe-core 4.13 found
  zero selected WCAG A/AA tag violations at 320px; independent desktop/320px
  visual review passed. This is not VoiceOver or full WCAG certification.
- Full local regression suite: 129 Python tests passed; all 10 signup tests
  passed. Hosted CI and packaged validation of this candidate remain separate
  checks; no prior build is being represented as containing this code.

Still open at that checkpoint: browser selective-export controls (addressed
below), broader inventory/recovery
coverage, clean-Mac and real cross-Mac acceptance, complete accessibility
testing, Search Console submission, signing/notarization, and paid distribution.
The prior packaged-helper check below predates these changes; it is not evidence
that the new skills code has been validated in a packaged release.

### Packaged browser-helper check

An unsigned Apple Silicon engineering build from clean source
`e6ba09f3309b212e861fd5e8fa5085ee52460e43` passed six desktop checks against
its actual bundled engine. Both `launch` and `serve` started private local
servers and shut down normally under disposable test homes. Engine subprocesses
used only the system PATH with Python/DYLD overrides removed. No destination SSH
or migration ran. This verifies packaging inclusion and startup on the build
Mac, not clean-Mac, minimum-macOS, native-picker, signing, or Gatekeeper support.

Artifact: `Codex-Migrate-arm64-LOCAL-UNSIGNED.zip` (engineering only).
SHA-256: `341e5e74585ecc1e03aca955bd5cc0a52cfeb89a8c56ac99a7afb549e1950d8f`.

### Browser skills-only migration checkpoint

- Browser setup now supports personal skills, workspace skills, or both. An
  adapter uses the existing staging, pause/stop/resume, shutdown, and explicit
  finalization state machine, with separate owned staging and saved scope.
  Full-migration state keys remain compatible. This does not adopt older CLI
  or native export staging.
- Replacement is limited to listed skills. Conversations, configuration, whole
  repositories, and unrelated destination skills are not replaced. Selected
  destinations receive mandatory verified backups; both staged and installed
  skills must match the same frozen source file-content and tree snapshot.
- Eight disposable local rsync/APFS adapter tests cover successful selective
  installation, preservation of full staging and unrelated destination data,
  restart and owner identity, changed scope, foreign staging, workspace-only
  selection, post-install corruption with rollback, and pause/safe-stop/resume
  after at least 32 KiB of real file data is staged while rsync remains live.
  These are not network-disconnection, power-loss, or real cross-Mac tests.
- Actual browser setup → stage → explicit Finalize → complete succeeded against
  disposable skill data, with SSH replaced by local fixture transport. The UI
  reported one selected and one verified skill with a backup receipt. No real
  workspace or remote Mac was modified.
- Desktop and 390/320px checks found a long-path overflow and corrected it.
  Independent review found invalid button font shorthand falling back to
  13.3333px; explicit properties now render all six buttons at 15px. Fresh
  completion checks at all three widths show no overflow and zero axe-core
  4.13 violations under selected WCAG A/AA tags. These checks do not establish
  full WCAG conformance or VoiceOver acceptance.
- Independent reviewer `public_release_review` accepted the bounded change
  with fixes after reviewing fresh desktop/320px setup, staged, and completed
  views and running 39 focused tests. No remaining blocker was identified
  within this checkpoint; native and real cross-Mac acceptance remain separate.
- Local regression suite: 141 Python tests and 10 signup tests passed. The
  real-helper startup test also configures the skills adapter in read-only
  mode and confirms Start is rejected without enabling destination changes;
  it can run against the packaged engine with a system-only subprocess PATH.
  Candidate-specific hosted CI and packaged checks are separate evidence.
- Hosted CI for source `3b5030bb01a4a1473f262694094b0db92b9f1390` passed on
  Python 3.9 and 3.12, including native Swift typechecking and signup tests:
  [run 33855189632](https://github.com/jsegeren/codex-migrate/actions/runs/33855189632).

The overall release remains open: broader inventory and interruption/recovery
acceptance, clean-Mac and real cross-Mac packaged testing, complete accessibility
checks, Search Console submission, signing/notarization, and paid distribution
are not closed by this checkpoint.

### Packaged selective-helper check

Clean committed source `3b5030bb01a4a1473f262694094b0db92b9f1390` produced
a fresh unsigned Apple Silicon engineering build. All six desktop checks passed
with `CODEX_MIGRATE_TEST_ENGINE` pointing at its bundled executable. The actual
browser helper configured the skills-only adapter, remained idle/read-only, and
rejected Start without change permission. Engine subprocesses had a system-only
PATH and no Python/DYLD overrides. No destination SSH or migration ran in this
packaged check; the local transaction/browser evidence above ran from source.

Artifact: `Codex-Migrate-arm64-LOCAL-UNSIGNED.zip` (engineering only).
SHA-256: `141a0e59c92d0a1150f1dcb35e2108942711ae3e7248b90f23ac7a0f2bc20bc2`.
The build receipt records a clean source tree. This remains build-Mac startup
and packaging evidence, not clean-Mac, signing, Gatekeeper, or complete
packaged-migration acceptance.

### Conversation-content verification checkpoint

- Two disposable full-migration fixtures demonstrated that the preceding code
  accepted corrupted staged and installed transcript bytes when file counts
  remained unchanged. Counts and SQLite checks alone were insufficient.
- Full finalization now freezes SHA-256 checks for active and archived `.jsonl`
  transcript bytes and relative paths after the final copy. The same checks run
  against staging before backup/replacement and against installed data under
  the rollback trap. The success receipt explicitly records conversation-content
  verification. No chat text or checksum values are logged.
- Thirteen focused tests cover same-count corruption before/after installation,
  renamed and extra transcripts, archived corruption, unusual filenames,
  symbolic links, source and destination FIFO entries, failed directory scans,
  missing receipts, and absence of transcript text/login paths in the script.
  Post-install corruption and FIFO tests confirm destination rollback.
- Independent reviewer `public_release_review` found an extra destination FIFO
  bypass in the initial change. It was fixed with staged and post-install
  regressions; final review accepted with fixes and no remaining blocker within
  this bounded change. The reviewer independently ran all 13 focused tests.
- Full local suite: 154 Python tests passed. Prior hosted CI for documentation
  commit `be0e3ca` also passed; candidate-specific CI follows publication.
- Hosted CI for `7838fd956e0815c134e03d817f1df18951c8aa1a` passed on Python
  3.9 and 3.12, including Swift typechecking and signup tests:
  [run 33855903871](https://github.com/jsegeren/codex-migrate/actions/runs/33855903871).

Verification reads all transcript bytes once on the source and twice on the
destination, so large histories add verification time. This is not an atomic
filesystem snapshot, JSON semantic validation, a proof of every workspace byte,
or proof that Codex can open every chat or resolve every Git worktree. Those
remain separate release acceptance work, not waived requirements.

Clean source `7838fd956e0815c134e03d817f1df18951c8aa1a` also built an unsigned
Apple Silicon app. All six desktop checks passed against its bundled engine,
with system-only subprocess PATH and no Python/DYLD overrides. This checks
startup/configuration/guards on the build Mac, not a full packaged migration.
The transcript corruption fixtures above run from source, not inside the ZIP.

Artifact: `Codex-Migrate-arm64-LOCAL-UNSIGNED.zip` (engineering only).
SHA-256: `4ad3195bc6d13e9c2abc071355aa6b7e7487ad72346c0d30d0115dfac9aa6aab`.

### Git dependency inventory and workspace-copy checkpoint

- Full inspection now lists repositories, linked Git directories, and bare or
  separate Git storage in selected workspace folders and Codex-managed
  worktrees. It checks common directories, registered worktrees, object
  alternates, metadata links, and intermediate aliases. Missing required
  folders and unsupported/unreadable metadata block preflight before SSH;
  no discovered folder is silently added to transfer scope.
- Independent review reproduced loss of external linked refs and an actual
  managed-workspace branch named `cache/important`. Root-anchored Codex runtime
  exclusions now preserve managed repositories' branches, reflogs, and working
  files while retaining root authentication/installation exclusions. A further
  review found omitted intermediate symlinks; their parent folders are now
  included in dependency requirements. All three defects have regressions
  demonstrated failing before their corrections.
- Twenty-one disposable Git tests cover main/shared storage, sibling and
  stale worktrees, separate Git directories, bare/alternate object stores,
  nested repositories, external/chained links and aliased alternate paths,
  unchanged refs/index/stash/dirty files, invalid metadata, and pre-SSH guards.
  Actual system rsync tests compare source/copy refs and managed-workspace file
  bytes and check copy/inventory exclusion agreement. No real user repository
  or remote destination was touched.
- The real browser fixture's Inspect action displayed the missing main
  checkout before any SSH call. Desktop/390/320px checks caught and fixed
  status-message long-path overflow. Fresh checks show no horizontal overflow
  and zero axe-core 4.13 violations for selected WCAG A/AA tags. The Git summary
  retains keyboard focus and Enter opens/closes it. This is not full WCAG or
  VoiceOver certification.
- Independent reviewer `public_release_review` accepted with fixes after
  inspecting actual code, running 44 focused tests, and reviewing fresh desktop
  and 320px screenshots. No remaining blocker was found within this bounded
  change. The final full local run passed 175 Python tests and all 10 signup
  tests. Candidate-wide CI follows publication.
- Hosted CI for `afa795b3bf6d08f0ff1a7d42694101cb0a05f636` passed on
  Python 3.9 and 3.12, including native Swift and signup checks:
  [run 33857442488](https://github.com/jsegeren/codex-migrate/actions/runs/33857442488).

This checkpoint does not certify Git object integrity, destination refs/index
and dirty-file equivalence, historical username/path resolution, or every Git
project on the machine. Those remain separate acceptance requirements.

Clean committed source `afa795b3bf6d08f0ff1a7d42694101cb0a05f636` produced a
fresh unsigned Apple Silicon engineering app. Seven desktop tests passed
against its bundled engine with system-only subprocess PATH and no Python/DYLD
overrides. The new real-process inventory check detects a managed worktree's
missing main repository, then reports both locations covered when that main
repository is explicitly selected. This uses disposable Git fixtures and does
not contact a destination. It is build-Mac packaged-engine evidence, not a
complete packaged migration, clean-Mac acceptance, signing or notarization.
The added real-process inventory regression brings the follow-up full local
suite to 176 passing Python tests.

Artifact: `Codex-Migrate-arm64-LOCAL-UNSIGNED.zip` (engineering only).
SHA-256: `923649072724b82aa311acfd798acf54bc35e66a7769b424cb281ec279f2bd86`.

### Reproduced workspace-verification defect

After the Git dependency checkpoint, a disposable full-migration probe against
`04e3ffa` initialized a committed source repository, selected its workspace,
ran the actual local rsync staging and APFS installation fixture, and changed
only the staged `.git/refs/heads/main` to forty zeroes. `_install_and_verify`
returned a completion receipt and installed that corrupted ref. Source refs
were not changed; the fixture cleaned up both disposable homes afterward.

The existing transcript checks and destination rollback-backup checks do not
prove source workspace/Git preservation. Required follow-up: reject staged
workspace-content mismatches before replacement, compare installed data with
the same frozen source expectations, exercise post-install rollback, and test
destination Git usability independently. Do not represent this alpha as a
verified paid release while this blocker remains.

### Workspace-content verification correction

The corruption-acceptance defect above is corrected by frozen source-to-staged
and source-to-installed workspace tree checks. Git operational acceptance
remains open; the historical probe is retained as evidence of why the checks
were necessary.

- `workspaces.py` streams SHA-256 with one system-Perl process per tree. The
  versioned, length-framed representation includes file bytes, byte-sorted
  names, regular-file/directory permission bits, empty directories and link
  text. It does not follow links or log file contents/checksums. Required Perl
  modules and no-follow flags are probed on both Macs during full inspection.
- Selected roots and Codex-managed worktrees use the same frozen snapshots
  before backup/replacement and after installation under rollback protection.
  Absent managed worktrees must remain absent, not merely empty. Completion
  requires a workspace verification marker and matching root count.
- Twenty focused tests use disposable Git repositories, system rsync and real
  local APFS installation: corrupted staged refs/object bytes, installed
  refs/files and rollback, names/permissions/links/empty directories, managed
  scope, frozen expectations, missing/mismatched receipts, source Stop process
  cleanup, Unicode/newline names, special files and changing source files.
  The raw non-UTF8 filename test explicitly skips when APFS rejects that name
  with EILSEQ; it is not recorded as a passing capability.
- Independent reviewer `public_release_review` reproduced a source-verification
  cancellation race: a phase update could overwrite cancellation and leave no
  worker but a running UI. Locked phase publication plus stopped-state recovery
  fixed it; a deterministic regression and real hash-child cancellation test
  cover the correction. Final independent review accepted with fixes after 54
  focused tests (one filename-support skip) and actual desktop/320px review.
- Playwright checked the source-verification and actual local fixture-completion
  screens at 1280/390/320px. All six checks found no horizontal overflow or
  axe-core 4.13 violations for selected WCAG A/AA tags. Keyboard Tab/Enter on
  Stop safely ended the held source check and enabled Resume. The source check
  was deliberately held for interaction testing; screenshots use disposable
  data, not a remote migration. Fixture preflight metrics were not populated.
- Full local verification: 196 Python tests, one explicit filename-support
  skip; all 10 Node signup tests passed. `git diff --check` passed.

Hashing reads workspace files once on the source and twice on the destination;
large workspaces may take substantial time. Source verification is safely
stoppable and restarts on the next Finalize; staged data is retained. Destination
verification, backup and install remain a protected phase. No atomic snapshot,
ACL/xattr/ownership/timestamp/hard-link proof, Git semantic usability, clean-Mac
acceptance or whole-release certification is inferred from these checks.

Clean source `abbcd7a12a58aefc9929e92ff01a9404b27b3040` produced a fresh
unsigned Apple Silicon engineering app. All seven desktop checks passed against
the actual bundled engine with system-only subprocess PATH and no Python/DYLD
overrides. The build receipt records a clean source tree. These are startup,
configuration and inventory checks on the build Mac; the full workspace
verification transactions above run from source, not inside this ZIP.

Artifact: `Codex-Migrate-arm64-LOCAL-UNSIGNED.zip` (engineering only).
SHA-256: `a8345a2c3f71affbfbe8c074f886a9682a2dc4c442cd0edce920fc70d920e2c9`.

Hosted CI for `abbcd7a12a58aefc9929e92ff01a9404b27b3040` passed on
Python 3.9 and 3.12, including native Swift and signup checks:
[run 33859299517](https://github.com/jsegeren/codex-migrate/actions/runs/33859299517).

### Disposable Git operational/path acceptance

Three local full-install fixtures now test Git after relocating the disposable
source home so original files cannot mask broken destination references. An
actual managed linked worktree cannot run Git status until the documented
old-home compatibility alias is created. With that alias, source and restored
refs, HEAD, stash object IDs, index entries, staged/unstaged diffs and untracked
status match. Strict full fsck passes for the main/linked-worktree fixture and
the separate shared-object-pool/absolute-alternates fixture. Workspace file
hashes remain unchanged after the read-only Git acceptance commands.

A third fixture covers linked refs. Normal commands remain equivalent after
restoration, but this Mac's strict fsck rejects that symlink layout on the source
as well. The test compares the existing result rather than misreporting it as a
clean integrity check or migration-created corruption. All fixtures disable
inherited Git configuration, hooks, fsmonitor and optional index locks; no user
repository or remote Mac is used.

Independent reviewer `public_release_review` ran and accepted all three tests
as local path-compatibility evidence. The linked-refs test compares source and
destination fsck results without requiring every installed Git version to
reject that source layout.
The full local suite passed 199 Python tests with the same explicit
filename-support skip. The final portability adjustment also passed all three
Git restore tests; candidate-specific hosted CI follows publication.

This demonstrates representative local path compatibility with a reviewed
alias, not automatic remapping, every Git feature/version, clean-Mac installation,
real cross-Mac acceptance, or restored Codex chat reopening.

### Reproduced Codex configuration/state verification defect

A disposable probe against `ddd598d` staged a full migration containing
`config.toml` and `.codex-global-state.json`, then changed only those two staged
files. The actual local rsync/APFS installation returned a completion receipt
with the altered configuration/organization fixture installed; the source was
unchanged. Existing transcript, personal-skill and workspace checks do not
cover these files. No user Codex state or remote Mac was involved.

This is the next preservation blocker: supported Codex state outside existing
content checks needs source-frozen staged and installed verification, with
regressions for corruption, omissions/additions and rollback. It must share the
actual transfer exclusions, never read/copy source authentication, preserve
destination identity, and avoid treating runtime exclusions as migration data.
Do not declare the release candidate complete while this gap remains.

### Retained Codex state verification correction

The reproduced configuration-copy verification gap above is corrected. The
same disposable probe now fails before installation, with staging retained.
The correction adds a separately versioned streaming tree snapshot for retained
Codex state to the stoppable source phase. That frozen snapshot checks staging
before backup/replacement and the installed copy under rollback; a distinct
`codex_state_content_verified` receipt is required before completion.

- The verifier compiles canonical transfer exclusions into byte-exact filters.
  Directory-only rules skip real directories, not regular files or symlinks
  with those names. Wildcards span newlines but not path separators. Managed
  worktrees have their existing separate complete check, including absent/type
  protection. Other retained state, including transcript data, is read by this
  pass. Separate transcript checks remain for their stricter no-link contract.
- Source `auth.json` and `installation_id` are not opened. Identity files with
  noncanonical capitalization fail before remote contact, copy and hashing;
  this protects against case-insensitive filesystem aliases. Unexpected staged
  identity symlinks are rejected before replacement. These path guards are not
  general detection of secrets under other retained names or inside workspaces.
- Twelve focused tests cover staged configuration/organization/rules/automation
  corruption, valid-but-changed SQLite before and after install, rollback,
  added/missing/renamed state, frozen expectations, auth FIFOs, case variants,
  staged identity links, missing receipts, failed hashing and actual rsync
  filter equivalence for directories/files/links/newlines/nested names.
- Independent reviewer `public_release_review` accepted code, docs and rendered
  desktop/320px views after running 66 focused cross-feature tests (one explicit
  filesystem filename-support skip), then all 12 final retained-state tests.
  No blocker remained in this bounded change. A conservative existing Git
  coverage-helper issue for regular files named `cache`/`logs` remains separate:
  it can overblock selection but does not silently omit transferred data.
- Playwright inspected actual local fixture completion and a deliberately held
  source-state hashing phase at 1280/390/320px. All six selected axe-core 4.13
  WCAG A/AA checks found no violations or horizontal overflow. Keyboard Stop
  cancelled the source check and left Resume enabled. These are disposable
  fixtures without destination SSH; preflight metrics were not populated.
- Final local verification passed 211 Python tests with one explicit filesystem
  filename-support skip and all 10 signup tests. `git diff --check` passed.

Only the Codex root mode is excluded from comparison because install explicitly
sets it to 700; retained child modes are checked. Installed bytes are compared
before SQLite quick checks, which can change database sidecars. This adds one
source and two destination reads of retained Codex state (including transcripts
also checked separately). No atomic snapshot, semantic application validation,
clean-Mac or cross-Mac acceptance, or whole-release certification is implied.

Earlier hosted CI for Git acceptance `ddd598d` and its audit follow-up `5a68b9f`
both passed on Python 3.9 and 3.12, including native and signup checks:
[Git acceptance](https://github.com/jsegeren/codex-migrate/actions/runs/33859578368),
[audit follow-up](https://github.com/jsegeren/codex-migrate/actions/runs/33859669625).

Clean source `1b8bb35ffddc42cb158b9c672a98ed459775ef53` built a fresh unsigned
Apple Silicon engineering app. All seven packaged-engine tests passed with
system-only subprocess PATH and no Python/DYLD overrides. This covers startup,
configuration and inventory on the development Mac, not a complete packaged
migration or clean-Mac acceptance. The local keychain still reports zero valid
code-signing identities; this is not a determination of Apple membership status.

Artifact: `Codex-Migrate-arm64-LOCAL-UNSIGNED.zip` (engineering only).
SHA-256: `864d75aa3ff7732a91e500ee7f5cdd7982521d8948b5893a4ec694011899ee64`.

### Search Console completion

The maintainer's existing authenticated Chrome session was used to add only the
URL-prefix property `https://migrate.segeren.com/`. Google reported **Ownership
auto verified**, with **Domain name provider** as the verification method.
No DNS changes, new verification credential, unrelated-property edits, or website
deployment were needed.

`https://migrate.segeren.com/sitemap.xml` was fetched successfully and submitted.
Search Console reported **Sitemap submitted successfully**, then a persisted
table row with **Success**, September 4, 2026 submitted/last-read dates, and
**6 discovered pages**. These are the homepage, both guides, and three legal
pages. Each live page returned HTTP 200, one H1, a matching self-canonical and
no HTML or response-header `noindex` directive.

Homepage URL inspection reported **Discovered - currently not indexed**. An
indexing request completed Google's live eligibility check and returned
**Indexing requested**, with the URL added to a priority crawl queue. No actual
indexing, ranking, traffic, or Google completion date is claimed. This closes
the registration, ownership, sitemap-submission and homepage-inspection gates,
not the remaining app/distribution gates.

The Apple Developer account was separately refreshed and still showed
**Pending** with the enrollment purchase/process notice. No repeat purchase or
account change was attempted. Apple activation and signed-artifact verification
remain open. Genuine cross-Mac testing requires a disposable destination account;
the active migrated user workspace must not be replaced as a test fixture.

Hosted CI for `0658dda55c216e82a19d45c3bb61780cc7465a15` completed successfully:
[verification evidence CI](https://github.com/jsegeren/codex-migrate/actions/runs/33860558249).

### Reference guidance

- [Lighthouse scoring excludes manual checks](https://developer.chrome.com/docs/lighthouse/accessibility/scoring).
- [Submitting a sitemap does not guarantee crawling or indexing](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap).
- [Apple Developer ID notarization and distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
