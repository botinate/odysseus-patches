"""Sandbox git fixtures: a fake upstream (bare) + a user checkout (clone).

GitHub's refs/pull/N/head namespace is simulated by pushing branches to
those refs on the bare repo — git fetch works against them identically.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "sandbox",
    "GIT_AUTHOR_EMAIL": "sandbox@example.invalid",
    "GIT_COMMITTER_NAME": "sandbox",
    "GIT_COMMITTER_EMAIL": "sandbox@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=GIT_ENV,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


class Upstream:
    """Drives the fake upstream repo: commits on dev, PR refs, squash-merges."""

    def __init__(self, bare: Path, work: Path):
        self.bare = bare
        self.work = work
        self._next_branch = 0

    def commit_on_dev(self, relpath: str, content: str, message: str) -> str:
        git("checkout", "dev", cwd=self.work)
        target = self.work / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        git("add", "-A", cwd=self.work)
        git("commit", "-m", message, cwd=self.work)
        git("push", "origin", "dev", cwd=self.work)
        return git("rev-parse", "HEAD", cwd=self.work)

    def open_pr(self, pr: int, relpath: str, content: str, message: str) -> str:
        """Create a one-commit PR branch off dev, publish as refs/pull/N/head."""
        self._next_branch += 1
        branch = f"pr-{pr}-{self._next_branch}"
        git("checkout", "-b", branch, "dev", cwd=self.work)
        target = self.work / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        git("add", "-A", cwd=self.work)
        git("commit", "-m", message, cwd=self.work)
        sha = git("rev-parse", "HEAD", cwd=self.work)
        git("push", "origin", f"{branch}:refs/pull/{pr}/head", cwd=self.work)
        git("checkout", "dev", cwd=self.work)
        return sha

    def squash_merge_pr(self, pr_head_sha: str, message: str) -> str:
        """Squash-merge a PR head into dev, like GitHub's squash button."""
        git("checkout", "dev", cwd=self.work)
        git("merge", "--squash", pr_head_sha, cwd=self.work)
        git("commit", "-m", message, cwd=self.work)
        git("push", "origin", "dev", cwd=self.work)
        return git("rev-parse", "HEAD", cwd=self.work)


@pytest.fixture
def upstream(tmp_path: Path) -> Upstream:
    bare = tmp_path / "upstream.git"
    bare.mkdir()
    git("init", "--bare", "-b", "dev", str(bare), cwd=tmp_path)
    work = tmp_path / "upstream-work"
    git("clone", str(bare), str(work), cwd=tmp_path)
    git("checkout", "-B", "dev", cwd=work)
    (work / "src").mkdir()
    (work / "src" / "app.py").write_text("VERSION = 1\nGREETING = 'hi'\n", encoding="utf-8")
    git("add", "-A", cwd=work)
    git("commit", "-m", "initial dev", cwd=work)
    git("push", "-u", "origin", "dev", cwd=work)
    return Upstream(bare=bare, work=work)


@pytest.fixture
def checkout(tmp_path: Path, upstream: Upstream) -> Path:
    """The user's Odysseus install: a clone of upstream on branch dev."""
    dest = tmp_path / "checkout"
    git("clone", "-b", "dev", str(upstream.bare), str(dest), cwd=tmp_path)
    return dest
