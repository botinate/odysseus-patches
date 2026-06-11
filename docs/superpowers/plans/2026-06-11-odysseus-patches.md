# odysseus-patches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone CLI that applies open upstream Odysseus PRs as SHA-pinned patches on a generated `patched` branch, keeps them healthy across `git pull --ff-only` updates (auto-retire on merge, flag on conflict), plus an optional read-only MCP status server.

**Architecture:** Stdlib-only Python package (`odysseus_patches/`) with a pure-function update planner at the center; git and GitHub access are thin, injectable wrappers so the planner and orchestration are table-testable. The manifest (`data/patches/manifest.json` in the Odysseus checkout) is the source of truth; the `patched` branch is a disposable artifact rebuilt from it.

**Tech Stack:** Python ≥3.10, stdlib only (subprocess, urllib, json, dataclasses, argparse). Optional extra: `mcp` (status server). Dev: pytest. Spec: `docs/superpowers/specs/2026-06-11-odysseus-patches-design.md`.

**Working directory for all commands:** `/Users/root1/odysseus-patches`

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `LICENSE`
- Create: `odysseus_patches/__init__.py`
- Create: `tests/test_package.py`

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "odysseus-patches"
version = "0.1.0"
description = "Apply and manage upstream PR patches on a self-hosted Odysseus install"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "AGPL-3.0-or-later" }
dependencies = []

[project.optional-dependencies]
mcp = ["mcp>=1.0"]
dev = ["pytest>=8"]

[project.scripts]
odysseus-patches = "odysseus_patches.cli:main"

