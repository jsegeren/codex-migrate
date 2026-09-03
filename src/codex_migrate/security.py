"""Security helpers that keep secrets and shell control characters out."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable


SECRET_NAME_PATTERN = re.compile(
    r"(^|/)(auth\.json|installation_id|.*\.pem|.*\.key|id_(rsa|ed25519))$",
    re.IGNORECASE,
)


def is_protected_name(path: str) -> bool:
    return bool(SECRET_NAME_PATTERN.search(path.replace("\\", "/")))


def redact(text: str, protected_paths: Iterable[str] = ()) -> str:
    result = text
    for path in protected_paths:
        if path:
            result = result.replace(path, "[private-path]")
    result = re.sub(r"(?i)(token|password|secret|authorization)=\S+", r"\1=[redacted]", result)
    result = re.sub(r"gh[opsu]_[A-Za-z0-9_]+", "[redacted-github-token]", result)
    return result


def assert_owner_only(path: str) -> None:
    mode = Path(path).stat().st_mode & 0o777
    if mode & 0o077:
        raise PermissionError("%s must be owner-only" % path)
