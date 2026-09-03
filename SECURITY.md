# Security policy

Codex Migrate handles private conversations, source code, Git history, and local
developer configuration. Please do not publish a vulnerability or attach real
migration data to a public issue.

## Reporting

Use GitHub's private vulnerability reporting for this repository. If that is
unavailable, open a content-free issue asking the maintainer to contact you.

Do not include:

- conversation content;
- credentials, tokens, cookies, or SSH keys;
- complete logs from a real migration;
- private repository names or file paths; or
- a proof that mutates someone else's computer or data.

## Supported versions

Until version 1.0, only the latest tagged release receives security fixes.

## Security invariants

- Source data is never modified or deleted.
- Destination authentication is never imported from the source.
- Host-key verification is never disabled.
- Dashboard controls are loopback-only and token-protected.
- Mutating operations require explicit `--apply`.
- Installation follows staging and a destination backup.
