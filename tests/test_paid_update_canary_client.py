"""Safety checks for the disposable private paid-updater canary client."""

import importlib.util
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
