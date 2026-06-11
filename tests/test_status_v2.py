from odysseus_patches.gitops import GitRepo
from odysseus_patches.manifest import Manifest, Patch, STATUS_PROPOSED
from odysseus_patches.status import build_status


def test_status_counts_proposals_as_attention(checkout):
    manifest = Manifest.load(checkout / "data" / "patches" / "manifest.json")
    manifest.add(Patch(pr=9, title="t", pinned_sha="a" * 40, status=STATUS_PROPOSED, proposer="agent"))
    status = build_status(GitRepo(checkout), manifest)
    assert status["healthy"] is False
    assert any("proposal" in line for line in status["attention"])
    assert status["patches"][0]["proposer"] == "agent"
