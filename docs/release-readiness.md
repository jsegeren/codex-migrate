# Desktop release readiness

The downloadable paid app is **not released**. Publishing source and the
informational website does not open checkout or certify a customer download.

See the [September 4 audit](release-audit-2026-09-04.md) for current automated
results, accessibility findings, and pre-signing work still open.

## Current gate map

Checked September 4 against the source checkpoints below and the live public site. Historical
checkpoints below are evidence, not separate promises that their then-pending
work is still missing. Neither the full release nor the release-candidate
handoff is complete while the engineering acceptance gates remain open.

| Requirement | Evidence now | Next proof / owner |
| --- | --- | --- |
| Supported conversations, organization, settings, skills and complete selected workspaces | Frozen content/tree checks, retained destination identity, Git dependency discovery and bound Git baseline; local installation/rollback fixtures | Codex must reopen representative restored chats, settings and projects on the separate Mac. Codex leads; Josh provides disposable accounts. |
| Scope is explicit, not “everything on the Mac” | Selected roots and dependency issues are reported; unsupported visible storage overrides, source project configuration, retained destination ancestor configuration, fixed system defaults, visible managed-preference keys, filenames and cloud-only flags stop early | Real configuration/version/provider matrix; managed preference visibility across launch contexts, cloud-managed policy, arbitrary role references and unflagged cloud storage remain unverified. Codex owns testing and any resulting fixes. |
| Full and selective migration, pause/resume and recovery | Full/skills-only staging, persisted setup, mandatory verified backups, guarded replacement, guided reconciliation and preserved displaced work have local fixture coverage | Packaged full and skills-only runs across the two Macs, including disconnect, restart, low space and recovery. Never use Josh's active migrated workspace. |
| Git and old-home paths remain usable | Local linked-worktree/alternate-storage checks with source home offline; read-only path/Git rechecks preserve installed work | Different-user cross-Mac acceptance and representative development commands. Matching fingerprints alone do not prove every future command works. |
| Browser-first local-data experience and clear status/help | Loopback helper, SSH transfer, saved setup, collapsed optional Help, bounded private-free diagnostic events and operation-specific controls | Native permission/VoiceOver checks and real route interruption acceptance. Automatic route selection and updating are not implemented. |
| Public website, useful guides, screenshots, price and launch intake | Six live pages; two informative guides; sample-labelled real UI screenshots; $50 planned edition with checkout closed; prior controlled SendGrid inbox receipt and signup tests | Preserve the existing rate-limit and launch-only consent. No new email was sent in the latest read-only audit. |
| Website accessibility and performance | Prior Lighthouse/axe results plus fresh desktop/320px rendering, six-page text-spacing and 200% text-size overflow checks | Manual assistive-technology and broader keyboard acceptance remain open; no WCAG-conformance claim. See the audit for exact scope. |
| Domain, search discovery and cross-promotion | Live canonical domain/robots/sitemap; recorded Search Console ownership, successful sitemap submission and accepted homepage request; You.one link on the live homepage; fresh HTTP 200 check of segeren.com confirms its “Explore Codex Migrate” link to the canonical domain | Actual indexing/ranking is not guaranteed. No repeated indexing request needed. |
| Reproducible identifiable packaged app | Clean-source unsigned arm64 bundle, checksum and eight passing actual engine checks (one filesystem skip); signing/notarization pipeline has mocked tests | Confirm intended Apple membership/team, install signing credentials securely, then notarize/staple and test the exact quarantined download on a clean Mac. Josh's account access is required. |
| Paid purchase, delivery, support and refunds | Best-effort support/legal pages; actual sandbox payment and full manual refund recorded, test link deactivated | Josh selects merchant/tax arrangement. Codex then implements and tests server-verified, replay-safe fulfillment and recoverable delivery of the exact signed artifact before checkout opens. |

Current access limits: the Mac remains locked for native/browser account work,
and the source test user `codexmigratesource` is absent. The destination test
account is not yet confirmed. These block real-account acceptance, not all
engineering work. Do not create another Apple purchase or enable live checkout
as a workaround.

## Candidate checks completed on the development Mac

