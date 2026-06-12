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


# --- the manifest is a trust anchor: reject tampered/malformed entries on load ---

def _write_manifest(path, patches, upstream="pewdiepie-archdaemon/odysseus", base_branch="dev"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "upstream": upstream, "base_branch": base_branch, "patches": patches}),
        encoding="utf-8",
    )


_OK = {"pr": 7, "title": "x", "pinned_sha": "a" * 40}


def test_rejects_non_int_pr(tmp_path):
    path = tmp_path / "manifest.json"
    _write_manifest(path, [{"pr": '7"><img src=x onerror=alert(1)>', "title": "x", "pinned_sha": "a" * 40}])
    with pytest.raises(ManifestError):
        Manifest.load(path)


def test_rejects_non_sha_pinned(tmp_path):
    # an option-shaped value must never be trusted into a git argument
    path = tmp_path / "manifest.json"
    _write_manifest(path, [{"pr": 7, "title": "x", "pinned_sha": "--output=/etc/cron.d/x"}])
    with pytest.raises(ManifestError):
        Manifest.load(path)


def test_rejects_unknown_status(tmp_path):
    path = tmp_path / "manifest.json"
    _write_manifest(path, [{"pr": 7, "title": "x", "pinned_sha": "a" * 40, "status": "totally-applied"}])
    with pytest.raises(ManifestError):
        Manifest.load(path)


def test_rejects_unknown_proposer(tmp_path):
    path = tmp_path / "manifest.json"
    _write_manifest(path, [{"pr": 7, "title": "x", "pinned_sha": "a" * 40, "proposer": "root"}])
    with pytest.raises(ManifestError):
        Manifest.load(path)


def test_rejects_bad_upstream(tmp_path):
    path = tmp_path / "manifest.json"
    _write_manifest(path, [_OK], upstream="../../etc/passwd")
    with pytest.raises(ManifestError):
        Manifest.load(path)


def test_rejects_bad_base_branch(tmp_path):
    path = tmp_path / "manifest.json"
    _write_manifest(path, [_OK], base_branch="dev; rm -rf /")
    with pytest.raises(ManifestError):
        Manifest.load(path)


def test_rejects_leading_dash_base_branch(tmp_path):
    # '-f' would be read as a git option: `git checkout -f`
    path = tmp_path / "manifest.json"
    _write_manifest(path, [_OK], base_branch="-f")
    with pytest.raises(ManifestError):
        Manifest.load(path)


def test_rejects_traversal_base_branch(tmp_path):
    path = tmp_path / "manifest.json"
    _write_manifest(path, [_OK], base_branch="../evil")
    with pytest.raises(ManifestError):
        Manifest.load(path)


def test_rejects_leading_dash_upstream(tmp_path):
    path = tmp_path / "manifest.json"
    _write_manifest(path, [_OK], upstream="-owner/repo")
    with pytest.raises(ManifestError):
        Manifest.load(path)


def test_rejects_traversal_upstream(tmp_path):
    # owner/.. would walk the GitHub API path
    path = tmp_path / "manifest.json"
    _write_manifest(path, [_OK], upstream="owner/..")
    with pytest.raises(ManifestError):
        Manifest.load(path)


def test_rejects_non_dict_review(tmp_path):
    # a non-object review crashes (p.review or {}).get(...) in list/status
    path = tmp_path / "manifest.json"
    _write_manifest(path, [{"pr": 7, "title": "x", "pinned_sha": "a" * 40, "review": "CLEAR"}])
    with pytest.raises(ManifestError):
        Manifest.load(path)


def test_accepts_valid_short_sha_and_agent_proposal(tmp_path):
    path = tmp_path / "manifest.json"
    _write_manifest(path, [{"pr": 7, "title": "x", "pinned_sha": "abc1234",
                            "status": "proposed", "proposer": "agent"}])
    m = Manifest.load(path)
    assert m.get(7).pinned_sha == "abc1234"
    assert m.get(7).proposer == "agent"
