import sys
from pathlib import Path

# The rsync SSH adapter launches this real Python entry point directly, using
# the current interpreter. It must also work without an inherited PYTHONPATH.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from codex_migrate.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
