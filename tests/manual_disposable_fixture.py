#!/usr/bin/env python3
"""Create a non-destructive, synthetic workspace for two-Mac acceptance.

This maintainer helper is intentionally restricted to a dedicated local account.
It never reads an existing Codex workspace and refuses to overwrite any fixture
root that already contains data.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import sqlite3
import subprocess
import sys
from pathlib import Path


EXPECTED_ACCOUNT = "codexmigratesource"


def fail(message: str) -> None:
    raise SystemExit(message)


def write(path: Path, contents: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    path.chmod(mode)


def git(repo: Path, *args: str) -> None:
    env = dict(os.environ)
    env.update(
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_SYSTEM="/dev/null",
        GIT_AUTHOR_NAME="Codex Migrate Fixture",
        GIT_AUTHOR_EMAIL="fixture@invalid.example",
        GIT_COMMITTER_NAME="Codex Migrate Fixture",
        GIT_COMMITTER_EMAIL="fixture@invalid.example",
    )
    subprocess.run(
        ["/usr/bin/git", *args],
        cwd=str(repo),
        env=env,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def ensure_empty(path: Path) -> None:
    if path.is_symlink():
        fail(f"Refusing linked fixture root: {path}")
    if path.exists() and not path.is_dir():
        fail(f"Refusing non-directory fixture root: {path}")
    if path.exists() and any(path.iterdir()):
        fail(f"Refusing to overwrite non-empty fixture root: {path}")


def chown_tree(path: Path, uid: int, gid: int) -> None:
    for current, directories, files in os.walk(path, topdown=False, followlinks=False):
        for name in files:
            os.lchown(os.path.join(current, name), uid, gid)
        for name in directories:
            os.lchown(os.path.join(current, name), uid, gid)
        os.lchown(current, uid, gid)


def create_codex_fixture(home: Path) -> None:
    codex = home / ".codex"
    active = codex / "sessions/2026/09/04/rollout-fixture-active.jsonl"
    archived = codex / "archived_sessions/rollout-fixture-archived.jsonl"
    active_event = {
        "timestamp": "2026-09-04T16:00:00Z",
        "type": "fixture",
        "payload": {
            "id": "fixture-active",
            "cwd": str(home / "Git/acceptance-repo"),
            "text": "Synthetic active conversation for migration acceptance.",
        },
    }
    archived_event = {
        "timestamp": "2026-09-04T15:00:00Z",
        "type": "fixture",
        "payload": {
            "id": "fixture-archived",
            "cwd": str(home / "Git/acceptance-repo"),
            "text": "Synthetic archived conversation for migration acceptance.",
        },
    }
    write(active, json.dumps(active_event) + "\n")
    write(archived, json.dumps(archived_event) + "\n")
    write(codex / "config.toml", 'model = "gpt-5"\n')
    write(codex / "AGENTS.md", "Synthetic Codex Migrate acceptance rules.\n")
    write(codex / "history.jsonl", json.dumps({"fixture": True, "kind": "history"}) + "\n")
    write(codex / "projects.json", json.dumps({"projects": [str(home / "Git/acceptance-repo")]}) + "\n")
    managed = codex / "worktrees/acceptance-managed"
    write(managed / "README.md", "Synthetic managed-worktree payload.\n", 0o644)
    (managed / "empty-directory").mkdir(parents=True)
    with sqlite3.connect(str(codex / "state_5.sqlite")) as database:
        database.execute("create table fixture (name text primary key, value text not null)")
        database.execute("insert into fixture values (?, ?)", ("acceptance", "synthetic"))
    (codex / "state_5.sqlite").chmod(0o600)


def create_skills_fixture(home: Path) -> None:
    write(
        home / ".agents/skills/personal-fixture/SKILL.md",
        "---\nname: personal-fixture\ndescription: Synthetic personal migration skill.\n---\n",
        0o644,
    )


def create_git_fixture(home: Path) -> None:
    repo = home / "Git/acceptance-repo"
    linked = home / "Git/acceptance-linked"
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    write(repo / "README.md", "# Synthetic acceptance repository\n", 0o644)
    write(repo / "src/app.txt", "committed main content\n", 0o644)
    write(
        repo / ".agents/skills/workspace-fixture/SKILL.md",
        "---\nname: workspace-fixture\ndescription: Synthetic workspace migration skill.\n---\n",
        0o644,
    )
    git(repo, "add", "README.md", "src/app.txt", ".agents/skills/workspace-fixture/SKILL.md")
    git(repo, "commit", "-m", "Create synthetic acceptance repository")

    git(repo, "switch", "-c", "feature/local-only")
    write(repo / "src/feature.txt", "local branch commit\n", 0o644)
    git(repo, "add", "src/feature.txt")
    git(repo, "commit", "-m", "Add local-only feature branch")
    git(repo, "switch", "main")

    write(repo / "stash-only.txt", "untracked file captured in stash\n", 0o644)
    write(repo / "README.md", "# Synthetic acceptance repository\n\nStashed edit.\n", 0o644)
    git(repo, "stash", "push", "--include-untracked", "-m", "codex-migrate-acceptance-stash")

    git(repo, "worktree", "add", "-b", "linked/local-only", str(linked))
    write(linked / "linked-uncommitted.txt", "unfinished linked-worktree work\n", 0o644)

    write(repo / "README.md", "# Synthetic acceptance repository\n\nUncommitted main-worktree edit.\n", 0o644)
    write(repo / "untracked-main.txt", "untracked main-worktree file\n", 0o644)
    os.symlink("README.md", repo / "readme-link")
    (repo / "empty-directory").mkdir()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument("--owner", required=True)
    arguments = parser.parse_args()

    account = pwd.getpwnam(arguments.owner)
    home = Path(arguments.home).resolve()
    if arguments.owner != EXPECTED_ACCOUNT:
        fail(f"Owner must be the disposable account {EXPECTED_ACCOUNT}")
    if home != Path(account.pw_dir).resolve() or home != Path("/Users") / EXPECTED_ACCOUNT:
        fail("Home must exactly match the disposable account directory")
    if os.geteuid() not in (0, account.pw_uid):
        fail("Run as root or as the disposable account owner")

    roots = (home / ".codex", home / ".agents", home / "Git")
    for root in roots:
        ensure_empty(root)

    create_codex_fixture(home)
    create_skills_fixture(home)
    create_git_fixture(home)
    write(
        home / ".codex-migrate-acceptance-fixture.json",
        json.dumps({"schema": 1, "synthetic": True, "owner": EXPECTED_ACCOUNT}, indent=2) + "\n",
    )
    if os.geteuid() == 0:
        for root in (*roots, home / ".codex-migrate-acceptance-fixture.json"):
            if root.is_dir():
                chown_tree(root, account.pw_uid, account.pw_gid)
            else:
                os.chown(root, account.pw_uid, account.pw_gid)
    print("Disposable acceptance fixture created.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
