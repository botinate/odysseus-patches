"""Staging patch proposals: the only mutating path agents are allowed.

A proposal is a manifest entry with status=proposed — never applied, never
built into the patched branch. Approving (CLI/UI only) converts it through
the normal add flow. This is the architectural enforcement of 'the agent can
suggest, only a human can run code'.
"""
from __future__ import annotations

import datetime
from typing import Callable, Optional

from . import github
from .gitops import GitRepo
from .manifest import Manifest, Patch, STATUS_PROPOSED
from .review import ReviewResult, ReviewUnavailable, to_manifest_dict


class ProposalError(Exception):
    pass


def stage_proposal(
    repo: GitRepo,
    manifest: Manifest,
    pr: int,
    *,
    run_review: bool,
    note: str,
    proposer: str,
    fetch_info: Optional[Callable] = None,
    review_runner: Optional[Callable[[str], ReviewResult]] = None,
) -> str:
    """Stage PR #pr as a proposal. Returns a human-readable summary message.

    review_runner takes the diff text and returns a ReviewResult (the CLI/MCP
    wire it to review.run_review with their Config); ReviewUnavailable is
    reported in the message but never blocks staging — the review re-runs at
    approval time anyway.
    """
    if fetch_info is None:
        fetch_info = github.fetch_pr_info
    existing = manifest.get(pr)
    if existing is not None:
        raise ProposalError(f"PR #{pr} is already tracked (status: {existing.status})")
    info = fetch_info(manifest.upstream, pr)
    if info is None:
        raise ProposalError("could not reach GitHub to look up the PR — try again later")
    if info.merged:
        raise ProposalError(f"PR #{pr} is already merged upstream — just update Odysseus")

    sha = repo.fetch_pr_head(pr)
    review_dict = None
    review_note = ""
    if run_review and review_runner is not None:
        base = repo.merge_base(manifest.base_branch, sha)
        diff = repo.run("diff", f"{base}..{sha}")
        try:
            result = review_runner(diff)
            review_dict = to_manifest_dict(result, sha)
            review_note = f" AI review: {result.verdict}"
            if result.findings:
                review_note += f" ({len(result.findings)} finding(s))"
        except ReviewUnavailable as exc:
            review_note = f" (review could not run: {exc})"

    manifest.add(
        Patch(
            pr=info.number,
            title=info.title,
            pinned_sha=sha,
            status=STATUS_PROPOSED,
            added_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            proposer=proposer,
            note=note,
            review=review_dict,
        )
    )
    manifest.save()
    return (
        f"Staged PR #{info.number} ({info.title}) as a proposal.{review_note} "
        f"Nothing is applied yet — approve with `odysseus-patches approve {info.number}` "
        "or reject in the patches UI/CLI."
    )