- Custom agent configuration references now stop full migration for explicit
  scope review. A disposable source fixture reproduced inventory succeeding
  without reporting a referenced role file outside the selection; independent
  review also reproduced a referenced file escaping the storage-key screen.
  The existing bounded lexical reader now detects `config_file` keys without
  resolving/opening their targets or disclosing values. This includes in-scope
  references; it is unsupported-configuration detection, not a reference resolver
  or evidence that the referenced file actually relocates a database.
  Eight new tests cover quoted/escaped/dotted/inline keys, profiles, ordinary
  comments/value nonmatches, early source inspection, selected projects,
  retained destination ancestors, fixed system defaults and late rejection
  preserving original destination data/staging. Independent
  `public_release_review` accepted the code and scoped documentation after 46
  focused tests; the primary passed 59 focused tests. The full suite passed
  530 of 537 tests with seven filesystem skips; all 16 Node tests, Swift
  typecheck and diff checks passed. Suite notarization is mocked, not Apple
  approval. Real cross-Mac/configuration acceptance remains open.
  Clean source `904bfdf8e3a3862130b7e11ea7d05a54d4761d4d` produced a local-only
  unsigned arm64 app. Eight of nine actual packaged-engine checks passed, with
  one case-sensitive-filename skip. The subsequently added, independently
  reviewed engine assertion confirms selected-project reference rejection,
  private-value suppression and unchanged fixture configuration in that binary.
  ZIP SHA-256:
  `92df762aa77ddcdfa4bb43b81c36608071dc49617da21357a7e7c821da6c4b19`.
  Hosted run 33886955990 passed on Python 3.9 and 3.12. The follow-up engine
  regression on `d06df05b14a598d64f78e16b5f3145c9f2a3e280` also passed both
  versions in run 33887061246. The previous inactive engineering build
  was moved recoverably to Trash after checking open files and running processes;
  user-running apps were left intact.

- Shared Help keyboard behavior now retains a useful focus target after
  diagnostic preparation. A reproduced HTTP-error bug dropped focus onto the
  page body; failure now returns it to Prepare, and successful preparation
  focuses the preview only if the user has not moved to another control.
  Repeated preparation while pending is ignored. Six new deterministic Node
  regressions cover success, HTTP failure, invalid JSON, moved focus and duplicate
  activation; these and all ten signup tests pass and run in CI. All 54 focused
  Python support/dashboard/setup tests pass. Independent `public_release_review`
  accepted the diff, reproduced failure recovery on setup and dashboard at
  1280px/320px, and verified delayed responses preserve moved focus. The primary
  also verified successful preview focus and delayed success after Tab in the
  real browser. Optional details remain collapsed; no horizontal overflow was
  observed in the reviewed Help states. Fixtures contain sample data and cannot
  migrate, SSH or send email. This is bounded keyboard evidence, not VoiceOver
  or WCAG-conformance certification.
  Clean source `8eb25b78cc12aefcefc50cbd5149d6cf0d558c78` produced a local-only
  unsigned arm64 app; eight of nine actual packaged-engine startup/CLI/browser
  checks passed, with one case-sensitive-filename skip. ZIP SHA-256:
  `4043e42b0ef12a8bc6fd3dece86ac447f1cf6f14faee797b11026d37b4f96a43`.
  Hosted run 33886223766 passed on Python 3.9 and 3.12. The separate browser and sample server
  were closed; the superseded inactive engineering build was moved recoverably
  to Trash after checking processes/open files. User-running apps stayed intact.

