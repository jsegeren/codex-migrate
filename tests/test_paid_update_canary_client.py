"""Safety checks for the disposable private paid-updater canary client."""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from xml.etree import ElementTree


SCRIPT = Path(__file__).resolve().parents[1] / "ops/paid-update-canary-client.py"
SPEC = importlib.util.spec_from_file_location("paid_update_canary_client", SCRIPT)
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)


class PaidUpdateCanaryClientTests(unittest.TestCase):
    def test_appcast_advertises_exact_unaccepted_dmg_via_first_party_archive(self):
        selected = CANARY.canary()
        root = ElementTree.fromstring(CANARY.appcast_xml(selected))
        item = root.find("channel/item")
        self.assertEqual(item.find("{http://www.andymatuschak.org/xml-namespaces/sparkle}version").text, "17")
        enclosure = item.find("enclosure")
        self.assertEqual(enclosure.get("url"), "https://migrate.segeren.com/api/update-archive")
        self.assertEqual(enclosure.get("length"), str(selected["size"]))
        self.assertEqual(enclosure.get("type"), "application/x-apple-diskimage")
        self.assertEqual(enclosure.get("{http://www.andymatuschak.org/xml-namespaces/sparkle}edSignature"),
                         selected["sparkleSignature"])
        self.assertIs(selected["testingOnly"], True)
        self.assertIs(selected["accepted"], False)

    def test_local_appcast_uses_only_loopback_archive_with_same_signature(self):
        selected = CANARY.canary()
        root = ElementTree.fromstring(CANARY.appcast_xml(
            selected, "http://127.0.0.1:8898/archive"))
        enclosure = root.find("channel/item/enclosure")
        self.assertEqual(enclosure.get("url"), "http://127.0.0.1:8898/archive")
        self.assertEqual(enclosure.get("length"), str(selected["size"]))
        self.assertEqual(enclosure.get("{http://www.andymatuschak.org/xml-namespaces/sparkle}edSignature"),
                         selected["sparkleSignature"])

    def test_only_exact_old_request_hook_can_gain_canary_header(self):
        source = "before\n        " + CANARY.HEADER_HOOK + "\nafter\n"
        modified = CANARY.add_canary_header(source)
        self.assertEqual(modified.count(CANARY.HEADER_HOOK), 1)
        self.assertEqual(modified.count("X-Codex-Migrate-Canary"), 1)
        self.assertIn(CANARY.CANARY_ID, modified)
        self.assertEqual(source.count("X-Codex-Migrate-Canary"), 0)
        with self.assertRaises(ValueError):
            CANARY.add_canary_header("no matching updater delegate")
        with self.assertRaises(ValueError):
            CANARY.add_canary_header(source + source)

    def test_only_exact_old_startup_hook_can_add_one_background_check(self):
        source = "before\n" + CANARY.HELPER_START + "after\n"
        modified = CANARY.add_background_check(source)
        self.assertEqual(modified.count("checkForUpdatesInBackground()"), 1)
        self.assertEqual(modified.count(CANARY.HELPER_START), 1)
        with self.assertRaises(ValueError):
            CANARY.add_background_check("no matching startup hook")
        with self.assertRaises(ValueError):
            CANARY.add_background_check(source + source)
        with self.assertRaises(ValueError):
            CANARY.add_background_check(modified)

    def test_only_exact_old_entitlement_lookup_can_read_piped_test_token(self):
        source = "before\n" + CANARY.TOKEN_LOOKUP + "        return nil\n    }\n"
        modified = CANARY.add_piped_test_token(source)
        self.assertEqual(modified.count("pipedCanaryToken"), 2)
        self.assertIn("FileHandle.standardInput.readDataToEndOfFile()", modified)
        self.assertIn("return nil", modified)  # Original Keychain fallback remains.
        with self.assertRaises(ValueError):
            CANARY.add_piped_test_token("no matching entitlement lookup")
        with self.assertRaises(ValueError):
            CANARY.add_piped_test_token(source + source)
        with self.assertRaises(ValueError):
            CANARY.add_piped_test_token(modified)

    @unittest.skipUnless(shutil.which("xcrun"), "Swift compiler requires macOS")
    def test_piped_test_token_compiles_and_falls_back_without_a_valid_token(self):
        # A disposable stand-in for build 16's lookup: no purchase credential
        # or Keychain item is used by this executable fixture.
        source = ("import Foundation\n"
                  "enum UpdateEntitlement {\n"
                  "    static func token(from value: String) -> String? {\n"
                  "        value.trimmingCharacters(in: .whitespacesAndNewlines) == \"test_fixture\" ? \"test_fixture\" : nil\n"
                  "    }\n"
                  + CANARY.TOKEN_LOOKUP
                  + "        return \"fixture_fallback\"\n"
                    "    }\n"
                    "}\n"
                    "@main struct Fixture {\n"
                    "    static func main() { print(UpdateEntitlement.savedToken() ?? \"missing\") }\n"
                    "}\n")
        with tempfile.TemporaryDirectory(prefix="paid-canary-hook-test-") as directory:
            swift_file = Path(directory) / "Fixture.swift"
            executable = Path(directory) / "Fixture"
            swift_file.write_text(CANARY.add_piped_test_token(source))
            subprocess.run(["xcrun", "swiftc", "-parse-as-library", str(swift_file), "-o", str(executable)],
                           check=True, capture_output=True, text=True)
            for supplied, expected in ((b"test_fixture\n", "test_fixture\n"),
                                       (b"not-a-token\n", "fixture_fallback\n")):
                completed = subprocess.run([str(executable)], input=supplied, capture_output=True, check=True)
                self.assertEqual(completed.stdout.decode(), expected)


if __name__ == "__main__":
    unittest.main()
