"""Conservative classification of customer-selected Vault locations.

This module recognizes common macOS cloud-provider folders.  It never claims
that a provider is running or that a particular file has reached the cloud;
only the provider can prove that.  The result exists to prevent a local folder
from being presented as off-device protection by implication.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class VaultStorage:
    kind: str
    provider: Optional[str]
    heading: str
    detail: str
    off_device_protection: str

    def as_dict(self):
        return asdict(self)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _cloud_storage_provider(name: str) -> Optional[str]:
    folded = name.casefold()
    providers = (
        ("onedrive", "OneDrive"),
        ("googledrive", "Google Drive"),
        ("google drive", "Google Drive"),
        ("dropbox", "Dropbox"),
        ("box", "Box"),
        ("protondrive", "Proton Drive"),
    )
    for prefix, provider in providers:
        if folded == prefix or folded.startswith(prefix + "-"):
            return provider
    return None


def classify_vault_storage(path: str, source_home: str) -> VaultStorage:
    """Describe whether *path* is recognizably managed by a cloud provider.

    Paths are resolved to account for a customer choosing an alias into a
    provider folder.  Classification is informational and intentionally
    conservative: provider status and remote durability remain unverified.
    """
    selected = Path(path).expanduser().resolve(strict=False)
    home = Path(source_home).expanduser().resolve(strict=False)

    cloud_storage = home / "Library" / "CloudStorage"
    if _inside(selected, cloud_storage):
        relative = selected.relative_to(cloud_storage)
        provider = (_cloud_storage_provider(relative.parts[0])
                    if relative.parts else None)
        provider = provider or "a macOS cloud provider"
        return VaultStorage(
            kind="cloud_sync",
            provider=provider,
            heading="Cloud-sync folder detected",
            detail=(
                "This folder is managed by %s. Codex Migrate cannot confirm "
                "that syncing is current, so check the provider before relying "
                "on this backup after loss of the Mac."
            ) % provider,
            off_device_protection="possible_unverified",
        )

    icloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    if _inside(selected, icloud):
        return VaultStorage(
            kind="cloud_sync",
            provider="iCloud Drive",
            heading="Cloud-sync folder detected",
            detail=(
                "This folder is managed by iCloud Drive. Codex Migrate cannot "
                "confirm that syncing is current, so check iCloud before "
                "relying on this backup after loss of the Mac."
            ),
            off_device_protection="possible_unverified",
        )

    legacy = (
        (home / "OneDrive", "OneDrive"),
        (home / "Google Drive", "Google Drive"),
        (home / "Dropbox", "Dropbox"),
        (home / "Box", "Box"),
    )
    for root, provider in legacy:
        if _inside(selected, root):
            return VaultStorage(
                kind="cloud_sync",
                provider=provider,
                heading="Cloud-sync folder detected",
                detail=(
                    "This looks like a legacy %s sync folder. Confirm that the "
                    "provider still manages it and that syncing is current "
                    "before relying on it after loss of the Mac."
                ) % provider,
                off_device_protection="possible_unverified",
            )

    if selected.parts[:2] == ("/", "Volumes"):
        return VaultStorage(
            kind="external_or_network",
            provider=None,
            heading="External or network location",
            detail=(
                "This folder is outside the Mac's home folder, but Codex "
                "Migrate cannot verify that the device or server is durable, "
                "available, or backed up."
            ),
            off_device_protection="unverified",
        )

    return VaultStorage(
        kind="local",
        provider=None,
        heading="Stored on this Mac",
        detail=(
            "No recognized cloud-sync location was detected. This backup can "
            "recover deleted or damaged conversations, but it does not protect "
            "against loss of this Mac or its drive unless you copy it elsewhere."
        ),
        off_device_protection="not_detected",
    )