- Full migration now checks presence of the two documented macOS managed
  preference keys for the executing source account and destination SSH account.
  No policy payload is converted, decoded, printed or changed. Present keys
  (including false/empty values), probe errors and timeouts block for review;
  checks repeat before source copying/freezing and destination replacement.
  Independent `public_release_review` accepted the code and scoped instructions,
  passed the initial 12 focused tests and then the cancellation/UNKNOWN additions.
  All 13 focused tests pass locally. The full suite before the final test addition
  passed 521 of 528 tests with seven filesystem skips; ten signup tests, Swift
  typecheck and diff checks passed. In-process fixture preferences are not
  persisted. Late rejection keeps staging and original destination data without
  starting a backup. The cancellation regression verifies the launched process
  is reaped, not every descendant PID independently. This is not MDM enrollment,
  effective-policy, restricted-launch visibility or real managed-account/SSH
  certification. Those acceptance gates remain open.
  Clean source `30b48473a23e26005adc535eaf0e43b5dd073ebe` produced a local-only
  unsigned arm64 app. Eight of nine actual packaged-engine startup/CLI/browser
  checks passed, with one case-sensitive-filename skip. ZIP SHA-256:
  `7e7037cffc6d4d8fe86eecaaca540750df5c552cfdb2266078f2210cce5511f9`.
  Hosted run 33885738099 passed on Python 3.9 and 3.12. The previous inactive engineering build
  was moved recoverably to Trash after checking open files/processes; running
  apps were not stopped or replaced. Native access was rechecked: the Mac is
  still locked and cannot be automatically unlocked. This does not certify the
  managed-preference probe in a real signed/restricted or destination SSH context.

- Fixed macOS system defaults are now screened for storage overrides on both
  Macs: `/etc/codex/config.toml` and `/etc/codex/managed_config.toml`. The reader
  verifies `/etc` against its canonical directory, rejects configuration links,
  special/oversized files and account-identity hardlinks, and retains bounded
  parsing and private-free errors. Checks run before source inventory, copy and
  freezing, and before destination staging/replacement; system files are never
  copied or changed. Independent `public_release_review` accepted the code and
  documentation and passed all 13 disposable system tests. These include late
  source/destination overrides retaining original destination data and staging,
  with replacement blocked before backup. The full suite passed 509 of 516
  tests with seven filesystem skips; ten signup tests, Swift typecheck and diff
  checks passed. Suite notarization results are mocked, not Apple approval.
  MDM preferences, cloud-managed requirements, role references and real managed
  Mac acceptance remain open. A separate read-only Foundation probe found
  neither documented managed-preference key in this account; it printed only
  presence booleans, not values. That observation is not integrated detection
  and does not certify the destination, cloud policy or absence of management.
  Clean source `451cdb5a85059a9cdeb6d65f11c26a4b578bc482` produced a local-only,
  unsigned arm64 build. Eight of nine actual packaged-engine startup/CLI/browser
  checks passed, with one case-sensitive-filename skip. ZIP SHA-256:
  `107e1f97eb687bf1a2841fdadf44475cb2113f56cf73cd794c53bf0ab8d64d45`.
  Hosted run 33884928778 passed on Python 3.9 and 3.12. The superseded inactive engineering
  build was moved recoverably to Trash; running apps were not stopped or replaced.

- Destination retained ancestor configuration is now screened at inspection
  and again before backup/replacement. The bounded check covers in-home parents
  above selected roots, not unrelated projects or settings inside replaced
  folders. Remote ancestor chains reject links/non-directories before config
  reads, and both ancestor readers and staged user-config readers protect the
  actual destination identity-file inodes. A failed initial user-config check
  cannot be masked by a later successful ancestor check. Independent reviewer
  `public_release_review` accepted the code, tests and scoped documentation,
  independently passing 56 focused tests. All 12 destination-scope tests passed,
  including real generated preflight execution and local rsync/APFS fixtures
  preserving original destination data and staging after a late override.
  The full local suite passed 495 of 502 tests with seven filesystem skips;
  the final preflight regression passed separately afterward. Ten signup tests,
  Swift typecheck and diff checks passed. System/managed settings and arbitrary
  role references remain engineering gates; this is not effective-config or
  real cross-Mac certification.
  Clean source `364303255c0daebf149476bdc222ee1b8072061c` produced a local-only,
  unsigned arm64 app. Eight of nine actual bundled-engine checks passed with
  one case-sensitive-filename skip; these are packaged startup/CLI/browser
  checks, not the missing two-Mac acceptance. ZIP SHA-256:
  `4f3dd3c7bec4219e2ea89c6c13ef670e44e1cf62b50c122a8acec3c2bec08a58`.
  Its hosted run 33884310112 passed on Python 3.9 and 3.12. The superseded inactive engineering
  build was moved recoverably to Trash; running user apps were left intact.

