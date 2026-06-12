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


def atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    """Write `text` to `path` atomically and race-safely.

    `tempfile.mkstemp` creates the temp file in the destination directory with
    O_CREAT|O_EXCL and mode 0600 *from creation* (unpredictable name, so a local
    attacker can't pre-plant a symlink at it, and O_EXCL fails closed if they
    somehow did) — so a secret is never momentarily world-readable. The final
    `os.replace` is atomic within the filesystem and, if `path` is itself a
    symlink, replaces the link rather than writing through it. `mode` is applied
    to the final file before the rename (default owner-only).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            os.chmod(tmp, mode)  # no-op where POSIX modes are unsupported
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)  # never leave a stray temp file behind
        except OSError:
            pass
        raise
