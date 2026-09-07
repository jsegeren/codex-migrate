# Receipt-write failure recovery — September 6, 2026

## Scope and method

Five added tests in `tests/test_transaction_write_failures.py` exercise the
existing full installer, recovery inspection, and explicitly authorized restore
against disposable local APFS fixtures. No personal data, SSH connection,
account settings, payment settings, or packaged runtime changed.

The partial-write cases perform a real eight-byte write, then inject an
undefined write result with ENOSPC at the next loop iteration. The production
write-result guard handles the failure. Two other cases inject failure before
receipt sync and after its exclusive rename but before the durability barrier.
The existing fixture substitutes a closed-Codex process snapshot and synthetic
identity; owner, backup, replacement, and restore operations still execute.

These are fault-injection tests, not actual filesystem exhaustion, hardware
power loss, a packaged two-Mac run, or authentic Codex conversation acceptance.

## Observed outcomes

| Failure boundary | Verified result |
| --- | --- |
| Partial initial pending journal | No replacement; original destination and staging unchanged. Retry succeeded with a different backup, retaining the prior backup and incomplete file. |
| Partial installed receipt | Automatic rollback restored original bytes but correctly reported unconfirmed recovery evidence. Ordinary migration writes remained blocked; explicit recovery succeeded. |
| Partial rollback receipt | No false verified-rollback result. Pending state blocked ordinary writes; explicit recovery succeeded. |
| Receipt sync failure | The incomplete receipt was not treated as success. Explicit recovery succeeded. |
| Failure after installed-receipt rename | A visible `installed` receipt was not sufficient to claim current success after rollback. Pending recovery remained; explicit restoration succeeded. |

Every explicit recovery case first inspected the backup without changing later
work, restored original Codex/workspace bytes, preserved a new post-failure
workspace file in the separate displaced-data directory, retained the original
backup and source, preserved dummy destination identity, wrote the recovery
completion record, and cleared the pending transaction. Partial terminal files
were not deleted to make the test pass.

## Verification

On macOS, Python 3.12.3:

```
PYTHONPATH=src:tests .venv/bin/python -m unittest test_transaction_write_failures test_transactions test_recovery test_restore -q
```

All 63 tests passed in 24.430 seconds, without skips. The five new tests also
passed on system Python 3.9.6 in 3.627 seconds. TemporaryDirectory fixture
cleanup completed normally; no test disk images or long-running processes were
created. No runtime fix was required by these observations.

## Release consequence

This strengthens the demonstrated recovery evidence for ordinary journal and
receipt failures. It does not close actual production-write ENOSPC, physical
disconnect/power-loss, signed clean-Mac launch, real purchase/app delivery, or
authentic cross-Mac application acceptance. The new account-local acceptance
launcher still had no status report before this run; prior synthetic helper
processes are not evidence that it started.
