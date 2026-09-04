"""Frozen-engine entry point. The core remains independently usable."""
from codex_migrate.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
