import unittest

from codex_migrate.security import is_protected_name, redact


class SecurityTests(unittest.TestCase):
    def test_protected_names(self):
        self.assertTrue(is_protected_name(".codex/auth.json"))
        self.assertTrue(is_protected_name(".ssh/id_ed25519"))
        self.assertFalse(is_protected_name(".codex/config.toml"))

    def test_redacts_known_secret_shapes_and_private_paths(self):
        message = "token=abc123 ghp_example /Users/person/.ssh/key"
        result = redact(message, ["/Users/person/.ssh/key"])
        self.assertNotIn("abc123", result)
        self.assertNotIn("ghp_example", result)
        self.assertNotIn("/Users/person/.ssh/key", result)


if __name__ == "__main__":
    unittest.main()
