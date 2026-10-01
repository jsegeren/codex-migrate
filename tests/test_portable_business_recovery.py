"""Safety checks for the disposable independent-Mac recovery drill."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from codex_migrate.errors import MigrationError


SCRIPT = Path(__file__).with_name("portable_business_recovery.py")
SPEC = importlib.util.spec_from_file_location("portable_business_recovery", SCRIPT)
PORTABILITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PORTABILITY)
KEY_ID = "77777777-7777-4777-8777-777777777777"


class PortableBusinessRecoverySafetyTests(unittest.TestCase):
    def test_failed_company_import_still_removes_any_partly_saved_test_key(self):
        for failure in (SimpleNamespace(returncode=1, stdout=b"", stderr=b""),
                        subprocess.TimeoutExpired("business-key-import", 30)):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as temp:
                bundle = Path(temp) / "bundle"
                vault = bundle / "vault"
                vault.mkdir(parents=True)
                (vault / "vault.json").write_text(json.dumps({"key_id": KEY_ID}))
                (bundle / "company-credential.json").write_text(
                    json.dumps({"envelope": {"role": "company"}}))
                helper = Path(temp) / "synthetic-helper"
                with patch.object(PORTABILITY, "verify_snapshot",
                                  side_effect=MigrationError("key absent")), \
                     patch.object(PORTABILITY.subprocess, "run",
                                  side_effect=failure if isinstance(failure, Exception) else None,
                                  return_value=None if isinstance(failure, Exception) else failure), \
                     patch.object(PORTABILITY, "helper_call", return_value={}) as cleanup:
                    with self.assertRaises((AssertionError, subprocess.TimeoutExpired)):
                        PORTABILITY.consume(bundle, helper)
                cleanup.assert_called_once_with(helper, "delete-key", "--key-id", KEY_ID)


if __name__ == "__main__":
    unittest.main()
