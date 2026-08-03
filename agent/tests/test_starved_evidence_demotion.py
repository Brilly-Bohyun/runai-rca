"""No fact ever reaching present+scoped is the common shape (a real run: 121
artifacts, 3 usable) -- and it used to stay silent even when every demoted
fact carried a `demotion_reason` explaining exactly why. This proves the new
branch of `_warn_on_starved_evidence` surfaces that reason instead of leaving
"insufficient evidence" unexplained, both in `warnings` and in the report.
"""

from dataclasses import replace

from app.collectors.base import artifact
from app.services import pipeline
from tests.test_starved_evidence_signal import _response, _scoped_positive_card, _state


def _unavailable_card(agent: str = "prometheus"):
    """No observation envelope at all, a transport failure -- demotion_reason
    resolves to "source_unavailable" (see `_demotion_reason` in
    evidence_blackboard.py)."""
    return artifact(
        agent=agent,
        source=agent,
        type=f"{agent}_query",
        status="unavailable",
        confidence="low",
        summary=f"{agent} unreachable",
    )


def _unscoped_card(*, target_scope_verified: bool = False):
    """Present but only partially scoped, with the collector's own
    verification flag declared -- demotion_reason resolves to
    "target_scope_unverified" when the flag is False, "" (nothing to explain)
    when True."""
    return artifact(
        agent="loki",
        source="loki",
        type="loki_log_query",
        status="partial",
        confidence="low",
        summary="matched log lines but scope unverified",
        result={
            "observation": {
                "predicate": "loki_log_query",
                "polarity": "present",
                "coverage": "partial",
                "target_scope_verified": target_scope_verified,
            }
        },
    )


def test_a_starved_board_names_the_dominant_demotion_reason() -> None:
    """121-artifacts/3-usable shape: nothing reached present+scoped, but two of
    three facts were demoted for the SAME reason -- that reason must lead."""
    state = _state(
        "runai-test1",
        [_unavailable_card("prometheus"), _unavailable_card("loki"), _unscoped_card()],
    )
    response = _response()

    pipeline._warn_on_starved_evidence(state, response)

    assert any(
        "no observation ever reached present+scoped: 2 of 3 fact(s) were demoted, "
        "most commonly (source_unavailable)" in w
        for w in response.warnings
    )
    assert "source_unavailable" in response.analysis_detail
    assert "Why evidence is insufficient" in response.analysis_detail


def test_the_report_line_is_localized_for_korean() -> None:
    state = _state("runai-test1", [_unavailable_card()])
    state.settings = replace(state.settings, language="ko")
    response = _response()

    pipeline._warn_on_starved_evidence(state, response)

    assert "증거가 부족한 이유" in response.analysis_detail
    assert "source_unavailable" in response.analysis_detail


def test_facts_with_no_identifiable_reason_stay_an_honest_gap() -> None:
    """coverage=partial but no collector verification flag fired: demotion_reason
    is "" (best-effort, not a guess) -- still nothing to explain."""
    state = _state("runai-test1", [_unscoped_card(target_scope_verified=True)])
    response = _response()

    pipeline._warn_on_starved_evidence(state, response)

    assert response.warnings == []
    assert response.analysis_detail == ""


def test_a_healthy_run_with_usable_evidence_gains_no_warning_or_report_line() -> None:
    """Noise guard: once ANY fact reaches present+scoped, the demotion branch
    must not run, even with an unrelated demoted fact sitting on the same
    board."""
    state = _state("runai-test1", [_scoped_positive_card(), _unavailable_card()])
    response = _response()

    pipeline._warn_on_starved_evidence(state, response)

    assert response.warnings == []
    assert response.analysis_detail == ""


def test_zero_facts_stays_an_honest_gap() -> None:
    """Pre-existing behaviour (see test_starved_evidence_signal.py) must
    survive the refactor to a shared `all_facts` list."""
    state = _state("runai-test1", [])
    response = _response()

    pipeline._warn_on_starved_evidence(state, response)

    assert response.warnings == []
    assert response.analysis_detail == ""
