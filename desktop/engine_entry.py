"""Frozen-engine entry point. The core remains independently usable."""
import sys

from codex_migrate.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--vault-paginated-reader":
        from codex_migrate.vault_paginated import _reader_main
        raise SystemExit(_reader_main(sys.argv[2]))
    raise SystemExit(main())
