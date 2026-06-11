"""Install/uninstall the patches panel into a local Odysseus checkout.

Drops two extension-owned assets (untracked in Odysseus's git, so they survive
`git pull`) and appends one marked, idempotent loader line to app.py — the only
edit to a tracked file, and the only hook Odysseus exposes (no module
auto-loading). uninstall reverses both.
"""
from __future__ import annotations

import shutil
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "ui_assets"
LOADER_BEGIN = "# >>> odysseus-patches UI (managed by `odysseus-patches install-ui`) >>>"
LOADER_END = "# <<< odysseus-patches UI <<<"
_LOADER_BLOCK = (
    f"\n{LOADER_BEGIN}\n"
    "import routes.patches_ui as _odypatch_ui\n"
    "_odypatch_ui.install(app)\n"
    f"{LOADER_END}\n"
)


class InstallError(Exception):
    pass


def _validate(root: Path) -> Path:
    root = Path(root)
    if not (root / "app.py").exists() or not (root / "static" / "js").exists():
        raise InstallError(
            f"{root} is not an Odysseus install (need app.py and static/js/). "
            "Point install-ui at your Odysseus checkout with -C."
        )
    return root


def install_ui(root: Path, overwrite: bool = True) -> list[str]:
    root = _validate(root)
    changed: list[str] = []

    targets = {
        _ASSETS / "patches_ui.py": root / "routes" / "patches_ui.py",
        _ASSETS / "patches.js": root / "static" / "js" / "patches.js",
    }
    for src, dst in targets.items():
        if dst.exists() and not overwrite:
            continue
        shutil.copyfile(src, dst)
        changed.append(str(dst.relative_to(root)))

    app_py = root / "app.py"
    text = app_py.read_text(encoding="utf-8")
    if LOADER_BEGIN not in text:
        app_py.write_text(text.rstrip("\n") + "\n" + _LOADER_BLOCK, encoding="utf-8")
        changed.append("app.py (loader line)")
    return changed


def uninstall_ui(root: Path) -> list[str]:
    root = Path(root)
    changed: list[str] = []
    for rel in ("routes/patches_ui.py", "static/js/patches.js"):
        p = root / rel
        if p.exists():
            p.unlink()
            changed.append(rel)
    app_py = root / "app.py"
    if app_py.exists():
        text = app_py.read_text(encoding="utf-8")
        if LOADER_BEGIN in text and LOADER_END in text:
            start = text.index(LOADER_BEGIN)
            end = text.index(LOADER_END) + len(LOADER_END)
            cut_start = start
            if cut_start > 0 and text[cut_start - 1] == "\n":
                cut_start -= 1
            new = text[:cut_start] + text[end:]
            new = new.rstrip("\n") + "\n"
            app_py.write_text(new, encoding="utf-8")
            changed.append("app.py (loader line)")
    return changed
