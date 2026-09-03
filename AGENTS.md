# Codex Migrate contributor guide

Codex Migrate is an unofficial, privacy-first macOS migration utility. Safety
and recoverability take priority over speed or convenience.

## Engineering rules

- Never copy, print, log, hash-display, or commit authentication material.
- Preserve the destination Mac's `~/.codex/auth.json` and `installation_id`.
- Never delete or mutate source data.
- Default to planning and inspection. Mutating operations require `--apply`.
- Bind the dashboard to loopback and require its random control token.
- Treat shell arguments, SSH targets, paths, and rsync output as untrusted.
- Do not use `StrictHostKeyChecking=no`.
- Stage first, back up the destination, install second, then verify.
- A failed or interrupted transfer must remain resumable by rerunning it.
- Keep the core dependency-free and compatible with Python 3.9 or newer.
- Add tests for every state transition or safety boundary changed.

Do not add OpenAI logos or language implying affiliation, endorsement, or
official support. “Codex” is referenced only to describe compatibility with
the Codex product.