- Source project configuration now receives conservative storage-override
  screening in selected descendants, managed worktrees and in-home ancestor
  layers before inventory, copy/resume and source freezing. A disposable
  regression first proved an unsupported project `sqlite_home` could pass
  inventory; it now stops before copying or replacing destination data.
  Readers protect the actual source account's identity-file inodes, retain
  cancellation and bound configuration layers. Explicit root links remain
  rejected; ordinary parent aliases are resolved before containment checks.
  Independent `public_release_review` accepted the correction and passed 58
  focused tests. The full local suite passed 484 of 491 tests with seven
  filesystem skips; the final actual-engine project-override assertion passed
  separately. Ten signup tests, Swift typecheck and diff checks passed.
  This is source-side lexical screening, not effective-config certification:
  destination project/ancestor layers, system/managed settings, arbitrary role
  references and other processes' overrides remain open scope gates. The suite's
  signing/notarization outputs are mocked fixtures, not Apple certification.
  Clean source `e287402ac80ba1fa0735694740bb9e562e9d1212` produced an unsigned,
  local-only arm64 app. Eight of nine actual bundled-engine checks passed,
  with one case-sensitive-filename skip. The actual executable also rejects
  the selected-project storage override without exposing its value or changing
  fixture content. ZIP SHA-256:
  `ea246e45ecffdfa9d98c83abb51aa02f3a32c3b14bad4f7968c4b184c2ac65e5`.
  The previous inactive engineering build was moved recoverably to Trash;
  the two running user apps were not stopped or replaced. Hosted run
  33883734376 subsequently passed on Python 3.9 and 3.12.

- Source availability now screens the macOS `SF_DATALESS` flag before selected
  content reads and directory enumeration, including configuration profiles,
  Git pointers, transcripts and materialized skill-link targets. Copy/resume
  and source freezing rescreen. Excluded runtime data and preserved link targets
  are not traversed by this guard, and ordinary sparse files remain supported.
  Twelve synthetic-metadata tests passed, including no content/process/copy
  calls after rejection and retention of the existing destination and staging.
  Independent `public_release_review` found a mixed-case configuration filename
  gap, verified the correction and accepted the code and scoped instructions
  after 59 focused tests. The local full run passed 472 of 479 tests with seven
  filesystem skips; expanded mixed-case cases passed separately after the fix.
  Ten signup tests, Swift typecheck and diff checks also passed. This proves
  observed-flag screening, not actual provider behavior, an eviction-proof
  snapshot, destination backup availability or Apple certification.
  Clean source `708a1db` built a local-only unsigned arm64 app. Eight of nine
  actual bundled-engine checks passed, with one case-sensitive-filename skip.
  ZIP SHA-256:
  `070bc4283bc73ac1aa454aa13f87e54bdcfbd714f2c1bba212c471994b9a9f70`.
  These package checks are not cloud-provider tests. Superseded inactive
  engineering builds were moved recoverably to Trash; running user apps were
  left untouched. Hosted run 33881789542 is pending at this checkpoint.
  Follow-up: that exact run passed both Python 3.9 and 3.12. The source
  availability checkpoint is hosted-tested; real provider behavior and
  clean/cross-Mac acceptance remain separate gates.

- Discovered Git scope now triggers an early source/destination runtime check
  before staging, using the existing sandbox probe with empty repository/read
  scopes. It validates destination identity first and never reads repositories
  for this startup check. Missing/unsupported Git is a preflight failure, not a
  surprise after a large transfer. If the source baseline later becomes
  unavailable, finalization stops before replacement, keeps staging and names
  the actual retry path: Resume, then Finalize. Older installed null-baseline
  records still receive a read-only unavailable result rather than a recreated
  baseline. Skills-only repair and no-Git scope remain independent.
  The local full suite passed 459 of 466 tests, with seven filesystem skips;
  the subsequently added guarded-retry regression passed separately.
  Independent `public_release_review` accepted the current diff after 29
  readiness/integration tests with ResourceWarning treated as errors and an
  independent pass of that final retry regression. The bundled setup guide now
  distinguishes pre-install retries from post-install Check Git and recovery.
  No new rendered layout or real second-Mac acceptance is claimed for this slice.
  Clean source `62bbb6d` produced a local-only unsigned arm64 engineering app;
  eight of nine actual bundled-engine tests passed, with the case-sensitive-name
  fixture skipped on this volume. ZIP SHA-256:
  `2800d961533cb20569c39286e7c1ae9beebb618f962dc9d4d0072a1c461de1b9`.
  No running user app was replaced. This is not Apple signing, notarization or
  clean second-Mac acceptance.
  Hosted run 33880934861 on that source passed both Python 3.9 and 3.12;
  the hosted suite ran 467 tests with seven filesystem skips.

