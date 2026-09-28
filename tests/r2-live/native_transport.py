"""Synthetic Python-client to real Worker-route transport proof.

Start the local Wrangler fixture first. This sends random test bytes only; it
does not create, publish, or recover a Vault snapshot. Never print grants.
"""

import hashlib
import io
import json
import os
import sys
from urllib.request import Request, build_opener

from codex_migrate.vault_http_store import CapabilityHttpStore, _NoRedirect


ACCOUNT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
VAULT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def prove(origin: str) -> None:
    if origin not in ("http://127.0.0.1:8789", "http://localhost:8789"):
        raise AssertionError("Native probe requires the local Wrangler endpoint")
    client = build_opener(_NoRedirect())
    value = os.urandom(64 * 1024)
    digest = hashlib.sha256(value).hexdigest()
    key = "objects/{}/{}.cvchunk".format(digest[:2], digest[2:])
    scoped = "accounts/{}/vaults/{}/{}".format(ACCOUNT, VAULT, key)

    def grant(method: str, requested: str, size: int, sha256: str) -> str:
        claim = json.dumps({"method": method, "key": requested,
                            "bytes": size, "sha256": sha256},
                           separators=(",", ":")).encode("utf-8")
        request = Request(origin + "/native-grant", data=claim, method="POST",
                          headers={"Content-Type": "application/json",
                                   "Content-Length": str(len(claim))})
        with client.open(request, timeout=15) as response:
            if response.status != 200:
                raise AssertionError("Synthetic grant was refused")
            result = json.loads(response.read(2049))
        if set(result) != {"token"} or not isinstance(result["token"], str):
            raise AssertionError("Synthetic grant was malformed")
        return result["token"]

    store = CapabilityHttpStore(origin, ACCOUNT, VAULT,
                                {key: (len(value), digest)}, grant,
                                allow_loopback_http=True)
    try:
        if store.checked_metadata(key) is not None:
            raise AssertionError("Random test object unexpectedly exists")
        store.put_if_absent(key, io.BytesIO(value), len(value))
        store.put_if_absent(key, io.BytesIO(value), len(value))
        if store.checked_metadata(key) != (len(value), digest):
            raise AssertionError("Uploaded object did not verify")
        with store.open_read(key) as response:
            downloaded = response.read(len(value) + 1)
        if downloaded != value:
            raise AssertionError("Native download changed synthetic bytes")
    finally:
        token = grant("DELETE", scoped, len(value), digest)
        request = Request(origin + "/v1/object/" + scoped, method="DELETE",
                          headers={"Authorization": "Bearer " + token,
                                   "Content-Length": "0"})
        with client.open(request, timeout=15) as response:
            if response.status != 204:
                raise AssertionError("Synthetic object cleanup failed")
    if store.checked_metadata(key) is not None:
        raise AssertionError("Synthetic object remains after cleanup")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: native_transport.py http://127.0.0.1:8789")
    prove(sys.argv[1])
    print("Synthetic native-to-Worker transport passed")
