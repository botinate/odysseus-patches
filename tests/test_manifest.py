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
