# Recovery next-action acceptance — September 5, 2026

## Change and boundary

The dashboard now places a recovery link immediately after the main status for
interrupted installation and recorded recovery work. Its labels distinguish
review, an active check, restoration progress and restored-file review. The
link opens the existing recovery disclosure and focuses its summary. It does
not initiate recovery or bypass the separate backup check, exact-scope
confirmation, apply guard or engine verification. Ordinary staging interruptions
retain their existing resume flow; active ordinary installation does not suggest
recovery.

This receipt covers the source change accompanying this document, not a newly
packaged or signed release. Production checkout remains closed.

## Reproducible fixture

Run on macOS as a non-root user:

```sh
PYTHONPATH=src:tests python3 tests/manual_recovery_browser.py
```

The script reuses the existing disposable APFS restore fixtures. It creates
fresh temporary source/destination folders, interrupts a fixture installation,
and adds distinct newer destination work. Production HTTP handlers, dashboard
JavaScript, restoration and reconciliation are used. SSH is replaced by a local
test transport; only the process snapshot is substituted so the developer's
running Codex is neither stopped nor treated as a fixture writer. All identity
contents are dummy test values. Its public fixture token is not a real migration
credential, and its server binds only to loopback. Exit cleans up only those
newly created temporary test directories.

The first fixture run lacked the restore-specific process-snapshot substitution
before argument quoting. Restoration correctly failed closed. That fixture issue
was fixed, and acceptance was repeated with fresh temporary data. No production
process or ownership guard was weakened.

## Observed browser journey

Real Chromium through Playwright CLI, desktop 1280×900 and narrow 320×900:

1. Interrupted-install state displayed “Review recovery options” beside status.
2. Keyboard Enter opened the disclosure, scrolled to it and focused its summary.
3. Tab/Enter started the read-only Check recovery operation. Focus moved to its
   status during checking and returned to Check recovery on completion.
4. Restore was disabled until backup verification passed.
5. Tab/Enter opened the confirmation naming the two exact synthetic paths.
   Dismissing it left the state interrupted and the fixture un-restored.
6. Reopening and accepting that confirmation performed actual restoration.
7. The UI reached `interrupted / restored`, with “Review restored files” and an
   explicit statement that restoration does not complete the migration.
8. Independent fixture assertions verified selected original destination files,
   selected newer files in preserved slots, the original backup entry and source
   entry, retained dummy destination identity, and absence of a pending
   transaction. The engine also reconciled its restoration evidence.
9. Both viewport widths had no horizontal document overflow. Full-page renders
   were visually inspected. No native VoiceOver or full WCAG claim follows.

Screenshots were saved locally under ignored `output/playwright/recovery-320.png`
and `output/playwright/recovery-1280.png`. They contain only synthetic test data
and temporary paths, and are not marketing screenshots.

## Automated checks

- `node --test tests/dashboard-ui.test.js`: 4 passed, including a 14-state
  recovery visibility/label matrix and disclosure navigation behavior.
- `PYTHONPATH=src:tests python3 -m unittest test_guided_recovery test_dashboard`:
  28 passed, covering recovery lifecycle and HTTP authorization/confirmation.
- `npm test`: 189 passed, 1 skipped, 0 failed.

## Still required

Physical disconnect/reconnect, complete buyer setup, authentic Codex
conversation reopening, full packaged-installer interruption, native VoiceOver,
and the signed clean-Mac purchase/download/launch gate remain open. This fixture
does not replace any of them.
