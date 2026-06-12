"""Manifest: the source of truth for which PR patches this install carries.

Lives at <checkout>/data/patches/manifest.json — `data/` is Odysseus's
persistent, Docker-bind-mounted directory, so the manifest survives updates
and image rebuilds. The `patched` git branch is a disposable artifact rebuilt
from this file; never the other way around.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ._fsutil import atomic_write_text

SCHEMA_VERSION = 1
DEFAULT_UPSTREAM = "pewdiepie-archdaemon/odysseus"
DEFAULT_BASE_BRANCH = "dev"

STATUS_ACTIVE = "active"
STATUS_CONFLICTED = "conflicted"
STATUS_RETIRED = "retired"
STATUS_CLOSED_UPSTREAM = "closed-upstream"
STATUS_PROPOSED = "proposed"  # staged by an agent/user; NEVER applied until approved

# Statuses that still get (re)applied to the patched branch. Conflicted is
# retried every update — upstream movement can resolve a conflict. Closed
# PRs keep applying until the user explicitly removes them (spec decision).
APPLIABLE_STATUSES = {STATUS_ACTIVE, STATUS_CONFLICTED, STATUS_CLOSED_UPSTREAM}

# The manifest is a trust anchor: its pinned_sha decides what commit content is
# applied, and its fields flow into git arguments, GitHub API paths/URLs, and
# the admin UI. Anything that can write data/patches/manifest.json could
# otherwise re-pin a patch to unreviewed code (applied on the next rebuild) or
# inject markup/option-shaped values. So validate strictly on load.
_VALID_STATUSES = {
    STATUS_ACTIVE, STATUS_CONFLICTED, STATUS_RETIRED, STATUS_CLOSED_UPSTREAM, STATUS_PROPOSED,
}
_VALID_PROPOSERS = {"cli", "agent"}
SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
# owner/repo, each segment STARTING alphanumeric so a leading '-' can't be read
# as an option by `gh api`; `..` is rejected separately (path traversal).
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
# a git branch ref, STARTING alphanumeric — a leading '-' would be read as a git
# option (e.g. base_branch '-f' -> `git checkout -f`); '..' rejected separately.
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _validated_ref(value, kind: str, pattern: "re.Pattern") -> str:
    """Validate a manifest string that flows into git args / API paths: must be a
    string, match `pattern` (so it can't start with '-' and be read as an
    option), and contain no '..' (path/ref traversal)."""
    if not isinstance(value, str) or ".." in value or not pattern.match(value):
        raise ManifestError(f"invalid {kind} {value!r}")
    return value


class ManifestError(Exception):
    """Raised for duplicate/missing patches and unreadable/invalid manifests."""


def _validated_patch(p: dict) -> "Patch":
    """Build a Patch from raw JSON, rejecting tampered/malformed entries."""
    patch = Patch(**p)  # unknown/missing keys raise TypeError (caught by load)
    if not isinstance(patch.pr, int) or isinstance(patch.pr, bool) or patch.pr <= 0:
        raise ManifestError(f"invalid pr {patch.pr!r} (must be a positive integer)")
    if not isinstance(patch.pinned_sha, str) or not SHA_RE.match(patch.pinned_sha):
        raise ManifestError(
            f"invalid pinned_sha {patch.pinned_sha!r} for PR #{patch.pr} "
            "(must be a hex commit SHA)")
    if patch.status not in _VALID_STATUSES:
        raise ManifestError(f"invalid status {patch.status!r} for PR #{patch.pr}")
    if patch.proposer not in _VALID_PROPOSERS:
        raise ManifestError(f"invalid proposer {patch.proposer!r} for PR #{patch.pr}")
    if patch.review is not None and not isinstance(patch.review, dict):
        # a non-dict review crashes `(p.review or {}).get(...)` in list/status
        raise ManifestError(f"invalid review for PR #{patch.pr} (must be an object or null)")
    return patch


@dataclass
class Patch:
    pr: int
    title: str
    pinned_sha: str
    status: str = STATUS_ACTIVE
    added_at: str = ""
    last_result: str = ""
    proposer: str = "cli"      # "cli" | "agent" — who staged/added it
    note: str = ""             # free text from the proposer
    review: dict | None = None # {"verdict","findings_count","model","reviewed_sha","at"}


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
            patches = [_validated_patch(p) for p in data.get("patches", [])]
        except (ValueError, TypeError, KeyError) as exc:
            raise ManifestError(
                f"Unreadable manifest at {path}: {exc}. "
                "It is plain JSON — fix or delete it and re-add patches."
            ) from exc
        upstream = _validated_ref(data.get("upstream", DEFAULT_UPSTREAM), "upstream", _REPO_RE)
        base_branch = _validated_ref(data.get("base_branch", DEFAULT_BASE_BRANCH), "base_branch", _BRANCH_RE)
        return cls(path=path, upstream=upstream, base_branch=base_branch, patches=patches)

    def save(self) -> None:
        payload = {
            "version": SCHEMA_VERSION,
            "upstream": self.upstream,
            "base_branch": self.base_branch,
            "patches": [asdict(p) for p in self.patches],
        }
        # 0644: non-secret, and the MCP server (possibly a different uid under
        # Docker) reads it. Written atomically/race-safely all the same.
        atomic_write_text(self.path, json.dumps(payload, indent=2) + "\n", mode=0o644)

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

    def proposals(self) -> list[Patch]:
        return [p for p in self.patches if p.status == STATUS_PROPOSED]
