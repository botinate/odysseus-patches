"""Atomic, race-safe file writes.

Used for the two on-disk state files (config.json holds the API token; the
manifest decides what code is applied). Both must be written without (a) a window
where a secret is world-readable, (b) a predictable temp name a local attacker
can pre-plant as a symlink, or (c) a torn/partial write.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically, owner-only, and race-safely.

    `tempfile.mkstemp` creates the temp file in the destination directory with
    O_CREAT|O_EXCL and mode 0600 *from creation*: an unpredictable name (so a
    local attacker can't pre-plant a symlink at it), O_EXCL (fails closed if they
    somehow did), and owner-only perms (a secret is never world-readable, even
    momentarily — so no chmod is needed). The final `os.replace` is atomic within
    the filesystem and, if `path` is itself a symlink, replaces the link rather
    than writing through it.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)  # never leave a stray temp file behind
        except OSError:
            pass
        raise
