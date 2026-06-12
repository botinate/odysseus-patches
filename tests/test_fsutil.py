import os

import pytest

from odysseus_patches._fsutil import atomic_write_text


def test_writes_content_and_creates_parent(tmp_path):
    p = tmp_path / "nested" / "dir" / "f.json"
    atomic_write_text(p, "hello\n")
    assert p.read_text() == "hello\n"


def test_overwrites_existing(tmp_path):
    p = tmp_path / "f"
    atomic_write_text(p, "one")
    atomic_write_text(p, "two")
    assert p.read_text() == "two"


def test_leaves_no_temp_file_behind(tmp_path):
    p = tmp_path / "f"
    atomic_write_text(p, "x")
    leftovers = [q.name for q in tmp_path.iterdir() if q.name != "f"]
    assert leftovers == [], leftovers


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_is_owner_only_with_no_world_readable_window(tmp_path):
    # mkstemp creates 0600 from the start, so a secret is never world-readable
    p = tmp_path / "secret"
    atomic_write_text(p, "sk-token")
    assert p.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "posix", reason="symlinks")
def test_symlinked_destination_is_replaced_not_followed(tmp_path):
    # a pre-planted symlink at the destination must not be written through
    victim = tmp_path / "victim"
    victim.write_text("DO NOT CLOBBER")
    dest = tmp_path / "config.json"
    dest.symlink_to(victim)
    atomic_write_text(dest, "new content")
    assert victim.read_text() == "DO NOT CLOBBER"   # target untouched
    assert not dest.is_symlink()                     # link replaced by a real file
    assert dest.read_text() == "new content"
