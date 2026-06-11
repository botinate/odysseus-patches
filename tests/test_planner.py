from odysseus_patches.github import PRInfo
from odysseus_patches.manifest import (
    Patch,
    STATUS_ACTIVE,
    STATUS_CONFLICTED,
    STATUS_RETIRED,
)
from odysseus_patches.planner import (
    ACTION_REAPPLY,
    ACTION_RETIRE,
    ACTION_WARN_CLOSED,
    plan_update,
)

SHA = "a" * 40
MOVED = "b" * 40


def patch(pr=1, status=STATUS_ACTIVE):
    return Patch(pr=pr, title="t", pinned_sha=SHA, status=status)


def info(state="open", merged=False, head=SHA):
    return PRInfo(number=1, title="t", state=state, merged=merged, head_sha=head)


def plan_one(p, i, offline_merged=frozenset()):
    actions = plan_update([p], {p.pr: i}, set(offline_merged))
    assert len(actions) == 1
    return actions[0]


def test_merged_upstream_retires():
    a = plan_one(patch(), info(state="closed", merged=True))
    assert a.action == ACTION_RETIRE


def test_offline_patch_id_match_retires():
    a = plan_one(patch(), None, offline_merged={1})
    assert a.action == ACTION_RETIRE
    assert "patch-id" in a.reason


def test_closed_unmerged_warns_but_reapplies():
    a = plan_one(patch(), info(state="closed", merged=False))
    assert a.action == ACTION_WARN_CLOSED


def test_open_unchanged_reapplies():
    a = plan_one(patch(), info())
    assert a.action == ACTION_REAPPLY
    assert a.upgrade_available is False


def test_open_moved_head_flags_upgrade():
    a = plan_one(patch(), info(head=MOVED))
    assert a.action == ACTION_REAPPLY
    assert a.upgrade_available is True


def test_offline_reapplies_pinned():
    a = plan_one(patch(), None)
    assert a.action == ACTION_REAPPLY
    assert "offline" in a.reason


def test_conflicted_is_retried():
    a = plan_one(patch(status=STATUS_CONFLICTED), info())
    assert a.action == ACTION_REAPPLY


def test_retired_is_skipped():
    assert plan_update([patch(status=STATUS_RETIRED)], {1: info()}, set()) == []