- Full finalization now durably saves an installation-bound source Git baseline
  and runs separate destination Git checks after home-path verification. The
  dashboard has collapsed Check Git/Stop Git check controls, read-only retry and
  distinct unavailable/changed/source-issue/cancelled results. Saved installation
  evidence blocks Resume-copy after installation; interruption cannot silently
  trigger a replacement or rollback. The destination check uses the existing
  lock read-only/shared and rejects active writers and pending transactions.
  Private baseline hashes do not leave public status/preflight JSON or support
  reports; the diagnostic event stream includes only allowlisted Git states.
  The local suite passed 446 of 453 tests, with seven filesystem skips; ten
  signup tests, Swift typecheck and diff checks also passed. Disposable actual
  rsync/APFS installation fixtures cover source Git taken offline, destination
  edits, unavailable Git, source issues, bound-receipt mismatch, pending/active
  locks and cancellation/restart without recopying. Independent review found
  and prompted fixes for a shutdown handoff race, CLI baseline disclosure and
  keyboard-focus loss across the path/Git check. This is not yet clean
  second-Mac or native/VoiceOver acceptance. Hosted CI run 33878246468 exposed
  16 primitive bootstrap failures on its Mac toolchain; diagnostic runtime
  evidence is being collected without relaxing the sandbox or skipping tests.
  Reviewer `public_release_review` accepted the final bounded integration,
  independently passing 53 focused tests and checking desktop/320px rendering,
  slow path-to-Git transitions, Stop, keyboard focus recovery and wrapping.
  A subsequent focused linked-worktree installation test also passed: with the
  entire disposable old home offline, missing historical paths need review;
  a fixture-only compatibility alias produces two matching Git locations.
  This extra test was added after the 453-test full run. No real user workspace,
  SSH destination, system alias or running app was changed.
  The final clean `2ca8f27` full run passed 447 of 454 tests, with the same seven
  skips. That source produced a local-only unsigned arm64 bundle; eight of nine
  actual bundled-engine tests passed, with the case-sensitive-name fixture
  skipped on this volume. ZIP SHA-256:
  `becb312afbe3c69a354261a9e4d544c30b951010eb08ba8fa4d8113ef49e78f7`.
  The superseded inactive engineering build was moved recoverably to Trash;
  the two user-running apps were not stopped or replaced.

  Hosted run 33879706844 identified the primitive startup cause: its canonical
  Xcode Git executable belongs to runner UID 501, while the product requires
  root ownership. CI now provisions only that exact regular, canonical,
  non-group/world-writable, Apple-signature-verified executable on its
  disposable runner. No product ownership/sandbox guard was relaxed. Customer
  user-owned/custom toolchains remain explicitly unavailable for this probe;
  changing their permissions to bypass checks is not recommended. Hosted run
  33880262265 on source `923b987` subsequently passed both Python 3.9 and 3.12;
  its 455-test suite had seven filesystem skips. This resolves that CI
  provisioning failure, not actual second-Mac or native/VoiceOver acceptance.

- An internal sandboxed Git-probe primitive now checks explicit repository
  locations, HEAD, refs, index/status and local objects without granting Git
  writes, network or subprocess helpers. Independent `public_release_review`
  accepted it after reproducing and verifying fixes for a protected `.SSH`
  alias, a child deadline bypass after pipe EOF and launcher environment/cleanup
  gaps. All 22 focused Git-probe tests passed; independent review reran 19 plus
  the final three additional filter/config fixtures. The broader local run
  passed 423 of 430 tests, with seven filesystem skips, before those final three
  test-only additions; 10 signup tests and Swift typecheck also passed.
  A disposable linked-worktree copy matches source Git fingerprints after the
  original home is taken offline and a fixture-only compatibility alias is
  added. Both trees remain byte-identical. That primitive checkpoint preceded
  the integration described above; actual packaged cross-Mac acceptance remains
  required. See the exact
  [Git verification integration plan](git-verification-plan.md).

