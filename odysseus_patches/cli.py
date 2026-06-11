"""Apply and manage upstream PR patches on this Odysseus install.

This first docstring line doubles as the help text upstream's `odysseus`
dispatcher displays if this file ever migrates into their scripts/ dir.
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from . import github
from .gitops import APPLY_OK, GitError, GitRepo, rebuild_patched
from .manifest import Manifest, ManifestError, Patch
from .update import UpdateError, run_update

MANIFEST_RELPATH = Path("data") / "patches" / "manifest.json"


class CliError(Exception):
    pass


def find_checkout(start: Path) -> Path:
    p = Path(start).resolve()
    for candidate in (p, *p.parents):
        if (candidate / ".git").exists():
            return candidate
    raise CliError(
        f"{start} is not inside a git checkout — point -C at your Odysseus "
        "install (zip downloads can't be patched; clone the repo instead)."
    )


def load(checkout: Path) -> tuple[GitRepo, Manifest]:
    repo = GitRepo(checkout)
    manifest = Manifest.load(checkout / MANIFEST_RELPATH)
    return repo, manifest


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{prompt} [y/N] ").strip().lower() == "y"


def cmd_add(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    info = github.fetch_pr_info(manifest.upstream, args.pr)
    if info is None:
        raise CliError(
            "Could not reach GitHub — adding a patch requires reviewing live "
            "PR metadata. Check your connection and retry."
        )
    if info.merged:
        raise CliError(f"PR #{args.pr} is already merged upstream — just update Odysseus.")
    sha = repo.fetch_pr_head(args.pr)
    base = repo.merge_base(manifest.base_branch, sha)
    print(f"PR #{info.number}: {info.title} [{info.state}]")
    print(f"pinning: {sha}")
    print(repo.diffstat(base, sha))
    if args.show:
        print(repo.run("diff", f"{base}..{sha}"))
    if not confirm("Apply this patch?", args.yes):
        print("aborted")
        return 0
    manifest.add(
        Patch(
            pr=info.number,
            title=info.title,
            pinned_sha=sha,
            added_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
    )
    results = rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
    if results.get(args.pr) != APPLY_OK:
        manifest.remove(args.pr)
        rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
        raise CliError(
            f"PR #{args.pr} does not apply cleanly ({results.get(args.pr)}) — "
            "it may need a rebase upstream. Nothing was changed."
        )
    patch = manifest.get(args.pr)
    patch.last_result = "applied-clean"
    manifest.save()
    print(f"applied PR #{args.pr} — restart/rebuild Odysseus to run it")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    _, manifest = load(checkout)
    if not manifest.patches:
        print("no patches tracked")
        return 0
    print(f"{'PR':>6}  {'STATUS':<16} {'PINNED':<12} TITLE")
    for p in manifest.patches:
        print(f"#{p.pr:>5}  {p.status:<16} {p.pinned_sha[:10]:<12} {p.title}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    patch = manifest.get(args.pr)
    if patch is None:
        raise CliError(f"PR #{args.pr} is not tracked")
    print(f"PR #{patch.pr}: {patch.title}")
    print(f"status: {patch.status}   pinned: {patch.pinned_sha}   last: {patch.last_result}")
    base = repo.merge_base(manifest.base_branch, patch.pinned_sha)
    print(repo.run("diff", f"{base}..{patch.pinned_sha}"))
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    manifest.remove(args.pr)
    rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
    manifest.save()
    print(f"removed PR #{args.pr}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    report, code = run_update(repo, manifest)
    if report.pulled:
        print(f"pulled {manifest.base_branch}: {report.old_base[:10]} -> {report.new_base[:10]}")
    else:
        print(f"{manifest.base_branch} already up to date")
    for action in report.actions:
        patch = manifest.get(action.pr)
        line = f"PR #{action.pr}: "
        if patch.status == "retired":
            line += f"retired ({patch.last_result})"
        elif patch.status == "conflicted":
            line += "CONFLICT — run `odysseus-patches show " + str(action.pr) + "`"
        else:
            line += patch.last_result or "ok"
        if action.upgrade_available:
            line += "  [upgrade available: `odysseus-patches upgrade " + str(action.pr) + "`]"
        if action.reason:
            line += f"  ({action.reason})"
        print(line)
    if code == 10:
        print("done — rebuild/restart Odysseus to run the updated code")
    elif code == 20:
        print("done with warnings — at least one patch needs attention")
    return code


def cmd_upgrade(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    patch = manifest.get(args.pr)
    if patch is None:
        raise CliError(f"PR #{args.pr} is not tracked")
    info = github.fetch_pr_info(manifest.upstream, args.pr)
    if info is None:
        raise CliError("Could not reach GitHub — upgrading requires reviewing the new commits.")
    new_sha = repo.fetch_pr_head(args.pr)
    if new_sha == patch.pinned_sha:
        print(f"PR #{args.pr} is up to date (pinned {patch.pinned_sha[:10]})")
        return 0
    print(f"PR #{args.pr} moved: {patch.pinned_sha[:10]} -> {new_sha[:10]}")
    print("incremental diff:")
    print(repo.run("diff", f"{patch.pinned_sha}..{new_sha}"))
    if not confirm("Adopt the new commits?", args.yes):
        print("aborted")
        return 0
    old_sha = patch.pinned_sha
    patch.pinned_sha = new_sha
    results = rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
    if results.get(args.pr) != APPLY_OK:
        patch.pinned_sha = old_sha
        rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
        raise CliError(
            f"upgraded PR #{args.pr} does not apply cleanly — kept the old pin."
        )
    patch.title = info.title
    patch.last_result = "applied-clean"
    manifest.save()
    print(f"re-pinned PR #{args.pr} to {new_sha[:10]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odysseus-patches",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument(
        "-C", "--checkout", default=".",
        help="path to (or inside) the Odysseus git checkout (default: cwd)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="apply an open upstream PR as a pinned patch")
    p_add.add_argument("pr", type=int)
    p_add.add_argument("--yes", action="store_true", help="skip confirmation")
    p_add.add_argument("--show", action="store_true", help="print the full diff before confirming")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="show tracked patches and their status")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show one patch's status and full diff")
    p_show.add_argument("pr", type=int)
    p_show.set_defaults(func=cmd_show)

    p_remove = sub.add_parser("remove", help="untrack a patch and rebuild without it")
    p_remove.add_argument("pr", type=int)
    p_remove.set_defaults(func=cmd_remove)

    p_update = sub.add_parser("update", help="pull upstream and reconcile every patch")
    p_update.set_defaults(func=cmd_update)

    p_upgrade = sub.add_parser("upgrade", help="re-pin a patch to its PR's new head")
    p_upgrade.add_argument("pr", type=int)
    p_upgrade.add_argument("--yes", action="store_true", help="skip confirmation")
    p_upgrade.set_defaults(func=cmd_upgrade)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (CliError, ManifestError, GitError, UpdateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
