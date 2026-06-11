import json

from odysseus_patches.manifest import (
    Manifest,
    Patch,
    STATUS_PROPOSED,
)


def test_proposed_is_not_appliable(tmp_path):
    m = Manifest.load(tmp_path / "m.json")
    m.add(Patch(pr=1, title="t", pinned_sha="a" * 40, status=STATUS_PROPOSED))
    assert m.appliable_patches() == []


def test_new_fields_round_trip(tmp_path):
    path = tmp_path / "m.json"
    m = Manifest.load(path)
    m.add(
        Patch(
            pr=1,
            title="t",
            pinned_sha="a" * 40,
            status=STATUS_PROPOSED,
            proposer="agent",
            note="agent found this for issue #5",
            review={"verdict": "CLEAR", "findings_count": 0, "reviewed_sha": "a" * 40, "at": "x"},
        )
    )
    m.save()
    again = Manifest.load(path)
    p = again.get(1)
    assert p.proposer == "agent"
    assert p.note == "agent found this for issue #5"
    assert p.review["verdict"] == "CLEAR"


def test_v1_manifest_without_new_fields_loads(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "upstream": "o/r",
                "base_branch": "dev",
                "patches": [
                    {
                        "pr": 7,
                        "title": "old",
                        "pinned_sha": "b" * 40,
                        "status": "active",
                        "added_at": "",
                        "last_result": "applied-clean",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    m = Manifest.load(path)
    p = m.get(7)
    assert p.proposer == "cli"
    assert p.note == ""
    assert p.review is None


def test_proposals_helper(tmp_path):
    m = Manifest.load(tmp_path / "m.json")
    m.add(Patch(pr=1, title="t", pinned_sha="a" * 40, status=STATUS_PROPOSED))
    m.add(Patch(pr=2, title="t", pinned_sha="b" * 40))
    assert [p.pr for p in m.proposals()] == [1]
