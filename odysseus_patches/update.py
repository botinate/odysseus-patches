"""The update dance: pull upstream, reconcile every patch, rebuild the branch.

Exit codes are machine-readable for wrapper scripts (update_windows.bat etc):
0 = nothing changed; 10 = updated, rebuild/restart needed; 20 = updated but
one or more patches need attention; errors raise UpdateError (CLI maps to 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import github
from .github import PRInfo
from .gitops import (
    APPLY_CONFLICT,
    APPLY_EMPTY,
    APPLY_OK,
    GitRepo,
    merged_upstream_prs,
    rebuild_patched,
)
from .manifest import (
    Manifest,
    STATUS_ACTIVE,
    STATUS_CLOSED_UPSTREAM,
    STATUS_CONFLICTED,
    STATUS_PROPOSED,
    STATUS_RETIRED,
)
from .planner import (
    ACTION_REAPPLY,
    ACTION_RETIRE,
    ACTION_WARN_CLOSED,
    PlannedAction,
    plan_update,
)

EXIT_OK = 0
EXIT_REBUILD = 10
EXIT_ATTENTION = 20

FetchInfo = Callable[[str, int], PRInfo | None]


class UpdateError(Exception):
    pass


@dataclass
class UpdateReport:
    old_base: str = ""
    new_base: str = ""
    actions: list[PlannedAction] = field(default_factory=list)
    apply_results: dict[int, str] = field(default_factory=dict)

    @property
    def pulled(self) -> bool:
        return self.old_base != self.new_base

    @property
    def attention_needed(self) -> bool:
        return APPLY_CONFLICT in self.apply_results.values()


def run_update(
    repo: GitRepo,
    manifest: Manifest,
    fetch_info: FetchInfo | None = None,
    force: bool = False,
) -> tuple[UpdateReport, int]:
    from .branch_safety import check_branch_safety
    check_branch_safety(repo, manifest.base_branch, force=force)

    if fetch_info is None:
        # resolved at call time (not def time) so tests can monkeypatch
        # odysseus_patches.github.fetch_pr_info and the CLI picks it up
        fetch_info = github.fetch_pr_info

    # Strip the UI loader block before the dirty-tree guard so that our own
    # managed edits to app.py never look like user uncommitted work.
    from .installer import strip_loader_block
    _app_py = repo.root / "app.py"
    _ui_installed = strip_loader_block(_app_py)

    try:
        # Check for changes to tracked files only; untracked files (e.g. the
        # manifest under data/) are not the user's working-tree edits.
        if repo.run("status", "--porcelain", "--untracked-files=no"):
            raise UpdateError(
                "Working tree has uncommitted changes — commit, stash, or discard "
                "them first (patches never live as dirty files; this is your own work)."
            )
        report = UpdateReport()
        base = manifest.base_branch

        repo.run("checkout", base)
        report.old_base = repo.rev_parse("HEAD")
        repo.run("pull", "--ff-only")
        report.new_base = repo.rev_parse("HEAD")

        tracked = [
            p for p in manifest.patches
            if p.status not in (STATUS_RETIRED, STATUS_PROPOSED)
        ]
        infos = {p.pr: fetch_info(manifest.upstream, p.pr) for p in tracked}
        offline_merged = merged_upstream_prs(repo, report.old_base, report.new_base, tracked)
        report.actions = plan_update(tracked, infos, offline_merged)

        for action in report.actions:
            patch = manifest.get(action.pr)
            if action.action == ACTION_RETIRE:
                patch.status = STATUS_RETIRED
                patch.last_result = action.reason
            elif action.action == ACTION_WARN_CLOSED:
                patch.status = STATUS_CLOSED_UPSTREAM

        report.apply_results = rebuild_patched(repo, base, manifest.appliable_patches())

        for pr, result in report.apply_results.items():
            patch = manifest.get(pr)
            if result == APPLY_CONFLICT:
                patch.status = STATUS_CONFLICTED
                patch.last_result = "conflict"
            elif result == APPLY_EMPTY:
                patch.status = STATUS_RETIRED
                patch.last_result = "already-upstream"
            elif result == APPLY_OK:
                if patch.status == STATUS_CONFLICTED:
                    patch.status = STATUS_ACTIVE
                patch.last_result = "applied-clean"

        # an empty-pick retire can leave the branch carrying nothing useful;
        # rebuild once more so the artifact matches the manifest exactly
        if APPLY_EMPTY in report.apply_results.values():
            rebuild_patched(repo, base, manifest.appliable_patches())

        manifest.save()

        if report.attention_needed:
            return report, EXIT_ATTENTION
        # any planned action (retire/warn/reapply) means install state changed,
        # even if the pull was a no-op — EXIT_OK strictly means "nothing happened"
        if report.apply_results or report.actions:
            return report, EXIT_REBUILD
        return report, EXIT_OK
    finally:
        if _ui_installed:
            try:
                from .installer import install_ui
                install_ui(repo.root, overwrite=True)
            except Exception as _exc:
                import logging
                logging.getLogger(__name__).warning(
                    "odysseus-patches: failed to reapply UI loader after update "
                    "(%s) — re-run `odysseus-patches install-ui`", _exc)
