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
from .config import Config, ConfigError
from .gitops import APPLY_EMPTY, APPLY_OK, GitError, GitRepo, rebuild_patched
from .hooks import HookError
from .manifest import Manifest, ManifestError, Patch, STATUS_PROPOSED
from .proposals import ProposalError, stage_proposal
from .update import UpdateError, run_update
from . import review as review_mod
from .review import HONESTY_NOTE, ReviewResult, ReviewUnavailable, VERDICT_CLEAR, VERDICT_ERROR, VERDICT_FINDINGS, to_manifest_dict

MANIFEST_RELPATH = Path("data") / "patches" / "manifest.json"
CONFIG_RELPATH = Path("data") / "patches" / "config.json"


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
    proceed, review_dict = _review_gate(repo, manifest, args.pr, base, sha, args)
    if not proceed:
        # exit 1 only when non-interactive review BLOCKED (script signal);
        # an interactive user declining is a clean choice, exit 0
        return 1 if (args.yes and review_dict and review_dict.get("verdict") != VERDICT_CLEAR) else 0
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
    result = results.get(args.pr)
    if result != APPLY_OK:
        manifest.remove(args.pr)
        rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
        if result == APPLY_EMPTY:
            raise CliError(
                f"PR #{args.pr}'s changes are already in upstream "
                f"{manifest.base_branch} — just run `odysseus-patches update`. "
                "Nothing was changed."
            )
        raise CliError(
            f"PR #{args.pr} does not apply cleanly ({result}) — "
            "it may need a rebase upstream. Nothing was changed."
        )
    patch = manifest.get(args.pr)
    patch.last_result = "applied-clean"
    if review_dict:
        patch.review = review_dict
    manifest.save()
    print(f"applied PR #{args.pr} — restart/rebuild Odysseus to run it")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    _, manifest = load(checkout)
    if not manifest.patches:
        print("no patches tracked")
        return 0
    print(f"{'PR':>6}  {'STATUS':<16} {'PINNED':<12} {'REVIEW':<14} TITLE")
    for p in manifest.patches:
        verdict = (p.review or {}).get("verdict", "-")
        title = p.title if p.proposer == "cli" else f"{p.title}  [proposed by {p.proposer}]"
        print(f"#{p.pr:>5}  {p.status:<16} {p.pinned_sha[:10]:<12} {verdict:<14} {title}")
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
        if action.reason and action.reason != patch.last_result:
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
    if patch.review and patch.review.get("reviewed_sha") != new_sha:
        print("note: the cached AI review covers the OLD pin — these new commits are unreviewed")
    proceed, review_dict = _review_gate(repo, manifest, args.pr, patch.pinned_sha, new_sha, args)
    if not proceed:
        # exit 1 only when non-interactive review BLOCKED (script signal);
        # an interactive user declining is a clean choice, exit 0
        return 1 if (args.yes and review_dict and review_dict.get("verdict") != VERDICT_CLEAR) else 0
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
    if review_dict:
        patch.review = review_dict
    else:
        patch.review = None  # old verdict no longer covers the new pin
    manifest.save()
    print(f"re-pinned PR #{args.pr} to {new_sha[:10]}")
    return 0


def cmd_install_hook(args: argparse.Namespace) -> int:
    from .hooks import install_hook

    changed = install_hook(Path(args.script))
    print("hook installed" if changed else "already hooked — nothing to do")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    import json

    from .status import build_status

    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    print(json.dumps(build_status(repo, manifest), indent=2))
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    config = Config.load(checkout / CONFIG_RELPATH)
    if args.action == "set":
        config.set_value(args.key, args.value)
        config.save()
        print(f"set {args.key}")
        return 0
    import json
    print(json.dumps(config.redacted_dict(), indent=2))
    return 0


def _print_review(result: "ReviewResult", upstream: str, pr: int) -> None:
    print(f"AI review verdict: {result.verdict}")
    for f in result.findings:
        loc = f" [{f.file}]" if f.file else ""
        print(f"  - {f.severity}{loc}: {f.description}")
    if result.verdict == VERDICT_FINDINGS:
        print(
            "If this looks malicious, please report it on the PR thread: "
            f"https://github.com/{upstream}/pull/{pr}"
        )
    if result.verdict == VERDICT_CLEAR:
        print(HONESTY_NOTE)
    if result.verdict == VERDICT_ERROR:
        print(f"the model's answer was unusable ({result.detail}) — treat as unreviewed")


