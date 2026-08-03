"""R1: the published Self-Check trail must not contradict the headline.

Real report: headline insufficient_evidence, then a reanalysis note "...반증되어
재분석 -> 재분석 결론: insufficient_evidence", then a LATER round's own note
"...추가 조사 -> 결론: observability_accuracy". A subsequent harness/refuted-top
decision moved the headline back to insufficient_evidence AFTER that note was
already written into analysis_detail -- the last thing the operator read
contradicted the conclusion.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.schemas import Alert, AlertAnalysisRequest, AlertAnalysisResponse
from app.services import pipeline
from app.services.root_cause_ranking import RankedCause
from tests.test_orchestrator import make_settings


def _response(detail: str) -> AlertAnalysisResponse:
    return AlertAnalysisResponse(
        status="ok",
        thread_ts="",
        analysis=detail,
        analysis_summary="summary",
        analysis_detail=detail,
        analysis_type="firing",
        analysis_quality="medium",
        root_cause_family="insufficient_evidence",
        missing_data=[],
        warnings=[],
        capabilities={},
        context={},
        artifacts=[],
    )


def _state(settings):
    state = pipeline.new_state(
        settings,
        AlertAnalysisRequest(alert=Alert(status="firing", labels={"alertname": "X"})),
        collectors=[],
    )
    state.results = []
    return state


@pytest.mark.asyncio
async def test_stale_reanalysis_note_gets_a_final_conclusion_line() -> None:
    settings = replace(make_settings(), enable_rca_output_harness=True)
    state = _state(settings)
    state.root_cause_candidates = [RankedCause("insufficient_evidence", "low", 0.0)]
    # A reanalysis round earlier concluded a DIFFERENT family than the final one.
    state.reanalysis_note_family = "observability_accuracy"
    state.response = _response(
        "## Root Cause\n\nNo cause confirmed.\n\n"
        "## Self-Check\n\n"
        "낮은 확신/증거 공백 때문에 추가 조사를 수행했습니다 → 결론: observability_accuracy\n\n"
        "## Appendix\n\nDetails."
    )

    await pipeline.harness_stage(state)

    detail = state.response.analysis_detail
    assert state.response.root_cause_family == "insufficient_evidence"
    appendix_index = detail.index("## Appendix")
    self_check_index = detail.index("## Self-Check")
    assert self_check_index < appendix_index, "the stale round note stays as history"
    assert "결론: observability_accuracy" in detail, "history is not scrubbed"
    # The reconciling line is the LAST thing before the appendix, and it names
    # the FINAL family, not the stale note's family.
    final_line_index = detail.index("Final conclusion")
    assert self_check_index < final_line_index < appendix_index
    assert "insufficient_evidence" in detail[final_line_index : appendix_index]
    assert state.response.analysis == state.response.analysis_detail


@pytest.mark.asyncio
async def test_matching_note_family_adds_no_reconciliation_line() -> None:
    """Guard against noise: when the note's family already matches the final
    headline, nothing extra is inserted."""
    settings = replace(make_settings(), enable_rca_output_harness=True)
    state = _state(settings)
    state.root_cause_candidates = [RankedCause("insufficient_evidence", "low", 0.0)]
    state.reanalysis_note_family = "insufficient_evidence"
    state.response = _response(
        "## Root Cause\n\nNo cause confirmed.\n\n"
        "## Self-Check\n\n결론: insufficient_evidence\n\n## Appendix\n\nDetails."
    )

    await pipeline.harness_stage(state)

    assert "Final conclusion" not in state.response.analysis_detail


@pytest.mark.asyncio
async def test_no_reanalysis_note_adds_no_reconciliation_line() -> None:
    """Guard against noise: an ordinary run (no reanalysis at all) is untouched."""
    settings = replace(make_settings(), enable_rca_output_harness=True)
    state = _state(settings)
    state.root_cause_candidates = [RankedCause("gpu_hardware_error", "high", 9.0)]
    state.response = _response("## Root Cause\n\nXID 79 [E01].\n\n## Appendix\n\nDetails.")

    await pipeline.harness_stage(state)

    assert "Final conclusion" not in state.response.analysis_detail


@pytest.mark.asyncio
async def test_korean_reconciliation_line_when_report_language_is_ko() -> None:
    settings = replace(make_settings(), enable_rca_output_harness=True, language="ko")
    state = _state(settings)
    state.root_cause_candidates = [RankedCause("insufficient_evidence", "low", 0.0)]
    state.reanalysis_note_family = "observability_accuracy"
    state.response = _response(
        "## 2. 원인\n\n원인 미확인.\n\n## Self-Check\n\n결론: observability_accuracy\n\n"
        "## 부록\n\n세부사항."
    )

    await pipeline.harness_stage(state)

    detail = state.response.analysis_detail
    assert "최종 결론" in detail
    final_line_index = detail.index("최종 결론")
    appendix_index = detail.index("## 부록")
    assert final_line_index < appendix_index
    assert "insufficient_evidence" in detail[final_line_index:appendix_index]
