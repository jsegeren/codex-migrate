# Codex Migrate

**Unofficial, privacy-first Mac-to-Mac migration for local Codex workspaces.**

Codex Migrate moves the local working state that does not magically appear when
you sign into Codex on a new Mac: conversations, project organization,
configuration, skills, automations, repositories, branches, worktrees, stashes,
and unfinished files.

It stages a resumable copy over SSH, preserves the new Mac's authentication,
creates a rollback backup, installs only after both Codex apps are closed, and
verifies the result before declaring completion.

> **Alpha:** This project was extracted from a successful real-world migration
> spanning hundreds of gigabytes. The core safety model is implemented and
> tested, but the public CLI
> still needs broader hardware and Codex-version testing. Read the plan before
> using `--apply`.

Codex Migrate is an independent project by Joshua Segeren. It is not made by,
affiliated with, supported by, or endorsed by OpenAI. OpenAI and Codex are
trademarks of their respective owner.

**Website:** [codex-migrate.vercel.app](https://codex-migrate.vercel.app)

![Codex Migrate showing a resumable workspace transfer](docs/images/dashboard.png)

## Why this exists

I changed Macs and discovered there was no documented, end-to-end way to move
my complete local Codex workspace. Signing in on the new computer did not
restore the working environment I depended on.

The workspace included thousands of conversations, archived tasks, multiple
projects, local Git branches and worktrees, uncommitted work, custom skills,
automations, and hundreds of gigabytes of source files. Apple's Migration
Assistant stalled. I built the migration tool I needed, then turned it into an
open project so nobody else has to reconstruct the process under pressure.

## What it transfers

- Active and archived local Codex conversations
- Codex configuration, project organization, skills, rules, memories, and
  automations
- User-selected workspace roots, including complete `.git` directories
- Local branches, remote refs, tags, stashes, linked-worktree metadata, and
  uncommitted or untracked files contained in those roots
- Relevant local Codex state required to resume work

## What it deliberately does not transfer

- `~/.codex/auth.json`
- `~/.codex/installation_id`
- The source Mac's `~/.ssh` directory and its private keys
- Runtime sockets, process locks, logs, and disposable caches
- Anything outside the explicitly selected source home and workspace roots

Selected workspace roots are copied byte-for-byte. Audit them before transfer:
a credential stored inside a selected repository or workspace is part of that
workspace and will be copied.

The new Mac must have Codex installed, opened, and signed in once before the
migration. Its authentication and installation identity are retained and
verified after installation.

## Requirements

- Two Macs
- Python 3.9 or newer on the source Mac
- Remote Login enabled on the destination Mac
- `ssh` and `rsync` available on both Macs
- An APFS destination home volume (required for space-efficient rollback)
- An SSH connection whose host key has already been verified
- Enough free destination space for staging, a safety backup, and the final
  workspace

Codex Migrate never disables SSH host-key verification. Connect manually once
before using the tool:

```bash
ssh new-user@new-mac.local
```

Confirm the host fingerprint, then exit that SSH session.

## Quick start

Clone the repository on the old Mac:

```bash
git clone https://github.com/jsegeren/codex-migrate.git
cd codex-migrate
chmod +x ./codex-migrate
```

Inspect the local source without changing anything:

```bash
./codex-migrate inventory \
  --workspace "$HOME/Git" \
  --workspace "$HOME/Documents"
```

Run destination preflight in read-only planning mode:

```bash
./codex-migrate inspect \
  --target new-user@new-mac.local \
  --target-home /Users/new-user \
  --workspace "$HOME/Git"
```

Start the local dashboard with mutation enabled:

```bash
./codex-migrate serve \
  --apply \
  --target new-user@new-mac.local \
  --target-home /Users/new-user \
  --workspace "$HOME/Git"
```

The dashboard binds only to `127.0.0.1`. Its controls require a random
owner-only token carried in the URL fragment, which browsers do not send to the
HTTP server or remote Mac.

## Selective component export

You do not need to repeat a large migration to repair a missing skill. The
`export` command can independently stage, back up, install, and verify personal
skills or repository-scoped workspace skills. It materializes top-level skill
aliases and file links only after proving their targets stay inside the source
home. Nested directory links are rejected. User-wide skills are installed in
the current documented `~/.agents/skills` location so a macOS username change
does not leave broken absolute links.

Plan a personal-skills-only repair:

```bash
./codex-migrate export \
  --component personal-skills \
  --target new-user@new-mac.local \
  --target-home /Users/new-user
```

Apply both personal and workspace skill repairs:

```bash
./codex-migrate export \
  --apply \
  --component personal-skills \
  --component workspace-skills \
  --target new-user@new-mac.local \
  --target-home /Users/new-user \
  --workspace "$HOME/Git"
```

Each destination skill is backed up before replacement. Other skills and all
conversation, configuration, authentication, and repository data are left
untouched. Rerunning the command is safe. Additional independently selectable
components will follow the same stage → backup → install → verify contract.

## Migration phases

1. **Inspect** — verify source state, destination identity, SSH safety, required
   tools, selected workspaces, counts, and estimated size.
2. **Stage** — copy into an isolated destination staging directory using
   resumable `rsync --partial`. Source files are never modified.
3. **Pause or stop safely** — suspend the active transfer or terminate it while
   retaining staged data. Resume reruns the same copy and reuses completed data.
4. **Finalize** — require Codex to be closed on both Macs, refresh the final
   delta, clone a destination backup, and move the staged data into place on
   the same volume without creating a second full-size copy.
5. **Verify** — compare conversation counts, run SQLite integrity checks, and
   prove destination authentication and installation identity did not change.

## Different macOS usernames

Older Codex conversation files can contain absolute working-directory paths.
When the two Macs use different usernames, the fastest compatibility approach
is an alias on the new Mac:

```bash
sudo ln -s /Users/new-user /Users/old-user
```

The dashboard prints the exact command after validating both home paths. Review
it before running it. A future release will offer a slower full metadata rewrite
for users who do not want a compatibility alias.

## Transfer routes

Codex Migrate reports the route selected by macOS. It works over ordinary
Wi-Fi, Ethernet, Thunderbolt networking, or a direct link that already supports
SSH. The current CLI accepts one destination at a time. Automatic multi-route
benchmarking is on the near-term roadmap.

## Privacy and security

- No telemetry
- No analytics
- No cloud service
- No account creation
- No copied Codex account authentication or installation identity
- No `StrictHostKeyChecking=no`
- No source deletion
- No installation without `--apply`
- Loopback-only dashboard with token-protected controls
- Timestamped destination backup before installation

Read [the security model](docs/security-model.md) before using the alpha on an
irreplaceable workspace. Please report vulnerabilities privately according to
[SECURITY.md](SECURITY.md).

## Free CLI and Founding Edition

The migration engine is MIT-licensed and will remain inspectable and usable from
the command line. A signed, notarized Mac app is in development for people who
want automatic discovery, guided permissions, route testing, one-click controls,
updates, and support. A **$49 one-time Founding Edition pre-order** reserves an
individual v1 license and beta access. It is not a subscription. See
[the commercial-edition principles](docs/commercial-edition.md).

The signed Mac app is not available for download today. The complete free CLI
is. Pre-orders are refundable at any time before the first beta and for 30 days
after delivery. The checkout and full terms are available on the
[project website](https://codex-migrate.vercel.app/#founding-edition).

## Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md). Migration code has an unusually
high trust burden: safety changes require tests and should fail closed.

## License

[MIT](LICENSE)
