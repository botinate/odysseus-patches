from odysseus_patches.review import (
    Finding,
    ReviewResult,
    VERDICT_CLEAR,
    VERDICT_ERROR,
    VERDICT_FINDINGS,
    _merge_results,
    _parse_verdict,
    _split_diff,
)

DIFF_A = "diff --git a/src/a.py b/src/a.py\n+print('a')\n"
DIFF_B = "diff --git a/src/b.py b/src/b.py\n+print('b')\n"


def test_parse_clear():
    r = _parse_verdict('Sure! {"verdict": "CLEAR", "findings": []}')
    assert r.verdict == VERDICT_CLEAR
    assert r.findings == []


def test_parse_findings():
    raw = (
        '{"verdict": "FINDINGS", "findings": [{"severity": "high", '
        '"file": "src/x.py", "description": "curl to unknown host"}]}'
    )
    r = _parse_verdict("prose before " + raw + " prose after")
    assert r.verdict == VERDICT_FINDINGS
    assert r.findings == [Finding("high", "src/x.py", "curl to unknown host")]


def test_parse_garbage_is_error():
    r = _parse_verdict("I think it looks fine!")
    assert r.verdict == VERDICT_ERROR


def test_parse_bad_verdict_value_is_error():
    r = _parse_verdict('{"verdict": "MAYBE", "findings": []}')
    assert r.verdict == VERDICT_ERROR


def test_parse_tolerates_missing_optional_finding_keys():
    r = _parse_verdict('{"verdict": "FINDINGS", "findings": [{"description": "odd"}]}')
    assert r.findings == [Finding("unknown", "", "odd")]


def test_split_small_diff_is_single_chunk():
    assert _split_diff(DIFF_A + DIFF_B, cap=10_000) == [DIFF_A + DIFF_B]


def test_split_large_diff_per_file():
    chunks = _split_diff(DIFF_A + DIFF_B, cap=len(DIFF_A) + 5)
    assert chunks == [DIFF_A, DIFF_B]


def test_merge_any_findings_wins():
    clear = ReviewResult(VERDICT_CLEAR, [])
    findings = ReviewResult(VERDICT_FINDINGS, [Finding("low", "f", "d")])
    merged = _merge_results([clear, findings])
    assert merged.verdict == VERDICT_FINDINGS
    assert merged.findings == [Finding("low", "f", "d")]


def test_merge_error_beats_clear():
    clear = ReviewResult(VERDICT_CLEAR, [])
    err = ReviewResult(VERDICT_ERROR, [])
    assert _merge_results([clear, err]).verdict == VERDICT_ERROR


def test_merge_all_clear():
    assert _merge_results([ReviewResult(VERDICT_CLEAR, [])] * 2).verdict == VERDICT_CLEAR
