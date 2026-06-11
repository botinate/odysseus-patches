import json

import pytest

from odysseus_patches.config import Config
from odysseus_patches.review import (
    ReviewUnavailable,
    VERDICT_CLEAR,
    VERDICT_FINDINGS,
    run_review,
    to_manifest_dict,
)


def cfg(tmp_path, token="tok"):
    c = Config.load(tmp_path / "config.json")
    c.api_token = token
    return c


def ok_transport(payload_text):
    calls = []

    def transport(url, data, headers):
        calls.append({"url": url, "data": json.loads(data.decode("utf-8")), "headers": headers})
        return 200, json.dumps({"response": payload_text})

    transport.calls = calls
    return transport


def test_run_review_clear(tmp_path):
    t = ok_transport('{"verdict": "CLEAR", "findings": []}')
    result = run_review("diff --git a/x b/x\n+1\n", cfg(tmp_path), transport=t)
    assert result.verdict == VERDICT_CLEAR
    call = t.calls[0]
    assert call["url"] == "http://127.0.0.1:8000/v1/chat"
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert "DIFF:" in call["data"]["message"]


def test_run_review_findings(tmp_path):
    t = ok_transport(
        '{"verdict": "FINDINGS", "findings": [{"severity": "high", "file": "a", "description": "bad"}]}'
    )
    result = run_review("diff", cfg(tmp_path), transport=t)
    assert result.verdict == VERDICT_FINDINGS
    assert result.findings[0].severity == "high"


def test_no_token_raises_unavailable(tmp_path):
    with pytest.raises(ReviewUnavailable, match="api_token"):
        run_review("diff", cfg(tmp_path, token=""), transport=ok_transport("x"))


def test_http_error_raises_unavailable(tmp_path):
    def transport(url, data, headers):
        return 403, "API token is not scoped for chat"

    with pytest.raises(ReviewUnavailable, match="403"):
        run_review("diff", cfg(tmp_path), transport=transport)


def test_connection_error_raises_unavailable(tmp_path):
    def transport(url, data, headers):
        raise OSError("connection refused")

    with pytest.raises(ReviewUnavailable, match="connection refused"):
        run_review("diff", cfg(tmp_path), transport=transport)


def test_chunked_review_merges(tmp_path):
    answers = iter(
        [
            '{"verdict": "CLEAR", "findings": []}',
            '{"verdict": "FINDINGS", "findings": [{"severity": "low", "file": "b", "description": "odd"}]}',
        ]
    )

    def transport(url, data, headers):
        return 200, json.dumps({"response": next(answers)})

    big_a = "diff --git a/a b/a\n" + "+x\n" * 30
    big_b = "diff --git a/b b/b\n" + "+y\n" * 30
    result = run_review(big_a + big_b, cfg(tmp_path), transport=transport, chunk_cap=40)
    assert result.verdict == VERDICT_FINDINGS
    assert len(result.findings) == 1


def test_response_text_extraction_tolerates_other_keys(tmp_path):
    def transport(url, data, headers):
        return 200, json.dumps({"message": '{"verdict": "CLEAR", "findings": []}'})

    assert run_review("d", cfg(tmp_path), transport=transport).verdict == VERDICT_CLEAR


def test_to_manifest_dict(tmp_path):
    t = ok_transport('{"verdict": "CLEAR", "findings": []}')
    result = run_review("d", cfg(tmp_path), transport=t)
    d = to_manifest_dict(result, "a" * 40)
    assert d["verdict"] == VERDICT_CLEAR
    assert d["findings_count"] == 0
    assert d["reviewed_sha"] == "a" * 40
    assert d["at"]
