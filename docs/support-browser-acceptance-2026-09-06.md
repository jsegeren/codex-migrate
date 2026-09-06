# Browser Help acceptance — September 6, 2026

Tested the shipped dashboard and shared Help script at source `a6ba8de`, using
real Chromium through Playwright CLI on macOS 26.5.1 / arm64. No production
code changed in this pass.

## Fixture and scope

Started the existing disposable recovery fixture:

```sh
PYTHONPATH=src:tests python3 tests/manual_recovery_browser.py
```

It uses invented source/destination contents, a public fixture-only control
token, loopback HTTP and the production dashboard/diagnostic handlers. The
fixture substitutes transport and process inspection; it does not touch an
active user workspace or establish real cross-Mac acceptance. Only Help was
operated in this pass; no recovery or migration action was started.

## Observed checks

- At 320×900, Tab/Enter activated the header Help link. Subsequent Tab presses
  reached the email address and Prepare diagnostic report in order.
- Enter prepared a real diagnostic response. Focus moved to the labelled,
  read-only report field; its computed font size was 15px. Tab/Enter then
  downloaded `codex-migrate-diagnostics.json` and kept focus on Save report.
- The downloaded JSON contained three structured phase/status events. The
  synthetic source/destination path, SSH username/host and control token were
  absent. This is a bounded fixture check, complemented by the privacy tests
  below, not proof that every conceivable sensitive input is covered.
- At 1280×900, repeating preparation and keyboard download produced bytes
  exactly equal to the report shown for review. Both email links used `mailto:`;
  no email was sent or automatic diagnostic upload performed.
- At both widths, document width did not exceed the viewport. Rendered Help
  screenshots were inspected: controls wrapped, report text stayed within its
  field, and the keyboard focus outline remained visible. The narrow view
  required normal vertical scrolling.
- A browser-intercepted HTTP 503 for only `/api/support-report` hid the old
  preview, reenabled Prepare, returned focus to it and offered email support.
  Removing the interception allowed successful preparation again.
- A separately intercepted HTTP 200 with malformed JSON followed the same
  usable failure path rather than leaving a disabled control or stale report.
- A direct request without the control token returned HTTP 403.

The response interceptions are synthetic failure cases. They do not establish
behavior under physical network loss, browser crashes or OS download denial.
An initial Playwright `run-code` invocation used the wrong wrapper syntax and
did not execute; the corrected invocation and downloaded-byte comparison above
completed successfully.

## Automated checks

```sh
PYTHONPATH=src:tests python3 -m unittest test_support test_dashboard -q
node --test tests/support-ui.test.js
```

32 Python tests and 6 JavaScript tests passed, with no failures or skips.
The JavaScript checks include success, HTTP failure and malformed JSON, both
with retained focus and with the user moving focus elsewhere while waiting.

## Remaining boundary

This closes the dashboard Help keyboard/narrow-layout/diagnostic-download check
for this source revision. It is not native VoiceOver acceptance, a complete
WCAG audit, actual email-client attachment/delivery acceptance, or a check of
every setup/pairing surface. Repeat against the exact packaged release and
complete the separate clean-Mac and assistive-technology gates before launch.
