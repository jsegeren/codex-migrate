# Security model

Codex Migrate assumes both Macs and the local network are controlled by the
same person. It does not make an untrusted destination safe.

## Protected assets

- Codex conversations and local task metadata
- Private source repositories and uncommitted work
- Git objects, refs, stashes, and worktree registrations
- Local configuration, skills, automations, and memories
- Destination Codex authentication and installation identity

## Trust boundaries

The source process may read only the selected source home, `~/.codex`, and
workspace roots, plus validated personal skills in `~/.agents/skills` and legacy
`~/.codex/skills`. Personal skill aliases and file links are materialized on the
destination only when their resolved source targets remain inside the source
home; references to the protected SSH directory or Codex
authentication/installation files are rejected, including relocated aliases.
The SSH destination is accepted only after ordinary SSH
host-key verification succeeds. The dashboard binds only to loopback and
requires an owner-only random token for status and controls.

## Safety sequence

```text
inspect → isolated staging → destination backup → install → verify
```

The source is read-only throughout. Staging is intentionally retained after an
interruption. Finalization refuses to proceed while either Codex application is
open. Destination `auth.json` and `installation_id` are excluded from transfer,
hashed locally on the destination before and after installation, and compared
without printing their hashes. Existing destination Codex state and selected
workspace roots receive copy-on-write rollback backups before replacement.
Existing destination data is budgeted conservatively in the free-space check,
and backups must pass content-checksum, structure, and symlink verification
before replacement. Verification receipts stay in the owner-only backup folder.
See [Recovery](recovery.md) for the exact coverage and limitations.

## Known limitations

- Codex's local storage format is not a documented public migration API and can
  change between releases.
- Version 0.1 reports but does not automatically fix every stale historical
  worktree path.
- Different macOS usernames require a reviewed compatibility alias.
- File-count and SQLite checks do not provide a cryptographic proof of every
  workspace byte in version 0.1.
- Staging and rollback backups contain private user data and must remain
  owner-only.
- Other tools and connectors may store their own credentials inside copied
  configuration. Review selected data and use only a trusted destination.
- Selected workspaces are exact copies. Credentials committed or stored inside
  those roots are included even though the default `~/.ssh` directory is not.

## Threats explicitly rejected

- Disabling SSH host-key verification
- Copying source authentication to the destination
- Binding the dashboard publicly
- Logging credentials or conversation contents
- Deleting source data after success
- Automatically deleting staging or backups
- Treating a partial transfer as complete
