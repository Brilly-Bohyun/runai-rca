"""pipeline._known_issue_cause_lines renders each known issue's refs (source/KB
citations authored in knowledge/runai_known_issues.yaml, e.g. "NVIDIA Case
01074073") so the citation reaches the operator instead of stopping at the
loader (app.knowledge._load_runai_known_issues already carries it through).

This flips tests/test_runai_known_issues.py::test_cause_line_does_not_yet_render_refs,
which pins the prior gap -- see that test's docstring."""

from __future__ import annotations

from app.knowledge import load_runai_known_issues
from app.services.pipeline import _known_issue_cause_lines

CATALOG = "knowledge/runai_known_issues.yaml"


def test_cause_line_renders_a_single_ref() -> None:
    catalog = load_runai_known_issues(CATALOG)
    lines = _known_issue_cause_lines(
        catalog, "the administrator prohibited modifying item", "en"
    )
    assert lines
    assert "NVIDIA Case 01074073" in lines[0]


def test_cause_line_renders_refs_in_a_korean_report_too() -> None:
    catalog = load_runai_known_issues(CATALOG)
    lines = _known_issue_cause_lines(
        catalog, "the administrator prohibited modifying item", "ko"
    )
    assert lines
    assert "NVIDIA Case 01074073" in lines[0]


def test_cause_line_comma_joins_multiple_refs() -> None:
    catalog = load_runai_known_issues(CATALOG)
    lines = _known_issue_cause_lines(catalog, "master-restart-policy", "en")
    assert lines
    assert "(NVIDIA Case 01064819, NVIDIA Case 01065900)" in lines[0]


def test_cause_line_has_no_stray_parens_when_refs_are_empty() -> None:
    catalog = load_runai_known_issues(CATALOG)
    # "Scheduler Reclaim Panic On Large GPU Job" is authored with refs: [].
    lines = _known_issue_cause_lines(
        catalog, "reclaim/reclaim.go:91 runtime/panic.go:785", "en"
    )
    assert lines
    assert "()" not in lines[0]
    assert not lines[0].rstrip().endswith("(")
