import pytest

from odysseus_patches.github import PRInfo
from odysseus_patches.gitops import GitRepo
from odysseus_patches.manifest import Manifest, Patch, STATUS_PROPOSED
from odysseus_patches.proposals import ProposalError, stage_proposal
from odysseus_patches.review import Finding, ReviewResult, ReviewUnavailable, VERDICT_CLEAR


def manifest_of(checkout):
    return Manifest.load(checkout / "data" / "patches" / "manifest.json")


def info_for(pr, sha, state="open", merged=False):
    return lambda upstream, n: PRInfo(pr, f"fix: pr {pr}", state, merged, sha) if n == pr else None


def test_stage_proposal_happy_path(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: pr 7")
    repo = GitRepo(checkout)
    manifest = manifest_of(checkout)

    message = stage_proposal(
        repo, manifest, 7,
        run_review=False, note="from agent", proposer="agent",
        fetch_info=info_for(7, sha),
    )

    saved = manifest_of(checkout).get(7)
    assert saved.status == STATUS_PROPOSED
    assert saved.proposer == "agent"
    assert saved.pinned_sha == sha
    assert saved.review is None
    assert "approve" in message


def test_stage_with_review_attaches_verdict(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: pr 7")
    repo = GitRepo(checkout)

    message = stage_proposal(
        repo, manifest_of(checkout), 7,
        run_review=True, note="", proposer="agent",
        fetch_info=info_for(7, sha),
        review_runner=lambda diff: ReviewResult(VERDICT_CLEAR, []),
    )

    saved = manifest_of(checkout).get(7)
    assert saved.review["verdict"] == VERDICT_CLEAR
    assert saved.review["reviewed_sha"] == sha
    assert "CLEAR" in message


def test_stage_review_unavailable_still_stages(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: pr 7")

    def failing_review(diff):
        raise ReviewUnavailable("no token")

    message = stage_proposal(
        GitRepo(checkout), manifest_of(checkout), 7,
        run_review=True, note="", proposer="agent",
        fetch_info=info_for(7, sha),
        review_runner=failing_review,
    )

    saved = manifest_of(checkout).get(7)
    assert saved.status == STATUS_PROPOSED
    assert saved.review is None
    assert "review could not run" in message


def test_stage_already_tracked_raises(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: pr 7")
    manifest = manifest_of(checkout)
    manifest.add(Patch(pr=7, title="t", pinned_sha=sha))
    manifest.save()

    with pytest.raises(ProposalError, match="already"):
        stage_proposal(
            GitRepo(checkout), manifest, 7,
            run_review=False, note="", proposer="agent",
            fetch_info=info_for(7, sha),
        )


def test_stage_merged_pr_raises(upstream, checkout):
    sha = upstream.open_pr(7, "src/fix.py", "FIX = True\n", "fix: pr 7")
    with pytest.raises(ProposalError, match="merged"):
        stage_proposal(
            GitRepo(checkout), manifest_of(checkout), 7,
            run_review=False, note="", proposer="agent",
            fetch_info=info_for(7, sha, state="closed", merged=True),
        )


def test_stage_offline_raises(upstream, checkout):
    with pytest.raises(ProposalError, match="GitHub"):
        stage_proposal(
            GitRepo(checkout), manifest_of(checkout), 7,
            run_review=False, note="", proposer="agent",
            fetch_info=lambda u, n: None,
        )
