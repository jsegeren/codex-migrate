"""Validated migration configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import re
import unicodedata
from typing import Dict, List, Optional

from codex_migrate.destination_lock import LOCK_NAME
from codex_migrate.transaction import TRANSACTION_NAME


TARGET_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9._-]*@(?:[A-Za-z0-9][A-Za-z0-9._-]*|\[[0-9A-Fa-f:]+\])$"
)


def path_key(path: str) -> tuple:
    """Conservative Mac path identity, without rewriting the path used for I/O.

    Reject ambiguous selections even on case-sensitive source volumes: the
    destination may be case-insensitive or normalization-insensitive.
    """
    return tuple(unicodedata.normalize("NFD", part).casefold()
                 for part in Path(path).parts)


def paths_overlap(left: str, right: str) -> bool:
    a, b = path_key(left), path_key(right)
    return a[:len(b)] == b or b[:len(a)] == a


def _clean_absolute(path: str, label: str) -> str:
    if not path or "\x00" in path or "\n" in path or "\r" in path:
        raise ValueError("%s contains unsupported characters" % label)
    expanded = str(Path(path).expanduser())
    if not Path(expanded).is_absolute():
        raise ValueError("%s must be absolute" % label)
    return os.path.normpath(expanded)


@dataclass(frozen=True)
class SSHOptions:
    identity_file: Optional[str] = None
    known_hosts_file: Optional[str] = None
    host_key_alias: Optional[str] = None
    connect_timeout: int = 15

    def validate(self) -> "SSHOptions":
        if self.identity_file:
            object.__setattr__(
                self,
                "identity_file",
                _clean_absolute(self.identity_file, "identity file"),
            )
        if self.known_hosts_file:
            object.__setattr__(
                self,
                "known_hosts_file",
                _clean_absolute(self.known_hosts_file, "known-hosts file"),
            )
        if self.host_key_alias and not re.match(r"^[A-Za-z0-9._-]+$", self.host_key_alias):
            raise ValueError("host-key alias contains unsupported characters")
        if self.connect_timeout < 1 or self.connect_timeout > 120:
            raise ValueError("connect timeout must be between 1 and 120 seconds")
        return self


@dataclass(frozen=True)
class MigrationConfig:
    target: str
    target_home: str
    workspace_roots: List[str] = field(default_factory=list)
    source_home: str = field(default_factory=lambda: str(Path.home()))
    state_dir: str = field(
        default_factory=lambda: str(Path.home() / ".local/state/codex-migrate")
    )
    staging_name: str = "Codex-Migrate-Staging"
    backup_prefix: str = "Codex-Migrate-Backup"
    apply: bool = False
    compress: bool = True
    ssh: SSHOptions = field(default_factory=SSHOptions)

    def validate(self) -> "MigrationConfig":
        if not TARGET_PATTERN.fullmatch(self.target):
            raise ValueError("target must look like user@host")
        for label, name in (("staging name", self.staging_name), ("backup prefix", self.backup_prefix)):
            if (name.casefold() in (".", "..", ".codex", ".ssh", ".agents", ".local", LOCK_NAME, TRANSACTION_NAME)
                    or not re.fullmatch(r"[A-Za-z0-9._-]+", name)):
                raise ValueError("%s is reserved or contains unsupported characters" % label)
        if (self.staging_name.casefold() == self.backup_prefix.casefold()
                or self.staging_name.casefold().startswith(self.backup_prefix.casefold() + "-")):
            raise ValueError("staging and backup namespaces must be separate")
        object.__setattr__(self, "target_home", _clean_absolute(self.target_home, "target home"))
        source_home = str(Path(_clean_absolute(self.source_home, "source home")).resolve())
        object.__setattr__(self, "source_home", source_home)
        state_dir = str(Path(_clean_absolute(self.state_dir, "state directory")).resolve())
        default_state = str((Path.home() / ".local/state/codex-migrate").resolve())
        if state_dir == default_state and source_home != str(Path.home().resolve()):
            state_dir = str((Path(source_home) / ".local/state/codex-migrate").resolve())
        if source_home == "/" or state_dir == source_home:
            raise ValueError("source home and state directory must not be broad filesystem roots")
        if os.path.commonpath((source_home, state_dir)) != source_home:
            raise ValueError("state directory must live beneath the source home")
        protected_paths = set()
        for relative in (".codex", ".ssh", ".agents/skills"):
            protected = Path(source_home) / relative
            protected_paths.update((str(protected), str(protected.resolve())))
        for protected_path in protected_paths:
            if paths_overlap(protected_path, state_dir):
                raise ValueError("state directory must not overlap Codex, SSH or personal skills storage")
        object.__setattr__(self, "state_dir", state_dir)
        roots = []
        for root in self.workspace_roots:
            cleaned = str(Path(_clean_absolute(root, "workspace root")).resolve())
            if os.path.commonpath((self.source_home, cleaned)) != self.source_home:
                raise ValueError("workspace roots must live beneath the source home")
            if cleaned == self.source_home:
                raise ValueError("select workspace directories beneath the source home")
            if any(paths_overlap(protected, cleaned) for protected in protected_paths):
                raise ValueError("workspace roots must not overlap Codex, SSH or separately managed personal skills storage")
            if paths_overlap(cleaned, state_dir):
                raise ValueError("workspace roots must not overlap migration control state")
            relative = os.path.relpath(cleaned, self.source_home)
            first_component = path_key(relative)[0]
            if first_component in (LOCK_NAME, TRANSACTION_NAME):
                raise ValueError("workspace root collides with destination safety state")
            if first_component == self.staging_name.casefold():
                raise ValueError("workspace root collides with the reserved staging namespace")
            if first_component == self.backup_prefix.casefold() or first_component.startswith(
                self.backup_prefix.casefold() + "-"
            ):
                raise ValueError("workspace root collides with the reserved backup namespace")
            for existing in roots:
                for left, right in zip(Path(existing).parts, Path(cleaned).parts):
                    if path_key(left) != path_key(right):
                        break
                    if left != right:
                        raise ValueError("workspace roots have ambiguous capitalization or Unicode spelling; select one consistent path spelling")
            if any(os.path.commonpath((existing, cleaned)) == existing for existing in roots):
                continue
            roots = [
                existing
                for existing in roots
                if os.path.commonpath((existing, cleaned)) != cleaned
            ]
            roots.append(cleaned)
        object.__setattr__(self, "workspace_roots", roots)
        self.ssh.validate()
        return self

    @property
    def source_codex(self) -> str:
        return str(Path(self.source_home) / ".codex")

    @property
    def target_codex(self) -> str:
        return str(Path(self.target_home) / ".codex")

    @property
    def target_staging(self) -> str:
        return str(Path(self.target_home) / self.staging_name)

    def to_public_dict(self) -> Dict[str, object]:
        value = asdict(self)
        value["ssh"]["identity_file"] = bool(self.ssh.identity_file)
        value["ssh"]["known_hosts_file"] = bool(self.ssh.known_hosts_file)
        return value
