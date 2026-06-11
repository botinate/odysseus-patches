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
STATUS_PROPOSED = "proposed"  # staged by an agent/user; NEVER applied until approved

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

    def proposals(self) -> list[Patch]:
        return [p for p in self.patches if p.status == STATUS_PROPOSED]
