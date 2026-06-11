import json
import subprocess

import pytest

from odysseus_patches import github
from odysseus_patches.github import PRInfo, fetch_pr_info

SAMPLE = {
    "number": 3055,
    "title": "fix(mcp): bust prompt cache",
    "state": "closed",
    "merged": True,
    "head": {"sha": "b" * 40},
}


def test_parse_api_payload():
    info = github._parse_payload(SAMPLE)
    assert info == PRInfo(
        number=3055,
        title="fix(mcp): bust prompt cache",
        state="closed",
        merged=True,
        head_sha="b" * 40,
    )


def test_fetch_prefers_gh(monkeypatch):
    rest_calls = []
    monkeypatch.setattr(github, "_via_gh", lambda upstream, pr: github._parse_payload(SAMPLE))
    monkeypatch.setattr(github, "_via_rest", lambda upstream, pr: rest_calls.append((upstream, pr)))
    assert fetch_pr_info("o/r", 3055).merged is True
    assert rest_calls == [], "_via_rest must not be called when gh succeeds"


def test_fetch_falls_back_to_rest(monkeypatch):
    monkeypatch.setattr(
        github, "_via_gh", lambda upstream, pr: (_ for _ in ()).throw(FileNotFoundError("no gh"))
    )
    monkeypatch.setattr(github, "_via_rest", lambda upstream, pr: github._parse_payload(SAMPLE))
    assert fetch_pr_info("o/r", 3055).head_sha == "b" * 40


def test_fetch_offline_returns_none(monkeypatch):
    monkeypatch.setattr(
        github, "_via_gh", lambda upstream, pr: (_ for _ in ()).throw(FileNotFoundError("no gh"))
    )
    monkeypatch.setattr(
        github, "_via_rest", lambda upstream, pr: (_ for _ in ()).throw(OSError("offline"))
    )
    assert fetch_pr_info("o/r", 3055) is None


def test_via_gh_invokes_gh_api(monkeypatch):
    calls = {}

    def fake_run(cmd, capture_output, text, check, timeout):
        calls["cmd"] = cmd
        calls["timeout"] = timeout
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(SAMPLE), stderr="")

    monkeypatch.setattr(github.subprocess, "run", fake_run)
    info = github._via_gh("o/r", 3055)
    assert calls["cmd"] == ["gh", "api", "repos/o/r/pulls/3055"]
    assert calls["timeout"] == github.TIMEOUT_SECONDS
    assert info.number == 3055


def test_fetch_warns_on_unexpected_error(monkeypatch):
    monkeypatch.setattr(
        github, "_via_gh", lambda upstream, pr: (_ for _ in ()).throw(KeyError("head"))
    )
    monkeypatch.setattr(
        github, "_via_rest", lambda upstream, pr: (_ for _ in ()).throw(OSError("offline"))
    )
    with pytest.warns(UserWarning, match="unexpected"):
        assert fetch_pr_info("o/r", 3055) is None