[tool.setuptools.packages.find]
include = ["odysseus_patches*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write .gitignore**

```
__pycache__/
*.pyc
*.egg-info/
dist/
build/
.venv/
.pytest_cache/
```

- [ ] **Step 3: Fetch the AGPL-3.0 license text**

Run: `curl -fsSL https://www.gnu.org/licenses/agpl-3.0.txt -o LICENSE && head -2 LICENSE`
Expected: `GNU AFFERO GENERAL PUBLIC LICENSE` / `Version 3, 19 November 2007`

- [ ] **Step 4: Write the package init and a smoke test**

`odysseus_patches/__init__.py`:
```python
"""odysseus-patches — apply upstream PR patches to a self-hosted Odysseus install."""

__version__ = "0.1.0"
```

`tests/test_package.py`:
```python
from odysseus_patches import __version__


def test_version():
    assert __version__ == "0.1.0"
```

- [ ] **Step 5: Create venv, install, run the smoke test**

Run:
```bash
python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]" && .venv/bin/python -m pytest -q
```
Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore LICENSE odysseus_patches/__init__.py tests/test_package.py
git commit -m "chore: scaffold package (stdlib core, AGPL-3.0, pytest)"
```

---

### Task 2: Manifest module

**Files:**
- Create: `odysseus_patches/manifest.py`
- Test: `tests/test_manifest.py`

The manifest is the source of truth. It must round-trip exactly, write atomically, fail loudly on corruption, and start empty when missing.

- [ ] **Step 1: Write the failing tests**

`tests/test_manifest.py`:
```python
import json

import pytest

from odysseus_patches.manifest import (
    Manifest,
    ManifestError,
    Patch,
    STATUS_ACTIVE,
    STATUS_RETIRED,
)


def make_patch(pr=3055, status=STATUS_ACTIVE):
    return Patch(
        pr=pr,
        title="fix(mcp): bust prompt cache",
        pinned_sha="a" * 40,
        status=status,
        added_at="2026-06-11T12:00:00Z",
        last_result="applied-clean",
    )


def test_missing_file_loads_empty(tmp_path):
    m = Manifest.load(tmp_path / "data" / "patches" / "manifest.json")
    assert m.patches == []
    assert m.upstream == "pewdiepie-archdaemon/odysseus"
    assert m.base_branch == "dev"


def test_round_trip(tmp_path):
    path = tmp_path / "manifest.json"
    m = Manifest.load(path)
    m.add(make_patch())
    m.save()
    again = Manifest.load(path)
    assert again.patches == m.patches
    assert again.get(3055).pinned_sha == "a" * 40
    assert again.get(9999) is None


def test_duplicate_add_raises(tmp_path):
    m = Manifest.load(tmp_path / "manifest.json")
    m.add(make_patch())
    with pytest.raises(ManifestError):
        m.add(make_patch())


def test_remove(tmp_path):
    m = Manifest.load(tmp_path / "manifest.json")
    m.add(make_patch())
    m.remove(3055)
    assert m.get(3055) is None
    with pytest.raises(ManifestError):
        m.remove(3055)


def test_corrupt_file_raises(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError):
        Manifest.load(path)


def test_active_patches_excludes_retired(tmp_path):
    m = Manifest.load(tmp_path / "manifest.json")
    m.add(make_patch(pr=1, status=STATUS_ACTIVE))
    m.add(make_patch(pr=2, status=STATUS_RETIRED))
    assert [p.pr for p in m.appliable_patches()] == [1]


def test_save_is_valid_json_on_disk(tmp_path):
    path = tmp_path / "manifest.json"
    m = Manifest.load(path)
    m.add(make_patch())
    m.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["patches"][0]["pr"] == 3055
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_manifest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'odysseus_patches.manifest'`

- [ ] **Step 3: Implement the manifest module**

`odysseus_patches/manifest.py`:
```python
"""Manifest: the source of truth for which PR patches this install carries.

Lives at <checkout>/data/patches/manifest.json — `data/` is Odysseus's
persistent, Docker-bind-mounted directory, so the manifest survives updates
and image rebuilds. The `patched` git branch is a disposable artifact rebuilt
from this file; never the other way around.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_UPSTREAM = "pewdiepie-archdaemon/odysseus"
DEFAULT_BASE_BRANCH = "dev"

STATUS_ACTIVE = "active"
STATUS_CONFLICTED = "conflicted"
STATUS_RETIRED = "retired"
STATUS_CLOSED_UPSTREAM = "closed-upstream"

# Statuses that still get (re)applied to the patched branch. Conflicted is
# retried every update — upstream movement can resolve a conflict. Closed
# PRs keep applying until the user explicitly removes them (spec decision).
APPLIABLE_STATUSES = {STATUS_ACTIVE, STATUS_CONFLICTED, STATUS_CLOSED_UPSTREAM}


class ManifestError(Exception):
    """Raised for duplicate/missing patches and unreadable manifest files."""


@dataclass
class Patch:
    pr: int
    title: str
    pinned_sha: str
    status: str = STATUS_ACTIVE
    added_at: str = ""
    last_result: str = ""


@dataclass
class Manifest:
    path: Path
    upstream: str = DEFAULT_UPSTREAM
    base_branch: str = DEFAULT_BASE_BRANCH
    patches: list[Patch] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        path = Path(path)
        if not path.exists():
            return cls(path=path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                path=path,
                upstream=data.get("upstream", DEFAULT_UPSTREAM),
                base_branch=data.get("base_branch", DEFAULT_BASE_BRANCH),
                patches=[Patch(**p) for p in data.get("patches", [])],
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise ManifestError(
                f"Unreadable manifest at {path}: {exc}. "
                "It is plain JSON — fix or delete it and re-add patches."
            ) from exc

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCHEMA_VERSION,
            "upstream": self.upstream,
            "base_branch": self.base_branch,
            "patches": [asdict(p) for p in self.patches],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, pr: int) -> Patch | None:
        for p in self.patches:
            if p.pr == pr:
                return p
        return None

    def add(self, patch: Patch) -> None:
        if self.get(patch.pr) is not None:
            raise ManifestError(f"PR #{patch.pr} is already tracked")
        self.patches.append(patch)

    def remove(self, pr: int) -> None:
        patch = self.get(pr)
        if patch is None:
            raise ManifestError(f"PR #{pr} is not tracked")
        self.patches.remove(patch)

    def appliable_patches(self) -> list[Patch]:
        return [p for p in self.patches if p.status in APPLIABLE_STATUSES]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_manifest.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add odysseus_patches/manifest.py tests/test_manifest.py
git commit -m "feat: manifest module — atomic JSON source of truth for tracked patches"
```

---

### Task 3: GitHub metadata access

**Files:**
- Create: `odysseus_patches/github.py`
- Test: `tests/test_github.py`

PR metadata via `gh` when available, plain REST otherwise; **any** failure degrades to `None` (the planner treats that as offline). Tests monkeypatch the two private fetchers — no network in tests.

- [ ] **Step 1: Write the failing tests**

`tests/test_github.py`:
```python
import json
import subprocess

import pytest

from odysseus_patches import github
from odysseus_patches.github import PRInfo, fetch_pr_info

SAMPLE = {
    "number": 3055,
    "title": "fix(mcp): bust prompt cache",
    "state": "closed",
    "merged": True,
    "head": {"sha": "b" * 40},
}


def test_parse_api_payload():
    info = github._parse_payload(SAMPLE)
    assert info == PRInfo(
        number=3055,
        title="fix(mcp): bust prompt cache",
        state="closed",
        merged=True,
        head_sha="b" * 40,
    )


def test_fetch_prefers_gh(monkeypatch):
    monkeypatch.setattr(github, "_via_gh", lambda upstream, pr: github._parse_payload(SAMPLE))
    monkeypatch.setattr(
        github, "_via_rest", lambda upstream, pr: (_ for _ in ()).throw(AssertionError("rest called"))
    )
    assert fetch_pr_info("o/r", 3055).merged is True


def test_fetch_falls_back_to_rest(monkeypatch):
    monkeypatch.setattr(
        github, "_via_gh", lambda upstream, pr: (_ for _ in ()).throw(FileNotFoundError("no gh"))
    )
    monkeypatch.setattr(github, "_via_rest", lambda upstream, pr: github._parse_payload(SAMPLE))
    assert fetch_pr_info("o/r", 3055).head_sha == "b" * 40


def test_fetch_offline_returns_none(monkeypatch):
    monkeypatch.setattr(
        github, "_via_gh", lambda upstream, pr: (_ for _ in ()).throw(FileNotFoundError("no gh"))
    )
    monkeypatch.setattr(
        github, "_via_rest", lambda upstream, pr: (_ for _ in ()).throw(OSError("offline"))
    )
    assert fetch_pr_info("o/r", 3055) is None


def test_via_gh_invokes_gh_api(monkeypatch):
    calls = {}

    def fake_run(cmd, capture_output, text, check, timeout):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(SAMPLE), stderr="")

    monkeypatch.setattr(github.subprocess, "run", fake_run)
    info = github._via_gh("o/r", 3055)
    assert calls["cmd"] == ["gh", "api", "repos/o/r/pulls/3055"]
    assert info.number == 3055
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_github.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'odysseus_patches.github'`

- [ ] **Step 3: Implement the GitHub module**

`odysseus_patches/github.py`:
```python
"""PR metadata from GitHub: `gh` CLI when present, anonymous REST otherwise.

Network failure is a supported state, not an error: fetch_pr_info returns
None and callers degrade (the planner re-applies pinned SHAs offline).
Patch *content* never comes from here — only `git fetch refs/pull/N/head`
in gitops.py fetches code.
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
from dataclasses import dataclass

TIMEOUT_SECONDS = 15


@dataclass
class PRInfo:
    number: int
    title: str
    state: str  # "open" | "closed"
    merged: bool
    head_sha: str


def _parse_payload(data: dict) -> PRInfo:
    return PRInfo(
        number=int(data["number"]),
        title=str(data["title"]),
        state=str(data["state"]),
        merged=bool(data.get("merged", False)),
        head_sha=str(data["head"]["sha"]),
    )


def _via_gh(upstream: str, pr: int) -> PRInfo:
    proc = subprocess.run(
        ["gh", "api", f"repos/{upstream}/pulls/{pr}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=TIMEOUT_SECONDS,
    )
    return _parse_payload(json.loads(proc.stdout))


def _via_rest(upstream: str, pr: int) -> PRInfo:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{upstream}/pulls/{pr}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "odysseus-patches",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return _parse_payload(json.loads(resp.read().decode("utf-8")))


def fetch_pr_info(upstream: str, pr: int) -> PRInfo | None:
    """Best-effort PR metadata. None means 'could not reach GitHub'."""
    for fetcher in (_via_gh, _via_rest):
        try:
            return fetcher(upstream, pr)
        except Exception:
            continue
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_github.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add odysseus_patches/github.py tests/test_github.py
git commit -m "feat: PR metadata via gh CLI with REST fallback; offline degrades to None"
```

---

### Task 4: Sandbox git fixtures

**Files:**
- Create: `tests/conftest.py`
- Test: `tests/test_fixtures.py`

A synthetic "upstream" (bare repo with a `dev` branch and fake `refs/pull/N/head` refs) plus a clone playing the user's install. Every gitops/update test builds on this. No network, hermetic git identity.

- [ ] **Step 1: Write the fixtures**

`tests/conftest.py`:
```python
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
    git("checkout", "-b", "dev", cwd=work)
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
```

`tests/test_fixtures.py`:
```python
from tests.conftest import git


def test_checkout_tracks_dev(checkout):
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=checkout) == "dev"
    assert (checkout / "src" / "app.py").exists()


def test_pr_ref_is_fetchable(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    git("fetch", "origin", "refs/pull/7/head", cwd=checkout)
    assert git("rev-parse", "FETCH_HEAD", cwd=checkout) == sha


def test_squash_merge_lands_on_dev(upstream, checkout):
    sha = upstream.open_pr(8, "src/fix.py", "FIX = True\n", "fix: something")
    upstream.squash_merge_pr(sha, "fix: something (#8)")
    git("pull", "--ff-only", cwd=checkout)
    assert (checkout / "src" / "fix.py").exists()
```

- [ ] **Step 2: Run the fixture tests**

Run: `.venv/bin/python -m pytest tests/test_fixtures.py -q`
Expected: `3 passed`

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py tests/test_fixtures.py
git commit -m "test: sandbox upstream + checkout fixtures with refs/pull simulation"
```

---

### Task 5: Git operations — repo wrapper

**Files:**
- Create: `odysseus_patches/gitops.py` (first half)
- Test: `tests/test_gitops.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_gitops.py`:
```python
import pytest

from odysseus_patches.gitops import GitError, GitRepo
from tests.conftest import git


def test_run_and_rev_parse(checkout):
    repo = GitRepo(checkout)
    assert repo.current_branch() == "dev"
    assert len(repo.rev_parse("HEAD")) == 40


def test_run_raises_giterror(checkout):
    repo = GitRepo(checkout)
    with pytest.raises(GitError):
        repo.run("rev-parse", "no-such-ref-xyz")


def test_is_dirty(checkout):
    repo = GitRepo(checkout)
    assert repo.is_dirty() is False
    (checkout / "src" / "app.py").write_text("VERSION = 99\n", encoding="utf-8")
    assert repo.is_dirty() is True


def test_fetch_pr_head_pins_sha(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    assert repo.fetch_pr_head(7) == sha
    # the ref is stored locally so offline re-applies keep working
    assert repo.rev_parse("refs/odypatches/pr/7") == sha


def test_diffstat_mentions_file(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    base = repo.merge_base("dev", sha)
    assert "src/fix.py" in repo.diffstat(base, sha)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gitops.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'odysseus_patches.gitops'`

- [ ] **Step 3: Implement the repo wrapper**

`odysseus_patches/gitops.py`:
```python
"""Git plumbing: a thin subprocess wrapper plus the patched-branch builder.

All patch content enters through `git fetch origin refs/pull/N/head` — these
refs live on the base repo for every PR regardless of fork, so no third-party
remote is ever added. Fetched heads are stored under refs/odypatches/pr/N so
re-applying pinned SHAs works offline.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .manifest import (
    Patch,
    STATUS_RETIRED,
)

PATCHED_BRANCH = "patched"
PR_REF = "refs/odypatches/pr/{pr}"

APPLY_OK = "applied"
APPLY_CONFLICT = "conflict"
APPLY_EMPTY = "empty"  # changes already present upstream -> retire


class GitError(Exception):
    pass


class GitRepo:
    def __init__(self, root: Path):
        self.root = Path(root)

    def run(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
            )
        return proc.stdout.strip()

    def current_branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD")

    def rev_parse(self, ref: str) -> str:
        return self.run("rev-parse", ref)

    def is_dirty(self) -> bool:
        return bool(self.run("status", "--porcelain"))

    def fetch_pr_head(self, pr: int) -> str:
        """Fetch refs/pull/N/head into a local ref; return its SHA."""
        local = PR_REF.format(pr=pr)
        self.run("fetch", "origin", f"refs/pull/{pr}/head:{local}", "--force")
        return self.rev_parse(local)

    def merge_base(self, a: str, b: str) -> str:
        return self.run("merge-base", a, b)

    def diffstat(self, base: str, head: str) -> str:
        return self.run("diff", "--stat", f"{base}..{head}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_gitops.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add odysseus_patches/gitops.py tests/test_gitops.py
git commit -m "feat: GitRepo wrapper — pr-ref fetch pinned under refs/odypatches"
```

---

### Task 6: Git operations — rebuild the patched branch

**Files:**
- Modify: `odysseus_patches/gitops.py` (append)
- Test: `tests/test_gitops_rebuild.py`

The core mechanism. `rebuild_patched` is idempotent: `checkout -B patched <base>`, then per patch squash-cherry-pick `merge-base..pinned`. Conflict → abort that pick, continue others. Empty result → "already upstream".

- [ ] **Step 1: Write the failing tests**

`tests/test_gitops_rebuild.py`:
```python
from odysseus_patches.gitops import (
    APPLY_CONFLICT,
    APPLY_EMPTY,
    APPLY_OK,
    GitRepo,
    PATCHED_BRANCH,
    rebuild_patched,
)
from odysseus_patches.manifest import Patch
from tests.conftest import git


def tracked(pr, sha, title="a fix"):
    return Patch(pr=pr, title=title, pinned_sha=sha)


def test_clean_apply_creates_branch_with_patch_commit(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)

    results = rebuild_patched(repo, "dev", [tracked(7, sha)])

    assert results == {7: APPLY_OK}
    assert repo.current_branch() == PATCHED_BRANCH
    assert (checkout / "src" / "fix.py").exists()
    log = git("log", "--oneline", "-1", cwd=checkout)
    assert "[patch] PR#7" in log


def test_conflict_is_skipped_and_others_apply(upstream, checkout):
    good = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: good")
    bad = upstream.open_pr(8, "src/app.py", "CONFLICT = 'pr'\n", "fix: bad")
    # upstream dev moves over the same file the bad PR touches
    upstream.commit_on_dev("src/app.py", "VERSION = 2\nGREETING = 'hi'\n", "bump")
    repo = GitRepo(checkout)
    repo.run("pull", "--ff-only")
    repo.fetch_pr_head(7)
    repo.fetch_pr_head(8)

    results = rebuild_patched(repo, "dev", [tracked(7, good), tracked(8, bad)])

    assert results[7] == APPLY_OK
    assert results[8] == APPLY_CONFLICT
    assert (checkout / "src" / "fix.py").exists()
    assert repo.is_dirty() is False  # aborted pick leaves nothing behind


def test_already_merged_content_reports_empty(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    upstream.squash_merge_pr(sha, "fix: something (#7)")
    repo = GitRepo(checkout)
    repo.run("pull", "--ff-only")
    repo.fetch_pr_head(7)

    results = rebuild_patched(repo, "dev", [tracked(7, sha)])

    assert results == {7: APPLY_EMPTY}


def test_no_patches_returns_to_base_and_drops_branch(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    rebuild_patched(repo, "dev", [tracked(7, sha)])

    results = rebuild_patched(repo, "dev", [])

    assert results == {}
    assert repo.current_branch() == "dev"
    branches = git("branch", "--list", PATCHED_BRANCH, cwd=checkout)
    assert branches == ""


def test_rebuild_is_idempotent(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    rebuild_patched(repo, "dev", [tracked(7, sha)])
    first = repo.rev_parse("HEAD^{tree}")
    rebuild_patched(repo, "dev", [tracked(7, sha)])
    assert repo.rev_parse("HEAD^{tree}") == first
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gitops_rebuild.py -q`
Expected: FAIL — `ImportError: cannot import name 'rebuild_patched'`

- [ ] **Step 3: Implement rebuild_patched (append to gitops.py)**

Append to `odysseus_patches/gitops.py`:
```python
def rebuild_patched(repo: GitRepo, base_branch: str, patches: list[Patch]) -> dict[int, str]:
    """Rebuild the patched branch from base + the given patches.

    Idempotent: the branch is recreated from scratch every time; the manifest
    is the source of truth and this branch is a build artifact. One failing
    patch never blocks the others. With no patches, the checkout returns to
    the base branch and the artifact branch is deleted.

    Returns {pr: APPLY_OK | APPLY_CONFLICT | APPLY_EMPTY}.
    """
    if not patches:
        if repo.current_branch() == PATCHED_BRANCH:
            repo.run("checkout", base_branch)
        repo.run("branch", "-D", PATCHED_BRANCH, check=False)
        return {}

    repo.run("checkout", "-B", PATCHED_BRANCH, base_branch)
    results: dict[int, str] = {}
    for patch in patches:
        local_ref = PR_REF.format(pr=patch.pr)
        base = repo.merge_base(PATCHED_BRANCH, patch.pinned_sha)
        proc = subprocess.run(
            [
                "git", "-c", "commit.gpgsign=false",
                "cherry-pick", "--no-commit", f"{base}..{patch.pinned_sha}",
            ],
            cwd=repo.root,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            subprocess.run(
                ["git", "cherry-pick", "--abort"],
                cwd=repo.root, capture_output=True, text=True,
            )
            repo.run("reset", "--hard", "HEAD")
            results[patch.pr] = APPLY_CONFLICT
            continue
        staged = repo.run("diff", "--cached", "--name-only")
        if not staged:
            repo.run("reset", "--hard", "HEAD")
            results[patch.pr] = APPLY_EMPTY
            continue
        repo.run("commit", "-m", f"[patch] PR#{patch.pr} {patch.title}")
        results[patch.pr] = APPLY_OK
        # keep the local pin ref alive even if fetch never reran
        repo.run("update-ref", local_ref, patch.pinned_sha)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_gitops_rebuild.py tests/test_gitops.py -q`
Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add odysseus_patches/gitops.py tests/test_gitops_rebuild.py
git commit -m "feat: idempotent patched-branch rebuild with conflict/empty isolation"
```

---

### Task 7: Offline squash-merge detection (patch-id scan)

**Files:**
- Modify: `odysseus_patches/gitops.py` (append)
- Test: `tests/test_patch_id_scan.py`

When GitHub is unreachable, detect "this patch's diff already landed on dev" by comparing `git patch-id` of the patch's squashed diff against the patch-ids of new upstream commits. Best-effort: a squash with review tweaks won't match (then the empty-pick detector in Task 6 catches it at apply time).

- [ ] **Step 1: Write the failing tests**

`tests/test_patch_id_scan.py`:
```python
from odysseus_patches.gitops import GitRepo, merged_upstream_prs
from odysseus_patches.manifest import Patch
from tests.conftest import git


def test_exact_squash_is_detected(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    old_dev = repo.rev_parse("dev")
    upstream.squash_merge_pr(sha, "fix: something (#7)")
    repo.run("checkout", "dev")
    repo.run("pull", "--ff-only")
    new_dev = repo.rev_parse("dev")

    patch = Patch(pr=7, title="fix: something", pinned_sha=sha)
    assert merged_upstream_prs(repo, old_dev, new_dev, [patch]) == {7}


def test_unmerged_pr_is_not_detected(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    old_dev = repo.rev_parse("dev")
    upstream.commit_on_dev("src/other.py", "OTHER = 1\n", "unrelated")
    repo.run("pull", "--ff-only")
    new_dev = repo.rev_parse("dev")

    patch = Patch(pr=7, title="fix: something", pinned_sha=sha)
    assert merged_upstream_prs(repo, old_dev, new_dev, [patch]) == set()


def test_no_upstream_movement_short_circuits(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    dev = repo.rev_parse("dev")
    patch = Patch(pr=7, title="fix: something", pinned_sha=sha)
    assert merged_upstream_prs(repo, dev, dev, [patch]) == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_patch_id_scan.py -q`
Expected: FAIL — `ImportError: cannot import name 'merged_upstream_prs'`

- [ ] **Step 3: Implement the scan (append to gitops.py)**

Append to `odysseus_patches/gitops.py`:
```python
def _patch_id_of_diff(repo: GitRepo, diff_text: str) -> str:
    """Stable patch-id for a diff, '' when the diff is empty."""
    if not diff_text.strip():
        return ""
    proc = subprocess.run(
        ["git", "patch-id", "--stable"],
        cwd=repo.root,
        input=diff_text,
        capture_output=True,
        text=True,
    )
    out = proc.stdout.strip()
    return out.split()[0] if out else ""


def merged_upstream_prs(
    repo: GitRepo, old_base: str, new_base: str, patches: list[Patch]
) -> set[int]:
    """Offline fallback for 'did this PR merge?': patch-id equivalence.

    Compares each patch's squashed diff against every commit that arrived on
    the base branch between old_base and new_base. Exact squash-merges match;
    merges with review tweaks won't (the empty-cherry-pick detector covers
    most of those at apply time). Best-effort by design.
    """
    if old_base == new_base or not patches:
        return set()
    upstream_ids = set()
    for sha in repo.run("rev-list", f"{old_base}..{new_base}").splitlines():
        diff = repo.run("diff-tree", "-p", "--no-commit-id", sha)
        pid = _patch_id_of_diff(repo, diff)
        if pid:
            upstream_ids.add(pid)
    merged = set()
    for patch in patches:
        base = repo.merge_base(old_base, patch.pinned_sha)
        diff = repo.run("diff", f"{base}..{patch.pinned_sha}")
        pid = _patch_id_of_diff(repo, diff)
        if pid and pid in upstream_ids:
            merged.add(patch.pr)
    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_patch_id_scan.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add odysseus_patches/gitops.py tests/test_patch_id_scan.py
git commit -m "feat: offline squash-merge detection via git patch-id equivalence"
```

---

### Task 8: Update planner (pure function)

**Files:**
- Create: `odysseus_patches/planner.py`
- Test: `tests/test_planner.py`

The decision core, free of git and network: `(patches, PR infos, offline-merged set) -> actions`. Every spec rule is one table row here.

- [ ] **Step 1: Write the failing tests**

`tests/test_planner.py`:
```python
from odysseus_patches.github import PRInfo
from odysseus_patches.manifest import (
    Patch,
    STATUS_ACTIVE,
    STATUS_CONFLICTED,
    STATUS_RETIRED,
)
from odysseus_patches.planner import (
    ACTION_REAPPLY,
    ACTION_RETIRE,
    ACTION_WARN_CLOSED,
    plan_update,
)

SHA = "a" * 40
MOVED = "b" * 40


def patch(pr=1, status=STATUS_ACTIVE):
    return Patch(pr=pr, title="t", pinned_sha=SHA, status=status)


def info(state="open", merged=False, head=SHA):
    return PRInfo(number=1, title="t", state=state, merged=merged, head_sha=head)


def plan_one(p, i, offline_merged=frozenset()):
    actions = plan_update([p], {p.pr: i}, set(offline_merged))
    assert len(actions) == 1
    return actions[0]


def test_merged_upstream_retires():
    a = plan_one(patch(), info(state="closed", merged=True))
    assert a.action == ACTION_RETIRE


def test_offline_patch_id_match_retires():
    a = plan_one(patch(), None, offline_merged={1})
    assert a.action == ACTION_RETIRE
    assert "patch-id" in a.reason


def test_closed_unmerged_warns_but_reapplies():
    a = plan_one(patch(), info(state="closed", merged=False))
    assert a.action == ACTION_WARN_CLOSED


def test_open_unchanged_reapplies():
    a = plan_one(patch(), info())
    assert a.action == ACTION_REAPPLY
    assert a.upgrade_available is False


def test_open_moved_head_flags_upgrade():
    a = plan_one(patch(), info(head=MOVED))
    assert a.action == ACTION_REAPPLY
    assert a.upgrade_available is True


def test_offline_reapplies_pinned():
    a = plan_one(patch(), None)
    assert a.action == ACTION_REAPPLY
    assert "offline" in a.reason


def test_conflicted_is_retried():
    a = plan_one(patch(status=STATUS_CONFLICTED), info())
    assert a.action == ACTION_REAPPLY


def test_retired_is_skipped():
    assert plan_update([patch(status=STATUS_RETIRED)], {1: info()}, set()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_planner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'odysseus_patches.planner'`

- [ ] **Step 3: Implement the planner**

`odysseus_patches/planner.py`:
```python
"""Pure update planner: manifest state + PR metadata in, actions out.

No git, no network, no I/O — every lifecycle rule from the spec lives here
as an easily table-tested branch.
"""
from __future__ import annotations

from dataclasses import dataclass

from .github import PRInfo
from .manifest import Patch, STATUS_RETIRED

ACTION_RETIRE = "retire"
ACTION_REAPPLY = "reapply"
ACTION_WARN_CLOSED = "warn-closed"


@dataclass
class PlannedAction:
    pr: int
    action: str
    upgrade_available: bool = False
    reason: str = ""


def plan_update(
    patches: list[Patch],
    infos: dict[int, PRInfo | None],
    offline_merged: set[int],
) -> list[PlannedAction]:
    actions: list[PlannedAction] = []
    for patch in patches:
        if patch.status == STATUS_RETIRED:
            continue
        info = infos.get(patch.pr)
        if info is not None and info.merged:
            actions.append(
                PlannedAction(patch.pr, ACTION_RETIRE, reason="merged upstream")
            )
        elif patch.pr in offline_merged:
            actions.append(
                PlannedAction(
                    patch.pr, ACTION_RETIRE, reason="patch-id match on new upstream commits"
                )
            )
        elif info is not None and info.state == "closed":
            actions.append(
                PlannedAction(
                    patch.pr, ACTION_WARN_CLOSED,
                    reason="PR closed without merging — keep or `remove` it",
                )
            )
        elif info is None:
            actions.append(
                PlannedAction(patch.pr, ACTION_REAPPLY, reason="offline — re-applying pinned SHA")
            )
        else:
            actions.append(
                PlannedAction(
                    patch.pr,
                    ACTION_REAPPLY,
                    upgrade_available=(info.head_sha != patch.pinned_sha),
                )
            )
    return actions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_planner.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add odysseus_patches/planner.py tests/test_planner.py
git commit -m "feat: pure update planner covering all lifecycle rules"
```

---

### Task 9: Update orchestration

**Files:**
- Create: `odysseus_patches/update.py`
- Test: `tests/test_update_integration.py`

Wires planner + gitops + github into the spec's `update` dance. The metadata fetcher is injected so integration tests run offline against the sandbox.

- [ ] **Step 1: Write the failing tests**

`tests/test_update_integration.py`:
```python
import pytest

from odysseus_patches.github import PRInfo
from odysseus_patches.gitops import GitRepo, PATCHED_BRANCH
from odysseus_patches.manifest import (
    Manifest,
    Patch,
    STATUS_ACTIVE,
    STATUS_CONFLICTED,
    STATUS_RETIRED,
)
from odysseus_patches.update import (
    EXIT_ATTENTION,
    EXIT_OK,
    EXIT_REBUILD,
    UpdateError,
    run_update,
)


def setup_tracked_pr(upstream, checkout, pr=7, path="src/fix.py"):
    sha = upstream.open_pr(pr, path, "FIX = True\n", f"fix: pr {pr}")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(pr)
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    manifest.add(Patch(pr=pr, title=f"fix: pr {pr}", pinned_sha=sha))
    manifest.save()
    return repo, manifest, sha


def online(infos):
    return lambda upstream, pr: infos.get(pr)


def test_open_pr_survives_update(upstream, checkout):
    repo, manifest, sha = setup_tracked_pr(upstream, checkout)
    upstream.commit_on_dev("src/other.py", "OTHER = 1\n", "unrelated upstream work")
    fetch = online({7: PRInfo(7, "fix: pr 7", "open", False, sha)})

    report, code = run_update(repo, manifest, fetch_info=fetch)

    assert code == EXIT_REBUILD
    assert repo.current_branch() == PATCHED_BRANCH
    assert (checkout / "src" / "other.py").exists()  # upstream work arrived
    assert (checkout / "src" / "fix.py").exists()    # patch still applied
    assert manifest.get(7).status == STATUS_ACTIVE


def test_merged_pr_is_retired(upstream, checkout):
    repo, manifest, sha = setup_tracked_pr(upstream, checkout)
    upstream.squash_merge_pr(sha, "fix: pr 7 (#7)")
    fetch = online({7: PRInfo(7, "fix: pr 7", "closed", True, sha)})

    report, code = run_update(repo, manifest, fetch_info=fetch)

    assert code == EXIT_REBUILD
    assert manifest.get(7).status == STATUS_RETIRED
    assert repo.current_branch() == "dev"  # no active patches left
    assert (checkout / "src" / "fix.py").exists()  # via upstream now


def test_offline_squash_merge_still_retires(upstream, checkout):
    repo, manifest, sha = setup_tracked_pr(upstream, checkout)
    upstream.squash_merge_pr(sha, "fix: pr 7 (#7)")

    report, code = run_update(repo, manifest, fetch_info=lambda u, p: None)

    assert manifest.get(7).status == STATUS_RETIRED


def test_conflict_marks_and_continues(upstream, checkout):
    repo, manifest, sha = setup_tracked_pr(upstream, checkout, pr=8, path="src/app.py")
    upstream.commit_on_dev("src/app.py", "VERSION = 2\nGREETING = 'hi'\n", "bump")
    fetch = online({8: PRInfo(8, "fix: pr 8", "open", False, sha)})

    report, code = run_update(repo, manifest, fetch_info=fetch)

    assert code == EXIT_ATTENTION
    assert manifest.get(8).status == STATUS_CONFLICTED


def test_dirty_tree_refuses(upstream, checkout):
    repo, manifest, _ = setup_tracked_pr(upstream, checkout)
    (checkout / "src" / "app.py").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(UpdateError):
        run_update(repo, manifest, fetch_info=lambda u, p: None)


def test_no_patches_plain_update(upstream, checkout):
    repo = GitRepo(checkout)
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    upstream.commit_on_dev("src/other.py", "OTHER = 1\n", "work")

    report, code = run_update(repo, manifest, fetch_info=lambda u, p: None)

    assert code == EXIT_OK
    assert repo.current_branch() == "dev"
    assert (checkout / "src" / "other.py").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_update_integration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'odysseus_patches.update'`

- [ ] **Step 3: Implement the orchestration**

`odysseus_patches/update.py`:
```python
"""The update dance: pull upstream, reconcile every patch, rebuild the branch.

Exit codes are machine-readable for wrapper scripts (update_windows.bat etc):
0 = nothing changed; 10 = updated, rebuild/restart needed; 20 = updated but
one or more patches need attention; errors raise UpdateError (CLI maps to 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import github
from .github import PRInfo
from .gitops import (
    APPLY_CONFLICT,
    APPLY_EMPTY,
    APPLY_OK,
    GitRepo,
    merged_upstream_prs,
    rebuild_patched,
)
from .manifest import (
    Manifest,
    STATUS_ACTIVE,
    STATUS_CLOSED_UPSTREAM,
    STATUS_CONFLICTED,
    STATUS_RETIRED,
)
from .planner import (
    ACTION_REAPPLY,
    ACTION_RETIRE,
    ACTION_WARN_CLOSED,
    PlannedAction,
    plan_update,
)

EXIT_OK = 0
EXIT_REBUILD = 10
EXIT_ATTENTION = 20

FetchInfo = Callable[[str, int], PRInfo | None]


class UpdateError(Exception):
    pass


@dataclass
class UpdateReport:
    old_base: str = ""
    new_base: str = ""
    actions: list[PlannedAction] = field(default_factory=list)
    apply_results: dict[int, str] = field(default_factory=dict)

    @property
    def pulled(self) -> bool:
        return self.old_base != self.new_base

    @property
    def attention_needed(self) -> bool:
        return APPLY_CONFLICT in self.apply_results.values()


def run_update(
    repo: GitRepo,
    manifest: Manifest,
    fetch_info: FetchInfo | None = None,
) -> tuple[UpdateReport, int]:
    if fetch_info is None:
        # resolved at call time (not def time) so tests can monkeypatch
        # odysseus_patches.github.fetch_pr_info and the CLI picks it up
        fetch_info = github.fetch_pr_info
    if repo.is_dirty():
        raise UpdateError(
            "Working tree has uncommitted changes — commit, stash, or discard "
            "them first (patches never live as dirty files; this is your own work)."
        )
    report = UpdateReport()
    base = manifest.base_branch

    repo.run("checkout", base)
    report.old_base = repo.rev_parse("HEAD")
    repo.run("pull", "--ff-only")
    report.new_base = repo.rev_parse("HEAD")

    tracked = [p for p in manifest.patches if p.status != STATUS_RETIRED]
    infos = {p.pr: fetch_info(manifest.upstream, p.pr) for p in tracked}
    offline_merged = merged_upstream_prs(repo, report.old_base, report.new_base, tracked)
    report.actions = plan_update(tracked, infos, offline_merged)

    for action in report.actions:
        patch = manifest.get(action.pr)
        if action.action == ACTION_RETIRE:
            patch.status = STATUS_RETIRED
            patch.last_result = action.reason
        elif action.action == ACTION_WARN_CLOSED:
            patch.status = STATUS_CLOSED_UPSTREAM

    report.apply_results = rebuild_patched(repo, base, manifest.appliable_patches())

    for pr, result in report.apply_results.items():
        patch = manifest.get(pr)
        if result == APPLY_CONFLICT:
            patch.status = STATUS_CONFLICTED
            patch.last_result = "conflict"
        elif result == APPLY_EMPTY:
            patch.status = STATUS_RETIRED
            patch.last_result = "already-upstream"
        elif result == APPLY_OK:
            if patch.status == STATUS_CONFLICTED:
                patch.status = STATUS_ACTIVE
            patch.last_result = "applied-clean"

    # an empty-pick retire can leave the branch carrying nothing useful;
    # rebuild once more so the artifact matches the manifest exactly
    if APPLY_EMPTY in report.apply_results.values():
        rebuild_patched(repo, base, manifest.appliable_patches())

    manifest.save()

    if report.attention_needed:
        return report, EXIT_ATTENTION
    if report.pulled or report.apply_results:
        return report, EXIT_REBUILD
    return report, EXIT_OK
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_update_integration.py -q`
Expected: `6 passed`

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all passing (35 tests at this point)

- [ ] **Step 6: Commit**

```bash
git add odysseus_patches/update.py tests/test_update_integration.py
git commit -m "feat: update orchestration — pull, reconcile, rebuild, report"
```

---

### Task 10: CLI — add / list / show / remove

**Files:**
- Create: `odysseus_patches/cli.py`
- Create: `bin/odysseus-patches`
- Test: `tests/test_cli.py`

argparse subcommands operating on a checkout found via `-C` or upward walk from cwd. `add` requires network (you must review what you apply), pins the fetched ref's SHA, and **rolls back on conflict** — a patch that never applied isn't tracked.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:
```python
import pytest

from odysseus_patches import cli, github
from odysseus_patches.github import PRInfo
from odysseus_patches.gitops import GitRepo, PATCHED_BRANCH
from odysseus_patches.manifest import Manifest


def manifest_of(checkout):
    return Manifest.load(checkout / "data" / "patches" / "manifest.json")


def fake_info(monkeypatch, infos):
    monkeypatch.setattr(github, "fetch_pr_info", lambda upstream, pr: infos.get(pr))


def test_add_applies_and_tracks(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: something", "open", False, sha)})

    code = cli.main(["-C", str(checkout), "add", "7", "--yes"])

    assert code == 0
    assert manifest_of(checkout).get(7).pinned_sha == sha
    assert GitRepo(checkout).current_branch() == PATCHED_BRANCH
    assert "src/fix.py" in capsys.readouterr().out


def test_add_offline_errors(upstream, checkout, monkeypatch, capsys):
    fake_info(monkeypatch, {})
    code = cli.main(["-C", str(checkout), "add", "7", "--yes"])
    assert code == 1
    assert "GitHub" in capsys.readouterr().err


def test_add_conflict_rolls_back(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(8, "src/app.py", "CONFLICT = 'pr'\n", "fix: bad")
    upstream.commit_on_dev("src/app.py", "VERSION = 2\nGREETING = 'hi'\n", "bump")
    repo = GitRepo(checkout)
    repo.run("pull", "--ff-only")
    fake_info(monkeypatch, {8: PRInfo(8, "fix: bad", "open", False, sha)})

    code = cli.main(["-C", str(checkout), "add", "8", "--yes"])

    assert code == 1
    assert manifest_of(checkout).get(8) is None
    assert repo.current_branch() == "dev"


def test_list_shows_patches(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: something", "open", False, sha)})
    cli.main(["-C", str(checkout), "add", "7", "--yes"])
    capsys.readouterr()

    code = cli.main(["-C", str(checkout), "list"])

    out = capsys.readouterr().out
    assert code == 0
    assert "7" in out and "active" in out and sha[:10] in out


def test_show_prints_diff(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: something", "open", False, sha)})
    cli.main(["-C", str(checkout), "add", "7", "--yes"])
    capsys.readouterr()

    code = cli.main(["-C", str(checkout), "show", "7"])

    out = capsys.readouterr().out
    assert code == 0
    assert "FIX = True" in out


def test_remove_untracks_and_rebuilds(upstream, checkout, monkeypatch, capsys):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: something", "open", False, sha)})
    cli.main(["-C", str(checkout), "add", "7", "--yes"])

    code = cli.main(["-C", str(checkout), "remove", "7"])

    assert code == 0
    assert manifest_of(checkout).get(7) is None
    assert GitRepo(checkout).current_branch() == "dev"
    assert not (checkout / "src" / "fix.py").exists()


def test_not_a_git_checkout_errors(tmp_path, capsys):
    code = cli.main(["-C", str(tmp_path), "list"])
    assert code == 1
    assert "git checkout" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'odysseus_patches.cli'`

- [ ] **Step 3: Implement the CLI (first four commands)**

`odysseus_patches/cli.py`:
```python
"""Apply and manage upstream PR patches on this Odysseus install.

This first docstring line doubles as the help text upstream's `odysseus`
dispatcher displays if this file ever migrates into their scripts/ dir.
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from . import github
from .gitops import APPLY_OK, GitError, GitRepo, rebuild_patched
from .manifest import Manifest, ManifestError, Patch
from .update import UpdateError, run_update

MANIFEST_RELPATH = Path("data") / "patches" / "manifest.json"


class CliError(Exception):
    pass


def find_checkout(start: Path) -> Path:
    p = Path(start).resolve()
    for candidate in (p, *p.parents):
        if (candidate / ".git").exists():
            return candidate
    raise CliError(
        f"{start} is not inside a git checkout — point -C at your Odysseus "
        "install (zip downloads can't be patched; clone the repo instead)."
    )


def load(checkout: Path) -> tuple[GitRepo, Manifest]:
    repo = GitRepo(checkout)
    manifest = Manifest.load(checkout / MANIFEST_RELPATH)
    return repo, manifest


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{prompt} [y/N] ").strip().lower() == "y"


def cmd_add(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    info = github.fetch_pr_info(manifest.upstream, args.pr)
    if info is None:
        raise CliError(
            "Could not reach GitHub — adding a patch requires reviewing live "
            "PR metadata. Check your connection and retry."
        )
    if info.merged:
        raise CliError(f"PR #{args.pr} is already merged upstream — just update Odysseus.")
    sha = repo.fetch_pr_head(args.pr)
    base = repo.merge_base(manifest.base_branch, sha)
    print(f"PR #{info.number}: {info.title} [{info.state}]")
    print(f"pinning: {sha}")
    print(repo.diffstat(base, sha))
    if args.show:
        print(repo.run("diff", f"{base}..{sha}"))
    if not confirm("Apply this patch?", args.yes):
        print("aborted")
        return 0
    manifest.add(
        Patch(
            pr=info.number,
            title=info.title,
            pinned_sha=sha,
            added_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
    )
    results = rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
    if results.get(args.pr) != APPLY_OK:
        manifest.remove(args.pr)
        rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
        raise CliError(
            f"PR #{args.pr} does not apply cleanly ({results.get(args.pr)}) — "
            "it may need a rebase upstream. Nothing was changed."
        )
    patch = manifest.get(args.pr)
    patch.last_result = "applied-clean"
    manifest.save()
    print(f"applied PR #{args.pr} — restart/rebuild Odysseus to run it")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    _, manifest = load(checkout)
    if not manifest.patches:
        print("no patches tracked")
        return 0
    print(f"{'PR':>6}  {'STATUS':<16} {'PINNED':<12} TITLE")
    for p in manifest.patches:
        print(f"#{p.pr:>5}  {p.status:<16} {p.pinned_sha[:10]:<12} {p.title}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    patch = manifest.get(args.pr)
    if patch is None:
        raise CliError(f"PR #{args.pr} is not tracked")
    print(f"PR #{patch.pr}: {patch.title}")
    print(f"status: {patch.status}   pinned: {patch.pinned_sha}   last: {patch.last_result}")
    base = repo.merge_base(manifest.base_branch, patch.pinned_sha)
    print(repo.run("diff", f"{base}..{patch.pinned_sha}"))
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    manifest.remove(args.pr)
    rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
    manifest.save()
    print(f"removed PR #{args.pr}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odysseus-patches",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument(
        "-C", "--checkout", default=".",
        help="path to (or inside) the Odysseus git checkout (default: cwd)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="apply an open upstream PR as a pinned patch")
    p_add.add_argument("pr", type=int)
    p_add.add_argument("--yes", action="store_true", help="skip confirmation")
    p_add.add_argument("--show", action="store_true", help="print the full diff before confirming")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="show tracked patches and their status")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show one patch's status and full diff")
    p_show.add_argument("pr", type=int)
    p_show.set_defaults(func=cmd_show)

    p_remove = sub.add_parser("remove", help="untrack a patch and rebuild without it")
    p_remove.add_argument("pr", type=int)
    p_remove.set_defaults(func=cmd_remove)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (CliError, ManifestError, GitError, UpdateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write the bin launcher (upstream scripts/odysseus-* conventions)**

`bin/odysseus-patches`:
```python
#!/usr/bin/env python3
"""Apply and manage upstream PR patches on this Odysseus install."""
import sys
from pathlib import Path

try:
    from odysseus_patches.cli import main
except ImportError:
    # running in-place from a source checkout (or upstream scripts/ after
    # migration, with the lib vendored next to this file)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from odysseus_patches.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

Run: `chmod +x bin/odysseus-patches`

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add odysseus_patches/cli.py bin/odysseus-patches tests/test_cli.py
git commit -m "feat: CLI add/list/show/remove with rollback-on-conflict add"
```

---

### Task 11: CLI — update and upgrade

**Files:**
- Modify: `odysseus_patches/cli.py`
- Test: `tests/test_cli_update.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_cli_update.py`:
```python
from odysseus_patches import cli, github
from odysseus_patches.github import PRInfo
from odysseus_patches.manifest import Manifest


def manifest_of(checkout):
    return Manifest.load(checkout / "data" / "patches" / "manifest.json")


def fake_info(monkeypatch, infos):
    monkeypatch.setattr(github, "fetch_pr_info", lambda upstream, pr: infos.get(pr))


def add_pr(upstream, checkout, monkeypatch, pr=7, path="src/fix.py", content="FIX = True\n"):
    sha = upstream.open_pr(pr, path, content, f"fix: pr {pr}")
    fake_info(monkeypatch, {pr: PRInfo(pr, f"fix: pr {pr}", "open", False, sha)})
    assert cli.main(["-C", str(checkout), "add", str(pr), "--yes"]) == 0
    return sha


def test_update_retires_merged(upstream, checkout, monkeypatch, capsys):
    sha = add_pr(upstream, checkout, monkeypatch)
    upstream.squash_merge_pr(sha, "fix: pr 7 (#7)")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: pr 7", "closed", True, sha)})

    code = cli.main(["-C", str(checkout), "update"])

    out = capsys.readouterr().out
    assert code == 10  # EXIT_REBUILD
    assert "retired" in out
    assert manifest_of(checkout).get(7).status == "retired"


def test_update_reports_upgrade_available(upstream, checkout, monkeypatch, capsys):
    sha = add_pr(upstream, checkout, monkeypatch)
    new_sha = upstream.open_pr(7, "src/fix.py", "FIX = 2\n", "fix: pr 7 v2")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: pr 7", "open", False, new_sha)})

    code = cli.main(["-C", str(checkout), "update"])

    out = capsys.readouterr().out
    assert "upgrade available" in out
    assert manifest_of(checkout).get(7).pinned_sha == sha  # still pinned


def test_upgrade_repins_after_confirm(upstream, checkout, monkeypatch, capsys):
    add_pr(upstream, checkout, monkeypatch)
    new_sha = upstream.open_pr(7, "src/fix.py", "FIX = 2\n", "fix: pr 7 v2")
    fake_info(monkeypatch, {7: PRInfo(7, "fix: pr 7", "open", False, new_sha)})

    code = cli.main(["-C", str(checkout), "upgrade", "7", "--yes"])

    assert code == 0
    assert manifest_of(checkout).get(7).pinned_sha == new_sha
    assert (checkout / "src" / "fix.py").read_text() == "FIX = 2\n"


def test_upgrade_up_to_date(upstream, checkout, monkeypatch, capsys):
    sha = add_pr(upstream, checkout, monkeypatch)
    fake_info(monkeypatch, {7: PRInfo(7, "fix: pr 7", "open", False, sha)})

    code = cli.main(["-C", str(checkout), "upgrade", "7", "--yes"])

    assert code == 0
    assert "up to date" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli_update.py -q`
Expected: FAIL — `SystemExit` / argparse error: `invalid choice: 'update'`

- [ ] **Step 3: Implement update + upgrade commands**

Append to `odysseus_patches/cli.py` (before `build_parser`), and register both in `build_parser`:

```python
def cmd_update(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    report, code = run_update(repo, manifest)
    if report.pulled:
        print(f"pulled {manifest.base_branch}: {report.old_base[:10]} -> {report.new_base[:10]}")
    else:
        print(f"{manifest.base_branch} already up to date")
    for action in report.actions:
        patch = manifest.get(action.pr)
        line = f"PR #{action.pr}: "
        if patch.status == "retired":
            line += f"retired ({patch.last_result})"
        elif patch.status == "conflicted":
            line += "CONFLICT — run `odysseus-patches show " + str(action.pr) + "`"
        else:
            line += patch.last_result or "ok"
        if action.upgrade_available:
            line += "  [upgrade available: `odysseus-patches upgrade " + str(action.pr) + "`]"
        if action.reason:
            line += f"  ({action.reason})"
        print(line)
    if code == 10:
        print("done — rebuild/restart Odysseus to run the updated code")
    elif code == 20:
        print("done with warnings — at least one patch needs attention")
    return code


def cmd_upgrade(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    patch = manifest.get(args.pr)
    if patch is None:
        raise CliError(f"PR #{args.pr} is not tracked")
    info = github.fetch_pr_info(manifest.upstream, args.pr)
    if info is None:
        raise CliError("Could not reach GitHub — upgrading requires reviewing the new commits.")
    new_sha = repo.fetch_pr_head(args.pr)
    if new_sha == patch.pinned_sha:
        print(f"PR #{args.pr} is up to date (pinned {patch.pinned_sha[:10]})")
        return 0
    print(f"PR #{args.pr} moved: {patch.pinned_sha[:10]} -> {new_sha[:10]}")
    print("incremental diff:")
    print(repo.run("diff", f"{patch.pinned_sha}..{new_sha}"))
    if not confirm("Adopt the new commits?", args.yes):
        print("aborted")
        return 0
    old_sha = patch.pinned_sha
    patch.pinned_sha = new_sha
    results = rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
    if results.get(args.pr) != APPLY_OK:
        patch.pinned_sha = old_sha
        rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
        raise CliError(
            f"upgraded PR #{args.pr} does not apply cleanly — kept the old pin."
        )
    patch.title = info.title
    patch.last_result = "applied-clean"
    manifest.save()
    print(f"re-pinned PR #{args.pr} to {new_sha[:10]}")
    return 0
```

In `build_parser`, add after the `remove` block:
```python
    p_update = sub.add_parser("update", help="pull upstream and reconcile every patch")
    p_update.set_defaults(func=cmd_update)

    p_upgrade = sub.add_parser("upgrade", help="re-pin a patch to its PR's new head")
    p_upgrade.add_argument("pr", type=int)
    p_upgrade.add_argument("--yes", action="store_true", help="skip confirmation")
    p_upgrade.set_defaults(func=cmd_upgrade)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli_update.py tests/test_cli.py -q`
Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
git add odysseus_patches/cli.py tests/test_cli_update.py
git commit -m "feat: CLI update (machine-readable exit codes) and upgrade (review + re-pin)"
```

---

### Task 12: install-hook command

**Files:**
- Create: `odysseus_patches/hooks.py`
- Modify: `odysseus_patches/cli.py`
- Test: `tests/test_install_hook.py`

Replaces the `git pull --ff-only` line in a local update script with an `odysseus-patches update` call, marker-commented and idempotent. A `.bak` of the original is kept.

- [ ] **Step 1: Write the failing tests**

`tests/test_install_hook.py`:
```python
import pytest

from odysseus_patches.hooks import HookError, install_hook

BAT = (
    'pushd "%~dp0"\r\n'
    "where git\r\n"
    "git pull --ff-only\r\n"
    "docker compose up -d --build\r\n"
)


def test_install_replaces_pull_line(tmp_path):
    script = tmp_path / "update_windows.bat"
    script.write_text(BAT, encoding="utf-8")

    changed = install_hook(script)

    text = script.read_text(encoding="utf-8")
    assert changed is True
    assert "odysseus-patches update" in text
    assert "git pull --ff-only" not in text.replace(":: odysseus-patches hook (was: git pull --ff-only)", "")
    assert (tmp_path / "update_windows.bat.bak").read_text(encoding="utf-8") == BAT


def test_install_is_idempotent(tmp_path):
    script = tmp_path / "update_windows.bat"
    script.write_text(BAT, encoding="utf-8")
    install_hook(script)
    once = script.read_text(encoding="utf-8")

    changed = install_hook(script)

    assert changed is False
    assert script.read_text(encoding="utf-8") == once


def test_no_pull_line_raises(tmp_path):
    script = tmp_path / "update.sh"
    script.write_text("echo no pull here\n", encoding="utf-8")
    with pytest.raises(HookError):
        install_hook(script)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_install_hook.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'odysseus_patches.hooks'`

- [ ] **Step 3: Implement the hook installer**

`odysseus_patches/hooks.py`:
```python
"""Wire `odysseus-patches update` into a local update script.

The local update script is itself a local modification — managing it
idempotently (marker comment, .bak backup) is squarely this tool's job.
"""
from __future__ import annotations

from pathlib import Path

HOOK_MARKER = "odysseus-patches hook"
PULL_LINE = "git pull --ff-only"


class HookError(Exception):
    pass


def install_hook(script_path: Path) -> bool:
    """Replace the ff-only pull with an odysseus-patches update call.

    Returns True when the script was modified, False when already hooked.
    """
    script_path = Path(script_path)
    text = script_path.read_text(encoding="utf-8")
    if HOOK_MARKER in text:
        return False
    if PULL_LINE not in text:
        raise HookError(
            f"{script_path} contains no '{PULL_LINE}' line to hook — "
            "edit it manually or run `odysseus-patches update` yourself."
        )
    comment = "::" if script_path.suffix.lower() == ".bat" else "#"
    newline = "\r\n" if "\r\n" in text else "\n"
    replacement = (
        f"{comment} {HOOK_MARKER} (was: {PULL_LINE}){newline}"
        f"odysseus-patches update"
    )
    script_path.with_suffix(script_path.suffix + ".bak").write_text(text, encoding="utf-8")
    script_path.write_text(text.replace(PULL_LINE, replacement, 1), encoding="utf-8")
    return True
```

- [ ] **Step 4: Register the CLI command**

Append to `odysseus_patches/cli.py` (before `build_parser`):
```python
def cmd_install_hook(args: argparse.Namespace) -> int:
    from .hooks import install_hook

    changed = install_hook(Path(args.script))
    print("hook installed" if changed else "already hooked — nothing to do")
    return 0
```

In `build_parser`, add after the `upgrade` block:
```python
    p_hook = sub.add_parser(
        "install-hook", help="make a local update script call `odysseus-patches update`"
    )
    p_hook.add_argument("script", help="path to e.g. update_windows.bat")
    p_hook.set_defaults(func=cmd_install_hook)
```

And add `HookError` to the `except` clause in `main`:
```python
    except (CliError, ManifestError, GitError, UpdateError, HookError) as exc:
```
with the import at the top of `cli.py`:
```python
from .hooks import HookError
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_install_hook.py -q`
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add odysseus_patches/hooks.py odysseus_patches/cli.py tests/test_install_hook.py
git commit -m "feat: install-hook — idempotent update-script wiring with backup"
```

---

### Task 13: Read-only MCP status server

**Files:**
- Create: `odysseus_patches/status.py`
- Create: `odysseus_patches/mcp_server.py`
- Test: `tests/test_status.py`

The data layer (`status.py`) is plain functions, fully tested. The MCP wrapper (`mcp_server.py`) is a thin shell over it, lazily importing `mcp` (optional extra), modeled on upstream's `mcp_servers/*.py` stdio pattern. Strictly read-only: no writes, no git mutation.

- [ ] **Step 1: Write the failing tests**

`tests/test_status.py`:
```python
from odysseus_patches.gitops import GitRepo, rebuild_patched
from odysseus_patches.manifest import Manifest, Patch
from odysseus_patches.status import build_status


def test_status_empty(checkout):
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    status = build_status(GitRepo(checkout), manifest)
    assert status["patch_count"] == 0
    assert status["on_patched_branch"] is False
    assert status["healthy"] is True


def test_status_with_applied_patch(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: something")
    repo = GitRepo(checkout)
    repo.fetch_pr_head(7)
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    manifest.add(Patch(pr=7, title="fix: something", pinned_sha=sha, last_result="applied-clean"))
    rebuild_patched(repo, "dev", manifest.appliable_patches())
    manifest.save()

    status = build_status(repo, manifest)

    assert status["patch_count"] == 1
    assert status["on_patched_branch"] is True
    assert status["healthy"] is True
    assert status["patches"][0]["pr"] == 7
    assert status["patches"][0]["status"] == "active"


def test_status_flags_conflicted_as_unhealthy(checkout):
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    manifest.add(Patch(pr=8, title="bad", pinned_sha="c" * 40, status="conflicted"))
    status = build_status(GitRepo(checkout), manifest)
    assert status["healthy"] is False
    assert "conflicted" in status["attention"][0]


def test_status_flags_active_patches_while_on_base_branch(upstream, checkout):
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    manifest.add(Patch(pr=7, title="t", pinned_sha="a" * 40, status="active"))
    status = build_status(GitRepo(checkout), manifest)  # still on dev
    assert status["healthy"] is False
    assert any("not running" in line for line in status["attention"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_status.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'odysseus_patches.status'`

- [ ] **Step 3: Implement the status builder**

`odysseus_patches/status.py`:
```python
"""Read-only status snapshot consumed by the CLI and the MCP server."""
from __future__ import annotations

from dataclasses import asdict

from .gitops import GitRepo, PATCHED_BRANCH
from .manifest import Manifest, STATUS_CONFLICTED


def build_status(repo: GitRepo, manifest: Manifest) -> dict:
    appliable = manifest.appliable_patches()
    on_patched = repo.current_branch() == PATCHED_BRANCH
    attention: list[str] = []
    for p in manifest.patches:
        if p.status == STATUS_CONFLICTED:
            attention.append(
                f"PR #{p.pr} is conflicted — `odysseus-patches show {p.pr}` for details"
            )
    if appliable and not on_patched:
        attention.append(
            "patches are tracked but the checkout is not running the patched "
            "branch — run `odysseus-patches update`"
        )
    return {
        "upstream": manifest.upstream,
        "base_branch": manifest.base_branch,
        "on_patched_branch": on_patched,
        "patch_count": len(manifest.patches),
        "patches": [asdict(p) for p in manifest.patches],
        "attention": attention,
        "healthy": not attention,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_status.py -q`
Expected: `4 passed`

- [ ] **Step 5: Write the MCP server shell**

`odysseus_patches/mcp_server.py`:
```python
"""Optional read-only MCP server: install state for the Odysseus agent.

Add via Odysseus's integrations tab (stdio transport):
  command: odysseus-patches-mcp   (or: python -m odysseus_patches.mcp_server)
  args:    ["--checkout", "/path/to/odysseus"]

Requires the 'mcp' extra: pip install 'odysseus-patches[mcp]'.
Strictly read-only — the agent can report patch state, never change it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    try:
        import asyncio

        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError:
        print(
            "the 'mcp' package is required: pip install 'odysseus-patches[mcp]'",
            file=sys.stderr,
        )
        return 1

    from .cli import MANIFEST_RELPATH, find_checkout
    from .gitops import GitRepo
    from .manifest import Manifest
    from .status import build_status

    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", default=".")
    args = parser.parse_args()
    checkout = find_checkout(Path(args.checkout))

    server = Server("odysseus-patches")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="list_patches",
                description=(
                    "List the upstream PR patches applied to this Odysseus "
                    "install: PR number, title, pinned commit, and status "
                    "(active/conflicted/retired/closed-upstream)."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="patch_status",
                description=(
                    "Overall patch health for this install: whether the "
                    "patched branch is running and anything needing attention."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        repo = GitRepo(checkout)
        manifest = Manifest.load(checkout / MANIFEST_RELPATH)
        status = build_status(repo, manifest)
        if name == "list_patches":
            payload = status["patches"]
        elif name == "patch_status":
            payload = {k: v for k, v in status.items() if k != "patches"}
        else:
            return [TextContent(type="text", text=f"unknown tool: {name}")]
        return [TextContent(type="text", text=json.dumps(payload, indent=2))]

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Add the entry point in `pyproject.toml` under `[project.scripts]`:
```toml
odysseus-patches-mcp = "odysseus_patches.mcp_server:main"
```

- [ ] **Step 6: Run the full suite (mcp_server has no unit tests — its logic lives in status.py)**

Run: `.venv/bin/python -m pytest -q`
Expected: all passing

- [ ] **Step 7: Commit**

```bash
git add odysseus_patches/status.py odysseus_patches/mcp_server.py pyproject.toml tests/test_status.py
git commit -m "feat: status builder + optional read-only MCP server"
```

---

### Task 14: README, status in CLI, final verification

**Files:**
- Create: `README.md`
- Modify: `odysseus_patches/cli.py` (add `status` subcommand)
- Test: `tests/test_cli_status.py`

- [ ] **Step 1: Write the failing test for `status`**

`tests/test_cli_status.py`:
```python
import json

from odysseus_patches import cli


def test_status_outputs_json(checkout, capsys):
    code = cli.main(["-C", str(checkout), "status"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["patch_count"] == 0
    assert data["healthy"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_status.py -q`
Expected: FAIL — argparse error: `invalid choice: 'status'`

- [ ] **Step 3: Implement `status` (append to cli.py, register in build_parser)**

```python
def cmd_status(args: argparse.Namespace) -> int:
    import json as _json

    from .status import build_status

    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    print(_json.dumps(build_status(repo, manifest), indent=2))
    return 0
```

In `build_parser`, after the `install-hook` block:
```python
    p_status = sub.add_parser("status", help="machine-readable install patch status (JSON)")
    p_status.set_defaults(func=cmd_status)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_status.py -q`
Expected: `1 passed`

- [ ] **Step 5: Write the README**

`README.md`:
```markdown
# odysseus-patches

Apply open upstream [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus)
PRs to your own install as tracked, SHA-pinned patches — re-applied across
updates while the PR is open, retired automatically once it merges, flagged
when it conflicts.

> **Community project — not affiliated with or endorsed by the Odysseus
> maintainers.** If they ever want this in core, the migration offer stands:
> AGPL-3.0 license and upstream CLI conventions are deliberate.

## Why

The Odysseus community ships fixes faster than upstream merges them. When the
bug you're hitting has an open PR, you shouldn't have to choose between
waiting weeks and hand-maintaining a fork.

## Install

```bash
pipx install odysseus-patches            # CLI only
pipx install 'odysseus-patches[mcp]'     # + MCP status server for the agent
```

Requirements: a git-checkout install of Odysseus (any platform — the Docker
flow builds from the working tree, so patches reach containers on rebuild).
Zip-download installs cannot be patched.

## Use

```bash
cd /path/to/odysseus
odysseus-patches add 3681        # review diffstat, confirm, apply pinned
odysseus-patches list
odysseus-patches update          # instead of `git pull --ff-only`
odysseus-patches upgrade 3681    # PR got new commits: review + re-pin
odysseus-patches remove 3681
odysseus-patches install-hook update_windows.bat   # wire into your updater
```

`update` exit codes: `0` nothing changed · `10` updated, rebuild/restart
Odysseus · `20` a patch needs attention · `1` error.

## How it works

Your tracked branch (`dev`) never carries local commits, so upstream's
`git pull --ff-only` always works. Patches live as squashed commits on a
generated `patched` branch, rebuilt from `data/patches/manifest.json` on
every update. PR content is fetched only from the upstream repo's own
`refs/pull/N/head` namespace and pinned to the commit SHA you reviewed —
a force-pushed PR can never silently change what your install runs.

## Agent visibility (optional)

Add the read-only MCP server in Odysseus → integrations (stdio):

- command: `odysseus-patches-mcp`
- args: `["--checkout", "/path/to/odysseus"]`

Tools: `list_patches`, `patch_status`. The agent can report patch state;
it cannot apply, upgrade, or remove anything by design.

## Security model

Applying a patch is running someone else's code. Mitigations: you review the
diff(stat) at `add`/`upgrade` time; the SHA you reviewed is what keeps being
applied; updates never adopt new PR content without an explicit `upgrade`.

## License

AGPL-3.0 — same as upstream Odysseus, so this code can migrate into core
without relicensing.
```

- [ ] **Step 6: Full suite + editable-install sanity run**

Run:
```bash
.venv/bin/python -m pytest -q && .venv/bin/odysseus-patches --help
```
Expected: all tests pass; help text lists add/list/show/remove/update/upgrade/install-hook/status.

- [ ] **Step 7: Commit**

```bash
git add README.md odysseus_patches/cli.py tests/test_cli_status.py
git commit -m "feat: status subcommand + README (install, security model, agent setup)"
```

---

## Self-review notes

- **Spec coverage:** manifest (Task 2), gh/REST fallback + offline-None (Task 3), refs/pull fetch + pin (Task 5), integration branch + conflict isolation + empty-pick retire (Task 6), patch-id offline detection (Task 7), planner rules incl. closed-unmerged-keeps-applying and upgrade-available (Task 8), update dance + exit codes + dirty-tree refusal (Task 9), CLI add/list/show/remove with add-rollback (Task 10), update/upgrade incl. incremental diff review (Task 11), install-hook (Task 12), read-only MCP server on the upstream stdio pattern (Task 13), README with disclaimer + migration note (Task 14). Spec's error-handling table: not-a-checkout → Task 10 `find_checkout`; corrupt manifest → Task 2; offline → Tasks 3/8/9; conflict → Tasks 6/9; gh missing → Task 3.
- **Deliberate scope notes:** `run_update`'s fetcher defaults to `None` and resolves `github.fetch_pr_info` at call time — this is what makes the CLI tests' monkeypatching of `odysseus_patches.github.fetch_pr_info` effective (a def-time default would bind the original function). The spec's "settings card / startup banner" items are explicitly out of scope (standalone variant).
- **Type consistency check:** `Patch` fields used identically in Tasks 2/6/7/8/9/10/13; `PRInfo(number,title,state,merged,head_sha)` consistent in 3/8/9/10/11; apply result constants `APPLY_OK/CONFLICT/EMPTY` consistent in 6/9/10; exit codes 0/10/20 consistent in 9/11/README.
```
