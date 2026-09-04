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

Full Git inspection may inspect metadata and link targets elsewhere inside the
source home to identify required storage. It does not run Git, read object
contents, or automatically transfer discovered folders. Required unselected
storage blocks preflight before SSH. Dependencies outside the source home and
unreadable or unsupported pointer metadata require review. Intermediate aliases
are part of the required scope, not just fully resolved link targets.

Codex runtime exclusions apply at the Codex root, not inside managed worktrees.
Branches named `cache/...`, reflogs, and unfinished files in `logs` or `packages`
must not be lost to app-cache exclusions. Complete selected and managed
workspaces can contain their own credentials; review them before copying.

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

Active and archived `.jsonl` transcripts receive a frozen source SHA-256 and
relative-path check against staging before backup/replacement, then against the
installed copy under the rollback trap. Extra/missing transcripts, different
bytes, links, or special transcript files cannot receive a successful content
receipt. A source transcript changing while it is hashed also blocks the check.
No transcript contents or hashes are printed. This is not an atomic snapshot;
keep writing apps closed. It does not validate JSON semantics or prove Codex
can reopen each chat and its historical workspace.

Browser skills-only migrations use the same explicit staging/finalization and
normal-shutdown protection, but their replacement scope contains only selected
skills. They do not copy or replace Codex state or whole repositories, and do
not claim to verify conversation counts or destination login-file hashes.
Both staged and installed skill contents are checked against the same frozen
source snapshot. Existing destination aliases are backed up without following
them. The one-pass CLI export remains separate from resumable browser staging.

Retained Codex configuration, organization, rules, automations and databases are
also compared against a frozen source tree before backup/replacement and after
installation under rollback. The check derives exact root-anchored filters from
transfer exclusions: directory-only patterns do not omit regular files or links
with those names. Managed worktrees have a separate mandatory complete check.
Canonical source `auth.json` and `installation_id` are not opened. Noncanonical
capitalization of these filenames blocks copying/hashing to protect against
case-insensitive filesystem aliases; unexpected staged identity links also
block installation. This is not general detection of secrets copied under
other retained names or stored inside user-selected workspaces.

Only the Codex root mode is omitted from the content snapshot because the
installer explicitly changes it to 700. Retained child modes remain checked.
The installed byte comparison precedes SQLite validation, which may change
sidecars. It is not a promise that runtime files or database bytes remain
unchanged after verification or that Codex can reopen every restored task.

## Known limitations

Selected workspaces and Codex-managed worktrees receive streaming SHA-256 tree
checks against the same frozen source expectations before replacement and
after installation. They include Git object/ref bytes, working files, names,
regular-file/directory permission bits, empty directories, and symlink text.
Links are not followed. Unreadable, changing, or special files fail closed.
Hashes are privately compared, never displayed or saved in progress state.
This does not independently verify ownership, timestamps, ACLs, extended
attributes, or hard-link topology, nor prove Git commands work on the new Mac.

- Codex's local storage format is not a documented public migration API and can
  change between releases.
- Version 0.1 reports but does not automatically fix every stale historical
  worktree path.
- Different macOS usernames require a reviewed compatibility alias.
- Content checks cover the retained copy scope, not excluded runtime data,
  semantic configuration validity, Git usability or old workspace-path
  continuity. Those require separate validation.
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
