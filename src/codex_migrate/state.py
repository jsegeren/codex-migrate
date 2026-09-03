"""Atomic, owner-only migration state."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
from typing import Any, Dict


INITIAL_STATE = {
    "status": "idle",
    "phase": "not_started",
    "message": "Ready to inspect both Macs.",
    "bytes_total": 0,
    "bytes_staged": 0,
    "percent": 0.0,
    "current_item": None,
    "error": None,
    "warning": None,
    "route": None,
    "receipt": None,
    "pending_backup": None,
    "staging_complete": False,
}


class StateStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.path = self.root / "state.json"
        self.token_path = self.root / "control-token"
        self.lock_path = self.root / "process.lock"
        self._process_lock = None
        self._lock = threading.RLock()
        if self.root == Path("/"):
            raise PermissionError("state directory must not be a filesystem root")
        if self.root.is_symlink():
            raise PermissionError("state directory must not be a symbolic link")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        if not self.path.exists():
            self.write(dict(INITIAL_STATE))

    def read(self) -> Dict[str, Any]:
        with self._lock:
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                return dict(INITIAL_STATE)

    def write(self, state: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".%s." % self.path.name,
                suffix=".tmp",
                dir=str(self.root),
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            return state

    def update(self, **changes: Any) -> Dict[str, Any]:
        with self._lock:
            state = self.read()
            state.update(changes)
            return self.write(state)

    def token(self) -> str:
        with self._lock:
            if self.token_path.exists():
                if self.token_path.is_symlink():
                    raise PermissionError("control-token must not be a symbolic link")
                os.chmod(self.token_path, 0o600)
                existing = self.token_path.read_text(encoding="utf-8").strip()
                if len(existing) == 64:
                    return existing
            value = secrets.token_hex(32)
            self.token_path.write_text(value + "\n", encoding="utf-8")
            os.chmod(self.token_path, 0o600)
            return value

    def acquire_process_lock(self) -> None:
        with self._lock:
            if self._process_lock is not None:
                return
            if self.lock_path.is_symlink():
                raise PermissionError("process lock must not be a symbolic link")
            descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            handle = os.fdopen(descriptor, "a+")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                handle.close()
                raise RuntimeError(
                    "another Codex Migrate process is already using this state directory"
                ) from error
            os.chmod(self.lock_path, 0o600)
            self._process_lock = handle

    def release_process_lock(self) -> None:
        with self._lock:
            if self._process_lock is None:
                return
            fcntl.flock(self._process_lock.fileno(), fcntl.LOCK_UN)
            self._process_lock.close()
            self._process_lock = None
