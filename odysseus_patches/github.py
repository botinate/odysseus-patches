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
import warnings
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
        except (OSError, subprocess.SubprocessError, ValueError):
            # expected offline/unavailable modes: no gh binary, network down,
            # rate-limited (non-zero gh exit), garbage/truncated JSON
            continue
        except Exception as exc:
            # unexpected (e.g. API schema change breaking _parse_payload):
            # still degrade to None, but loudly enough to diagnose
            warnings.warn(f"fetch_pr_info: unexpected {exc!r}", stacklevel=2)
            continue
    return None
