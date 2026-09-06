# Folder-selection review boundary — September 5, 2026

## Reproduced defects and fix

The setup page allowed **Review migration** while a folder picker or suggestions
request was pending. Its late response could change the folder list after the
review count had been rendered. Disabling only the two selection buttons did
not protect that boundary. The same interaction left a prior error visible
after success and could drop keyboard focus when the triggering button was
disabled.

The shipped interaction now disables Review until selection finishes, ignores
duplicate selection requests, clears stale errors, and reports pending selection
in the existing live status. It restores focus to the originating button only
if the user has not moved elsewhere and that button is still visible. Failure
keeps existing folder paths and re-enables retry. No backend authorization,
copy scope, backup requirement or migration action changed.

The full-mode option was shortened to **Full Codex migration** because its
previous label was visibly clipped at 320px. The explicit explanation that only
selected workspace folders are included remains visible and unchanged.

## Verification

- Five of the initial seven focused tests failed against the original source;
  all eight final tests pass, including the compact-label regression.
- Real Chromium at 1280×900 exercised keyboard picker activation, pending
  Review exclusion, a delayed synthetic permission-denial response, and useful
  restored focus. A subsequent 320×800 retry cleared the old error, retained the
  selected scope, and displayed the correct count on the review step.
- A delayed suggestions response did not steal focus after the user moved to
  Help. Desktop and 320px screenshots were inspected; the final narrow view
  showed the full shortened option, a visible keyboard focus ring, minimum
  visible explanatory/control text of 15px, and no horizontal overflow.
- `node --test --test-reporter=spec tests/*.test.js`: 211 tests, 210 passed,
  one skipped. `PYTHONPATH=src python3 -m unittest discover -s tests -p
  'test_*.py' -q`: 596 tests, 584 passed, 12 skipped, no failures. Signed-build
  output in those unit tests is mocked, not an Apple signing receipt.
- `git diff --check` passed.

The repeatable local fixture is `tests/manual_folder_selection_browser.py`.
It serves production HTML and delayed invented folder responses; its first
picker request fails. It cannot configure or run a migration. No real folder
picker, macOS permission decision, SSH, authentic Codex data or receiving Mac
participated. This is not native VoiceOver, WCAG conformance, physical
interruption, or full clean-Mac acceptance. The fixture and isolated browser
were stopped after inspection; disposable screenshots and snapshots were removed.

The retained `286f6b9` unsigned package predates this source change. A new clean
package must include it before final device/signing acceptance. No running
test-account helper was replaced and no app download was published in this pass.