- Nested filename screening now rejects conservative case-fold/decomposition
  collisions and invalid UTF-8 names before copying and during the source tree
  freeze before replacement. Full inventory/copy includes managed worktrees;
  skill discovery and selective repair screen their nested names too. No source
  files are renamed or changed. Errors do not echo filenames or file contents.
  Existing destination recovery keeps its original byte-based digest contract
  and can still verify case-sensitive backups containing such names.
  Thirteen filename tests and nine actual-engine desktop tests passed with no
  skips on a disposable 128 MiB case-sensitive APFS image, including real
  distinct source filenames, unchanged rejected data, inventory rejection,
  stopping before an installation RPC and rescreening before resume copies.
  Synthetic cases also cover canonical Unicode equivalents, case-fold
  expansions, invalid UTF-8 and a nested conflicting directory listing.
  Independent `public_release_review` accepted the bounded diff, verified
  unchanged digest bytes, and passed 14 filename/CLI tests on the case-sensitive
  image without skips. The full local suite passed 404 of 411 tests, with seven
  filesystem-dependent skips; the case-sensitive run covers six of those skips.
  Ten signup tests, Swift typecheck and diff checks also passed. Notarization
  output produced by the release unit tests is mocked, not Apple certification.
  Clean source `4dfe27a` produced a local-only unsigned arm64 app; all nine
  actual bundled-engine desktop tests passed on the case-sensitive image with
  system-only PATH and no Python environment dependencies. The inventory
  subprocess rejects real `README`/`readme` collisions without changing either
  file. ZIP SHA-256:
  `bede747375e77954615a642fa85c4c64495d03f80ee3fdccb457abc444d1c0dd`.
  No real user workspace, SSH destination or running app was modified.
  This remains conservative screening, not an exact filesystem Unicode model,
  an atomic source snapshot or a real cross-Mac acceptance test.

