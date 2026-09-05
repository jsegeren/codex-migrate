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
Path comparisons reject capitalization and Unicode-normalization aliases of
protected storage. Known Codex login/installation hard links in skills are
identified by file metadata only; their contents are not opened or hashed.
Skill names that differ only in capitalization require review instead of
silently overwriting each other on a case-insensitive destination. This is not
general secret detection or a guarantee against a source changing after checks.
The SSH destination is accepted only after ordinary SSH
host-key verification succeeds. The dashboard binds only to loopback and
requires an owner-only random token for status and controls.

Configuration validates the resolved state directory before it is created,
including the relocated default for a selected source home. Workspace and
control folders cannot overlap protected storage through alternate spelling or
resolved aliases. Selected roots with ambiguous case/Unicode spellings fail
closed; exact duplicate/nested roots still collapse to one selection. Nested
filename collisions across different filesystem types need separate acceptance.

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

### Guided SSH connection cards

The browser helper may explicitly create a new dedicated ED25519 key in its
private control directory, separate from selected migration data. The private
key never enters a card, browser response, support report or receiving Mac.
The user carries a request containing its public key and seven-day expiry to
the receiving helper, approves SSH account access there, and carries back a
reply containing the receiver's locally read root-owned public host key and
account address. The reply is bound to the request ID, key and expiry. This is
a user-mediated trust exchange, not an authenticated network-discovery protocol.
The user must carry cards directly between trusted Macs; an attacker-supplied
replacement card can authorize the wrong party if the user approves it.

Approval adds a specifically marked, restricted and expiring authorized-key
entry without changing other entries. It grants SSH command access to the
account, not a filesystem sandbox. Revocation removes only the exact marked
line this helper owns; unknown or edited lines are left intact. If the same
public key remains in an edited or additional active entry, approval and
revocation stop with an unverified result rather than claim success. This is
conservative byte screening of the standard file, not inspection of every
possible SSH authorization source. Missing SSH storage after an interrupted
approval permits retiring its local record without creating access. Existing SSH
sessions can outlive expiry/revocation. Closing the helper does not revoke keys.
Permission, owner, regular-file, hard-link and symbolic-link guards protect
connection files. Atomic replacement checks for changes before publishing;
other SSH-editing tools must not run concurrently. This is not protection
against a malicious process already running as the same user or as root.

Token-protected setup reads restore public connection cards from checked local
records. Reads do not generate keys, authorize access, or contact a destination.
Accepted source records must match the request, generated key and pinned host
file. Receiving replies are offered only while the exact owned authorization
entry is present and the card has not expired. Unreadable records do not become
a fresh or verified connection. The check cannot certify custom SSH policy or
prevent another account-owned process from editing files after inspection.

Paired transfers use explicit identity/host files and an isolated SSH invocation:
no user/system SSH configuration, agent, global known-host fallback, DNS host
trust, password authentication, host-key updating or forwarding. Strict host
checking stays enabled. Route changes retain the paired host-key alias.
macOS Remote Login and receiving-account authorization must already be enabled.
No network-facing HTTP service or password collection is introduced. Guided
pairing assumes standard receiving-account and SSH paths; custom server policy
still needs an administrator. These assumptions require real-Mac acceptance.

The restriction and expiry semantics follow the
[OpenSSH authorized-keys documentation](https://man.openbsd.org/sshd.8#AUTHORIZED_KEYS_FILE_FORMAT).

### Data migration

Full inventory reads bounded user configuration/profile files locally to screen
for storage overrides; no values are emitted. The same system-Perl screen checks
destination and staged user config before backup/replacement. Visible account
`CODEX_HOME` must identify the default state directory, and any `sqlite_home`
key requires review. Config links, special files, known identity-file hard
links, unreadable/changing files, read errors and exceeded scan limits stop the
check. The source helper uses actual home identity, not path spelling, to decide
whether its inherited environment belongs to the selected account.

This is not a full TOML/effective-configuration evaluator. Project/managed
layers, other processes' environments and custom roots remain separate scope
limitations. Source checks are cancellable and reap their child process; they
are not atomic snapshots and do not prevent concurrent writers. Skills-only
repair does not migrate Codex state and retains its existing explicit scope.

```text
inspect → isolated staging → destination backup → install → verify
```

Selected source data is read-only throughout. The helper writes its own control
state and explicitly created connection material separately. Staging is intentionally retained after an
interruption. Full and browser skills finalization refuse to proceed while Codex is
open in either migration account (including the known `codex` CLI/background
engine executable). Unrelated logged-in accounts do not block finalization.
The inspected account's real and effective UIDs must match, be non-root and
own the selected home. Failed commands, malformed/empty process snapshots and
unknown state block installation rather than imply that Codex is closed.
Only executable names and UIDs are inspected, never arguments or environments.
Destination checks run before staged verification, immediately before backup,
and again before replacement in both full and component installations. These
are point-in-time checks, not an atomic lock: renamed executables and other
writers are not detected, and new processes can start after a check. Keep all
writers to selected data closed throughout finalization.

Destination `auth.json` and `installation_id` are excluded from transfer,
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
