import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from codex_migrate.errors import MigrationError
from codex_migrate import vault_hosted_subscription_client as CLIENT


ORIGIN = "https://codex-migrate-abc-joshuas-projects-d3a5c48d.vercel.app"
DEVICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TOKEN = "hv1_" + "a" * 43
URL = "https://checkout.stripe.com/c/pay/cs_test_fixture#test-only"


class Response(io.BytesIO):
    def __init__(self, value, *, status=200, headers=None, raw=None):
        super().__init__(raw if raw is not None else json.dumps(value).encode())
        self.status = status
        self.headers = {"Content-Type": "application/json", **(headers or {})}


class SubscriptionClientTests(unittest.TestCase):
    def setUp(self):
        self.client = CLIENT.HostedSubscriptionClient(ORIGIN)
        self.credential = patch.object(CLIENT.HostedEnrollmentClient, "_credential",
                                       return_value=TOKEN).start()
        self.addCleanup(patch.stopall)
        self.opener = self.client._opener = Mock()

    def reply(self, value=None, **options):
        self.opener.open.return_value = Response(
            {"status": "subscribed", "testMode": True} if value is None else value, **options)

    def test_native_begin_only_sends_device_and_action(self):
        expected = {"status": "checkout_required", "testMode": True, "checkoutUrl": URL}
        self.reply(expected)
        self.assertEqual(self.client.begin(DEVICE, crypto_helper="/synthetic/helper", apply=True), expected)
        self.credential.assert_called_once_with(DEVICE, "/synthetic/helper")
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, ORIGIN + "/api/hosted-subscription")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"action": "begin", "deviceId": DEVICE})
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertEqual(int(request.get_header("Content-length")), len(request.data))

    def test_status_does_not_begin_a_new_checkout(self):
        for status in ("subscribed", "not_entitled", "needs_support", "checkout_required"):
            with self.subTest(status=status):
                value = {"status": status, "testMode": True}
                if status == "checkout_required":
                    value["checkoutUrl"] = URL
                self.reply(value)
                self.assertEqual(self.client.status(DEVICE, apply=True), value)
                self.assertEqual(json.loads(self.opener.open.call_args.args[0].data)["action"], "status")

    def test_both_actions_refuse_without_apply_before_keychain_or_network(self):
        for method in (self.client.begin, self.client.status):
            for value in (False, None, 1):
                with self.assertRaises(MigrationError):
                    method(DEVICE, apply=value)
        self.credential.assert_not_called()
        self.opener.open.assert_not_called()

    def test_invalid_device_refused_before_credential_access(self):
        for value in (None, 1, TOKEN, DEVICE.upper(), DEVICE + "\n"):
            with self.assertRaises(MigrationError):
                self.client.begin(value, apply=True)
        self.credential.assert_not_called()
        self.opener.open.assert_not_called()

    def test_live_foreign_and_unsafe_origins_are_refused(self):
        for origin in ("https://codexbackup.segeren.com", "https://evil.example",
                       "http://127.0.0.1:1234", ORIGIN + "/path", ORIGIN + "?token=private",
                       "https://user:pass@codex-migrate-abc-joshuas-projects-d3a5c48d.vercel.app"):
            with self.assertRaises((MigrationError, ValueError)):
                CLIENT.HostedSubscriptionClient(origin)

    def test_timeouts_are_bounded_and_boolean_is_not_a_number(self):
        for timeout in (True, 0, -1, 121, None, float("nan")):
            with self.assertRaises(MigrationError):
                CLIENT.HostedSubscriptionClient(ORIGIN, timeout=timeout)

    def test_arbitrary_fields_and_live_or_unknown_statuses_are_refused(self):
        values = [None, [], {"status": "subscribed", "testMode": False},
                  {"status": "subscribed", "testMode": 1},
                  {"status": "subscribed", "testMode": True, "token": TOKEN},
                  {"status": "protected", "testMode": True},
                  {"status": "checkout_required", "testMode": True},
                  {"status": ["subscribed"], "testMode": True}]
        for value in values:
            with self.subTest(value_type=type(value).__name__):
                self.reply(value, raw=json.dumps(value).encode())
                with self.assertRaises(MigrationError) as caught:
                    self.client.begin(DEVICE, apply=True)
                self.assertEqual(str(caught.exception), CLIENT._FAILED)

    def test_checkout_destination_and_test_session_are_exact(self):
        urls = ["http://checkout.stripe.com/c/pay/cs_test_fixture",
                "https://checkout.stripe.com.evil.example/c/pay/cs_test_fixture",
                "https://user:password@checkout.stripe.com/c/pay/cs_test_fixture",
                "https://checkout.stripe.com:443/c/pay/cs_test_fixture",
                "https://checkout.stripe.com/c/pay/cs_live_fixture",
                "https://checkout.stripe.com/c/pay/../cs_test_fixture",
                "https://checkout.stripe.com/c/pay/%63s_test_fixture",
                URL + "\n", URL.replace("#", "\\"), "https://checkout.stripe.com/other", 1,
                "https://checkout.stripe.com/c/pay/cs_test_" + "a" * 12_001]
        for url in urls:
            self.reply({"status": "checkout_required", "testMode": True, "checkoutUrl": url})
            with self.assertRaises(MigrationError):
                self.client.begin(DEVICE, apply=True)

    def test_bad_http_json_size_and_duplicate_fields_are_refused(self):
        options = [{"status": 302}, {"status": 403},
                   {"headers": {"Content-Type": "text/html"}},
                   {"headers": {"Content-Encoding": "gzip"}},
                   {"raw": b"{"}, {"raw": b"a" * (CLIENT._LIMIT + 1)},
                   {"raw": b'{"status":"subscribed","status":"not_entitled","testMode":true}'}]
        for option in options:
            self.reply(**option)
            with self.assertRaises(MigrationError):
                self.client.begin(DEVICE, apply=True)

    def test_uncertain_send_is_not_retried_and_diagnostics_are_redacted(self):
        for error in (URLError(TOKEN + URL), OSError(TOKEN),
                      HTTPError(ORIGIN + "/private", 503, TOKEN, {}, None)):
            self.opener.open.reset_mock()
            self.opener.open.side_effect = error
            with self.assertRaises(MigrationError) as caught:
                self.client.begin(DEVICE, apply=True)
            self.assertEqual(str(caught.exception), CLIENT._FAILED)
            self.assertTrue(caught.exception.__suppress_context__)
            self.opener.open.assert_called_once()

    def test_native_diagnostics_are_not_forwarded(self):
        self.credential.side_effect = MigrationError(TOKEN)
        with self.assertRaises(MigrationError) as caught:
            self.client.begin(DEVICE, apply=True)
        self.assertEqual(str(caught.exception), CLIENT._FAILED)
        self.opener.open.assert_not_called()

    def test_real_loopback_post_and_redirect_refusal(self):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                calls.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                if self.server.redirect:
                    self.send_response(302)
                    self.send_header("Location", "https://evil.example")
                    self.end_headers()
                    return
                raw = b'{"status":"not_entitled","testMode":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.redirect = False
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = CLIENT.HostedSubscriptionClient(
                "http://127.0.0.1:" + str(server.server_port), allow_loopback_http=True)
            self.assertEqual(client.status(DEVICE, apply=True), {"status": "not_entitled", "testMode": True})
            server.redirect = True
            with self.assertRaises(MigrationError):
                client.begin(DEVICE, apply=True)
            self.assertEqual(calls, [("/api/hosted-subscription", {"action": "status", "deviceId": DEVICE}),
                                     ("/api/hosted-subscription", {"action": "begin", "deviceId": DEVICE})])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