- Full migration now screens visible account `CODEX_HOME` and bounded user
  config/profile files for `sqlite_home` before inventory/copy and source
  verification. Destination and staged user configuration are screened inside
  the guarded installation path before backup/replacement. Unsupported or
  unverifiable scope stops without removing the setting or transferring an
  unknown custom root. Scanner output never includes config values; known
  credential aliases, special files, scan/read failures and oversized files
  fail closed. Source cancellation reaps its child. Independent
  `public_release_review` reproduced and verified fixes for a same-home case
  alias bypass and directory-read failures being mistaken for EOF; 51 focused
  tests passed at review. Real disposable transaction tests preserve old data
  and staging when destination/staged overrides are detected. Official OpenAI
  documentation informed the distinction between storage roots and ordinary
  configuration profiles; see the [scope guide](../README.md#custom-storage-and-configuration-profiles).
  This is lexical user-layer screening, not effective-config discovery or TOML
  validation. Project/managed layers, other processes' environments, custom
  roots and actual cross-Mac acceptance remain open.
  Final local checks passed 397 Python tests (396 passed, one filesystem skip),
  10 signup tests, Swift typecheck and diff checks. Eight source-engine desktop
  tests also passed after adding real-process inventory rejection for a profile
  storage override, with empty stdout, no private value in errors and unchanged
  fixture configuration.
  Clean source `f2cb823` built an unsigned arm64 engineering app and passed all
  eight bundled-engine tests, including profile-override rejection through its
  real inventory command. Packaging verified the ad-hoc signature. ZIP SHA-256:
  `34122de41d79a0917aa8084dafcdc74bbe74f62f10acafc186bc7bfaaabd7e75`.
  No real account data or SSH migration was used; no running app was replaced.
  This does not certify Apple signing or a clean second-Mac migration.

- Folder-selection guards now compare conservative case/Unicode path identities
  without rewriting the selected I/O paths. Config rejects protected/control
  aliases, resolved protected-storage targets, ambiguous workspace roots and
  unsafe staging/backup names. The relocated default state directory is resolved
  before confinement/protection checks; independent review reproduced and
  verified a `.local` alias bypass. Skill discovery rejects case-only name
  conflicts and protected login/SSH aliases; the two known Codex identity files
  also receive inode-only hard-link protection, never content reads. HTTP setup
  tests prove rejection before attaching/saving a migration or making SSH calls.
  Independent `public_release_review` accepted the code and scoped documentation
  after 73 focused tests. Main verification passed 381 Python tests (380 passed,
  one filesystem skip), 10 signup tests, Swift typecheck and diff checks. The
  eight source-engine desktop tests also passed with explicit HTTP rejection
  assertions for protected path aliases. These are selection-level and known-identity guards,
  not general secret detection, nested filename collision certification or
  custom `CODEX_HOME` support. Real cross-filesystem acceptance remains open.
  Clean source `b2c4569` built an unsigned arm64 engineering app; all eight
  bundled-engine tests passed, including rejecting protected path aliases over
  real loopback HTTP before saving/attaching setup. Packaging verified the
  ad-hoc signature. ZIP SHA-256:
  `ba35a840315e28b8977f260fe52413167d1b8431caf556b275c089f764af05bb`.
  No running user app was replaced, no real SSH migration ran, and this is not
  Apple notarization or clean-second-Mac acceptance.

- Home-path compatibility now has a separate read-only check before transfer
  and after installation. Missing ordinary `/Users/name` paths receive an
  optional, manually invoked administrator command. The command repeats owner,
  local-account and path checks and uses an exact symlink syscall, not `ln`'s
  directory-destination behavior. Existing entries and account conflicts are
  never replaced; unsupported/custom homes receive no privileged command.
  Full installation evidence is saved before the post-install check. Missing,
  conflicting or unverified paths leave the app in needs-attention state,
  without losing that receipt or blindly repeating installation. A recheck
  can complete only with matching home paths and a valid bound installation
  receipt. Skills-only repairs do not use this whole-home mapping flow.
  The reviewer caught a shutdown/late-publication race; cancellation now reaches
  the tracked child, joins the worker, and suppresses late results. Tests cover
  actual disposable symlinks, conflicting entries, late-entry races, Unicode,
  private/malformed account evidence, receipt retention and real child reaping.
  A read-only check using this Mac's actual account provider also passed; it
  emitted only the fixed result, not account records. Desktop/320px UI review
  verified readable text, disclosure/keyboard behavior, exact command copying,
  and focus. Independent `public_release_review` accepted the final bounded
  code, UI and documentation after 58 focused tests, including a fresh keyboard
  check of the disclosure shortcut. Main verification passed 371 Python tests
  (370 passed, one filesystem skip), 10 signup tests, Swift typecheck and diff
  checks; a final 17-test skills/path regression check also passed. Playwright
  fixture review covered desktop/320px wrapping and keyboard focus. Review
  browsers and disposable servers were closed. Diagnostic events include only
  allowlisted path statuses, never the command or local-account records.
  These are not a privileged real-account repair or cross-Mac usability proof.
  Clean source `1f1c3c8` also built an unsigned arm64 engineering app and passed
  all eight bundled-engine regression tests. Packaging verified its ad-hoc
  signature; no Apple signing/notarization or privileged path creation was
  performed. ZIP SHA-256:
  `9c469045f5eaa46faf11e83dc03f67053c9ecb0ab941d44ebf0b7c06e4aa5c6e`.
  No running user app was replaced.

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
  Clean source `17ff1ec` built an unsigned arm64 engineering app and passed all
  eight bundled-engine tests, including the guided-control HTML and missing
  recovery-proof rejection before any SSH request. Packaging verified its
  ad-hoc signature. ZIP SHA-256:
  `c785735f713c926583d7cce48e183da43649dce9feb0b93573eb5428dce23dee`.
  The actual restore fixtures used the source engine; these bundled checks do
  not claim a packaged restoration over SSH. No running user app was replaced.

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

- Complete the remaining safety/configuration acceptance in the
  [failure-mode matrix](failure-mode-matrix.md). Wrong-machine rejection,
  destination locking, guided recovery and home-path conflict guards now have
  local implementation evidence, but real cross-Mac/hardware failure acceptance
  and unsupported-configuration detection remain engineering gates, not merely
  Apple/account dependencies.

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
