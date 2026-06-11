"""Pure update planner: manifest state + PR metadata in, actions out.

No git, no network, no I/O — every lifecycle rule from the spec lives here
as an easily table-tested branch.
"""
from __future__ import annotations

from dataclasses import dataclass

from .github import PRInfo
from .manifest import Patch, STATUS_RETIRED

ACTION_RETIRE = "retire"
ACTION_REAPPLY = "reapply"
ACTION_WARN_CLOSED = "warn-closed"


@dataclass
class PlannedAction:
    pr: int
    action: str
    upgrade_available: bool = False
    reason: str = ""


def plan_update(
    patches: list[Patch],
    infos: dict[int, PRInfo | None],
    offline_merged: set[int],
) -> list[PlannedAction]:
    actions: list[PlannedAction] = []
    for patch in patches:
        if patch.status == STATUS_RETIRED:
            continue
        info = infos.get(patch.pr)
        if info is not None and info.merged:
            actions.append(
                PlannedAction(patch.pr, ACTION_RETIRE, reason="merged upstream")
            )
        elif patch.pr in offline_merged:
            actions.append(
                PlannedAction(
                    patch.pr, ACTION_RETIRE, reason="patch-id match on new upstream commits"
                )
            )
        elif info is not None and info.state == "closed":
            actions.append(
                PlannedAction(
                    patch.pr, ACTION_WARN_CLOSED,
                    reason="PR closed without merging — keep or `remove` it",
                )
            )
        elif info is None:
            actions.append(
                PlannedAction(patch.pr, ACTION_REAPPLY, reason="offline — re-applying pinned SHA")
            )
        else:
            actions.append(
                PlannedAction(
                    patch.pr,
                    ACTION_REAPPLY,
                    upgrade_available=(info.head_sha != patch.pinned_sha),
                )
            )
    return actions
