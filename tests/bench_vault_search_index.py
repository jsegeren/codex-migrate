"""Opt-in synthetic database-search benchmark; never reads customer history.

Run with PYTHONPATH=src. The temporary Codex home and index are removed on exit.
This measures source-interpreter search, not a packaged app or real user data.
"""

import argparse
import base64
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time

from codex_migrate.vault import search
from codex_migrate.vault_search_index import _path, build, supported


MARKER = "synthetic-unique-search-needle-8942"
MISS = "synthetic-not-found-needle-8942"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, default=100)
    parser.add_argument("--items-per-thread", type=int, default=200)
    parser.add_argument("--text-bytes", type=int, default=1024)
    parser.add_argument("--alphabet", choices=("hex", "base64"), default="base64",
                        help="base64 is a high-trigram-variety stress case, not prose")
    args = parser.parse_args()
    if (not 1 <= args.threads <= 2_000 or
            not 1 <= args.items_per_thread <= 1_000 or
            not 32 <= args.text_bytes <= 8_192 or
            args.threads * args.items_per_thread * args.text_bytes > 1_000_000_000):
        parser.error("benchmark size is outside the bounded synthetic range")
    if not supported():
        parser.error("this Python SQLite cannot build the optional trigram index")

    with tempfile.TemporaryDirectory(prefix="codex-vault-search-scale-") as temporary:
        home = Path(temporary)
        database = home / ".codex/thread_history_1.sqlite"
        database.parent.mkdir()
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, "
                               "item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, "
                               "item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER)")
            connection.execute("CREATE INDEX thread_items_thread_ordinal "
                               "ON thread_items(thread_id, rollout_ordinal)")
            connection.execute("CREATE TABLE thread_history_projection_state ("
                               "thread_id TEXT, next_rollout_byte_offset INTEGER, "
                               "next_rollout_ordinal INTEGER)")

            def rows():
                for thread_number in range(args.threads):
                    thread_id = "00000000-0000-4000-8000-%012d" % thread_number
                    for ordinal in range(args.items_per_thread):
                        item_id = "item-%d-%d" % (thread_number, ordinal)
                        if args.alphabet == "base64":
                            text = base64.urlsafe_b64encode(
                                hashlib.shake_256(item_id.encode()).digest(
                                    (args.text_bytes * 3 + 3) // 4)).decode()[:args.text_bytes]
                        else:
                            text = hashlib.shake_256(item_id.encode()).hexdigest(
                                (args.text_bytes + 1) // 2)[:args.text_bytes]
                        if thread_number == args.threads // 2 and ordinal == args.items_per_thread // 2:
                            text += " " + MARKER
                        body = json.dumps({"id": item_id, "type": "userMessage",
                                           "text": text})
                        yield (thread_id, "turn-%d" % ordinal, item_id, ordinal,
                               ordinal, body, "userMessage", ordinal)

            connection.executemany("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)", rows())

        def timed_search(query):
            started = time.monotonic()
            found = search(temporary, query, limit=10)
            return found, round(time.monotonic() - started, 3)

        direct_hit, direct_hit_seconds = timed_search(MARKER)
        direct_miss, direct_miss_seconds = timed_search(MISS)
        if len(direct_hit) != 1 or direct_miss:
            raise AssertionError("direct synthetic search returned unexpected results")
        started = time.monotonic()
        result = build(temporary, apply=True)
        index_seconds = round(time.monotonic() - started, 3)
        if not result.get("paginated_indexed") or result.get("paginated_threads") != args.threads:
            raise AssertionError("the database index was not complete")
        indexed_hit, indexed_hit_seconds = timed_search(MARKER)
        indexed_miss, indexed_miss_seconds = timed_search(MISS)
        if indexed_hit != direct_hit or indexed_miss:
            raise AssertionError("indexed search differed from direct search")
        print(json.dumps({
            "threads": args.threads,
            "items": args.threads * args.items_per_thread,
            "alphabet": args.alphabet,
            "database_bytes": database.stat().st_size,
            "index_bytes": _path(temporary).stat().st_size,
            "direct_hit_seconds": direct_hit_seconds,
            "direct_miss_seconds": direct_miss_seconds,
            "build_seconds": index_seconds,
            "indexed_hit_seconds": indexed_hit_seconds,
            "indexed_miss_seconds": indexed_miss_seconds,
        }, sort_keys=True))


if __name__ == "__main__":
    main()
