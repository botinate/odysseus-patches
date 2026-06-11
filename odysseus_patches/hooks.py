"""Wire `odysseus-patches update` into a local update script.

The local update script is itself a local modification — managing it
idempotently (marker comment, .bak backup) is squarely this tool's job.
"""
from __future__ import annotations

from pathlib import Path

HOOK_MARKER = "odysseus-patches hook"
PULL_LINE = "git pull --ff-only"


class HookError(Exception):
    pass


def install_hook(script_path: Path) -> bool:
    """Replace the ff-only pull with an odysseus-patches update call.

    Returns True when the script was modified, False when already hooked.

    The injected command is a bare `odysseus-patches update`: it assumes the
    script sets its working directory to the checkout root before the pull
    line (update_windows.bat does, via pushd "%~dp0") and that
    odysseus-patches is on PATH for whichever user runs the script — use a
    full path in the script if it runs under a different account.
    """
    script_path = Path(script_path)
    raw = script_path.read_bytes()
    text = raw.decode("utf-8")
    if HOOK_MARKER in text:
        return False
    if PULL_LINE not in text:
        raise HookError(
            f"{script_path} contains no '{PULL_LINE}' line to hook — "
            "edit it manually or run `odysseus-patches update` yourself."
        )
    comment = "::" if script_path.suffix.lower() == ".bat" else "#"
    newline = "\r\n" if "\r\n" in text else "\n"
    replacement = (
        f"{comment} {HOOK_MARKER} (was: {PULL_LINE}){newline}"
        f"odysseus-patches update"
    )
    script_path.with_suffix(script_path.suffix + ".bak").write_bytes(raw)
    script_path.write_text(text.replace(PULL_LINE, replacement, 1), encoding="utf-8", newline="")
    return True
