"""Dark native client for the reviewed test-mode subscription endpoint.

No live billing, caller-selected price/account, automatic browser launch, or
backup entitlement is created here. The server owns durable checkout attempts.
The existing native helper supplies the device bearer; it stays out of results.
"""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from codex_migrate.errors import MigrationError
from codex_migrate.vault_hosted_enrollment_client import (
    HostedEnrollmentClient, _require_apply,
)
from codex_migrate.vault_hosted_recovery_client import _origin
from codex_migrate.vault_http_store import _NoRedirect


_PREVIEW = re.compile(
    r"https://codex-migrate-[a-z0-9]+-joshuas-projects-d3a5c48d\.vercel\.app\Z")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_CHECKOUT_PATH = re.compile(r"/c/pay/cs_test_[A-Za-z0-9]+\Z")
_LIMIT = 16 * 1024
_FAILED = "Hosted test subscription could not be confirmed. Check its status before retrying checkout."


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate response field")
        value[key] = item
    return value


def _result(value):
    if not isinstance(value, dict) or value.get("testMode") is not True:
        raise ValueError("invalid test subscription result")
    status = value.get("status")
    if status in ("subscribed", "not_entitled", "needs_support"):
        if set(value) != {"status", "testMode"}:
            raise ValueError("invalid test subscription fields")
        return dict(value)
    if status != "checkout_required" or set(value) != {"status", "testMode", "checkoutUrl"}:
        raise ValueError("invalid test subscription fields")
    url = value["checkoutUrl"]
    if (not isinstance(url, str) or len(url) > 12_000 or
            any(ord(character) <= 32 or ord(character) >= 127 for character in url) or
            "\\" in url):
        raise ValueError("invalid checkout URL")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "checkout.stripe.com" or
            not _CHECKOUT_PATH.fullmatch(parsed.path)):
        raise ValueError("invalid checkout destination")
    return dict(value)


class HostedSubscriptionClient:
    """Sandbox-only native begin/status; both require explicit mutation consent.

    Status may enroll a completed checkout on the server, so it is not a
    read-only request. Neither result is a backup or protection receipt.
    Production support and the customer UI remain separate release work.
    """

    def __init__(self, service_origin, *, timeout=30.0, allow_loopback_http=False):
        origin = _origin(service_origin, allow_loopback_http)
        if (not _PREVIEW.fullmatch(origin) and
                not (allow_loopback_http is True and origin.startswith("http://127.0.0.1:"))):
            raise MigrationError("Live hosted subscription billing is not enabled.")
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or
                not 0 < timeout <= 120):
            raise MigrationError("The hosted subscription timeout is invalid.")
        self._origin = origin
        self._timeout = timeout
        self._opener = build_opener(_NoRedirect())

    def _call(self, action, device_id, crypto_helper, apply):
        _require_apply(apply)
        if not isinstance(device_id, str) or not _UUID.fullmatch(device_id):
            raise MigrationError("The hosted subscription device is invalid.")
        try:
            # Returns a validated bearer from the existing helper; no copied
            # login cache, caller token or browser-accessible credential.
            token = HostedEnrollmentClient._credential(device_id, crypto_helper)
            body = json.dumps({"action": action, "deviceId": device_id},
                              separators=(",", ":")).encode("ascii")
            request = Request(self._origin + "/api/hosted-subscription", data=body,
                headers={"Authorization": "Bearer " + token,
                         "Content-Type": "application/json", "Content-Length": str(len(body))},
                method="POST")
            with self._opener.open(request, timeout=self._timeout) as response:
                if (response.status != 200 or
                        response.headers.get("Content-Encoding", "identity") != "identity" or
                        response.headers.get("Content-Type", "").split(";")[0] != "application/json"):
                    raise ValueError("invalid subscription HTTP response")
                data = response.read(_LIMIT + 1)
                if len(data) > _LIMIT:
                    raise ValueError("oversized subscription response")
            return _result(json.loads(data, object_pairs_hook=_unique_object))
        except (HTTPError, URLError, OSError, ValueError, TypeError, MigrationError):
            # Never echo native diagnostics, provider bodies, tokens, checkout
            # links or customer identifiers in an exception.
            raise MigrationError(_FAILED) from None

    def begin(self, device_id, *, crypto_helper=None, apply=False):
        return self._call("begin", device_id, crypto_helper, apply)

    def status(self, device_id, *, crypto_helper=None, apply=False):
        return self._call("status", device_id, crypto_helper, apply)