def _review_gate(
    repo: GitRepo,
    manifest: Manifest,
    pr: int,
    base: str,
    head: str,
    args: argparse.Namespace,
    cached: dict | None = None,
) -> tuple[bool, dict | None]:
    """The security-review question for add/upgrade/approve.

    Returns (proceed, review_dict_to_cache). Fail-closed rule: in fully
    non-interactive review mode (--yes --review), anything other than CLEAR
    aborts. Bare --yes implies --no-review so scripts never hang.

    cached: a prior review dict (used by cmd_approve to reuse a proposal's
    verdict when it still covers the same commit); None for add/upgrade's
    first review.
    """
    force_review = getattr(args, "review", False)
    skip_review = getattr(args, "no_review", False) or (args.yes and not force_review)
    if skip_review:
        return True, None

    if cached and cached.get("reviewed_sha") == head:
        print(f"cached AI review for this commit: {cached['verdict']} "
              f"({cached.get('findings_count', 0)} finding(s), {cached.get('at', '')})")
        if cached["verdict"] == VERDICT_CLEAR:
            print(HONESTY_NOTE)
            return True, cached
        if args.yes:
            return False, cached
        return confirm("Install anyway despite the cached verdict?", False), cached

    if force_review:
        choice = "r"
    else:
        choice = input("Review this diff with your Odysseus AI before applying? "
                       "[r]eview first / [i]nstall without review / [a]bort ").strip().lower()
    if choice == "a":
        print("aborted")
        return False, None
    if choice != "r":
        return True, None

    config = Config.load(repo.root / CONFIG_RELPATH)
    diff = repo.run("diff", f"{base}..{head}")
    try:
        result = review_mod.run_review(diff, config)
    except ReviewUnavailable as exc:
        print(f"review could not run: {exc}")
        if args.yes:
            return False, None  # fail closed in non-interactive mode
        return confirm("Install without review?", False), None

    _print_review(result, manifest.upstream, pr)
    review_dict = to_manifest_dict(result, head)
    if result.verdict == VERDICT_CLEAR:
        return True, review_dict
    if args.yes:
        return False, review_dict  # findings/error + non-interactive = abort
    # interactive: a FINDINGS verdict is worth caching; REVIEW_ERROR is noise
    cache = review_dict if result.verdict == VERDICT_FINDINGS else None
    return confirm("Install anyway?", False), cache


def cmd_review(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    patch = manifest.get(args.pr)
    if patch is None:
        raise CliError(f"PR #{args.pr} is not tracked — `add` or `propose` it first")
    config = Config.load(checkout / CONFIG_RELPATH)
    repo.fetch_pr_head(args.pr)
    base = repo.merge_base(manifest.base_branch, patch.pinned_sha)
    diff = repo.run("diff", f"{base}..{patch.pinned_sha}")
    try:
        result = review_mod.run_review(diff, config)
    except ReviewUnavailable as exc:
        raise CliError(str(exc))
    _print_review(result, manifest.upstream, args.pr)
    patch.review = to_manifest_dict(result, patch.pinned_sha)
    manifest.save()
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    review_runner = None
    if args.review:
        config = Config.load(checkout / CONFIG_RELPATH)
        review_runner = lambda diff: review_mod.run_review(diff, config)
    message = stage_proposal(
        repo, manifest, args.pr,
        run_review=args.review, note=args.note, proposer="cli",
        review_runner=review_runner,
    )
    print(message)
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    repo, manifest = load(checkout)
    patch = manifest.get(args.pr)
    if patch is None or patch.status != STATUS_PROPOSED:
        raise CliError(
            f"PR #{args.pr} is not a proposal"
            + ("" if patch is None else f" (status: {patch.status})")
        )
    base = repo.merge_base(manifest.base_branch, patch.pinned_sha)
    print(f"PR #{patch.pr}: {patch.title} (proposed by {patch.proposer})")
    if patch.note:
        print(f"note: {patch.note}")
    print(repo.diffstat(base, patch.pinned_sha))
    if args.show:
        print(repo.run("diff", f"{base}..{patch.pinned_sha}"))
    proceed, review_dict = _review_gate(
        repo, manifest, args.pr, base, patch.pinned_sha, args, cached=patch.review
    )
    if not proceed:
        return 1 if (args.yes and review_dict and review_dict.get("verdict") != VERDICT_CLEAR) else 0
    if not confirm("Apply this patch?", args.yes):
        print("aborted")
        return 0
    patch.status = "active"
    if review_dict:
        patch.review = review_dict
    results = rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
    result = results.get(args.pr)
    if result != APPLY_OK:
        patch.status = STATUS_PROPOSED  # roll back to proposal, nothing applied
        rebuild_patched(repo, manifest.base_branch, manifest.appliable_patches())
        manifest.save()
        if result == APPLY_EMPTY:
            raise CliError(
                f"PR #{args.pr}'s changes are already in upstream {manifest.base_branch} "
                "— reject the proposal and just update."
            )
        raise CliError(f"PR #{args.pr} does not apply cleanly ({result}) — left as proposal.")
    patch.last_result = "applied-clean"
    manifest.save()
    print(f"approved and applied PR #{args.pr} — restart/rebuild Odysseus to run it")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    checkout = find_checkout(args.checkout)
    _, manifest = load(checkout)
    patch = manifest.get(args.pr)
    if patch is None:
        raise CliError(f"PR #{args.pr} is not tracked")
    if patch.status != STATUS_PROPOSED:
        raise CliError(f"PR #{args.pr} is applied (status: {patch.status}) — use `remove` instead")
    manifest.remove(args.pr)
    manifest.save()
    print(f"rejected proposal PR #{args.pr}")
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
    p_add.add_argument("--review", action="store_true", help="AI-review the diff before applying")
    p_add.add_argument("--no-review", action="store_true", help="skip the review question")
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
    p_upgrade.add_argument("--review", action="store_true", help="AI-review the incremental diff")
    p_upgrade.add_argument("--no-review", action="store_true", help="skip the review question")
    p_upgrade.set_defaults(func=cmd_upgrade)

    p_hook = sub.add_parser(
        "install-hook", help="make a local update script call `odysseus-patches update`"
    )
    p_hook.add_argument("script", help="path to e.g. update_windows.bat")
    p_hook.set_defaults(func=cmd_install_hook)

    p_status = sub.add_parser("status", help="machine-readable install patch status (JSON)")
    p_status.set_defaults(func=cmd_status)

    p_config = sub.add_parser("config", help="show or set tool config (Odysseus url/token)")
    config_sub = p_config.add_subparsers(dest="action", required=True)
    pc_set = config_sub.add_parser("set", help="set a config value")
    pc_set.add_argument("key")
    pc_set.add_argument("value")
    pc_set.set_defaults(func=cmd_config)
    pc_show = config_sub.add_parser("show", help="show config (token redacted)")
    pc_show.set_defaults(func=cmd_config)

    p_review = sub.add_parser("review", help="AI-review a tracked patch's diff via Odysseus")
    p_review.add_argument("pr", type=int)
    p_review.set_defaults(func=cmd_review)

    p_propose = sub.add_parser("propose", help="stage a PR as a proposal (not applied)")
    p_propose.add_argument("pr", type=int)
    p_propose.add_argument("--review", action="store_true", help="attach an AI review to the proposal")
    p_propose.add_argument("--note", default="", help="why this PR is proposed")
    p_propose.set_defaults(func=cmd_propose)

    p_approve = sub.add_parser("approve", help="apply a staged proposal (review question included)")
    p_approve.add_argument("pr", type=int)
    p_approve.add_argument("--yes", action="store_true", help="skip confirmation")
    p_approve.add_argument("--show", action="store_true", help="print the full diff")
    p_approve.add_argument("--review", action="store_true", help="AI-review before applying")
    p_approve.add_argument("--no-review", action="store_true", help="skip the review question")
    p_approve.set_defaults(func=cmd_approve)

    p_reject = sub.add_parser("reject", help="drop a staged proposal")
    p_reject.add_argument("pr", type=int)
    p_reject.set_defaults(func=cmd_reject)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (CliError, ManifestError, GitError, UpdateError, HookError, ConfigError, ProposalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
