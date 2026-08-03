"""An abstained run must keep saying WHY it abstained.

`abstain()` sets the family to `insufficient_evidence`, and every gate in
`harness.evaluate` is guarded by `not insufficient`. Re-evaluating the rewritten
document therefore reports every hard gate as False — which is what got
persisted. The backend's knowledge-promotion veto (`harnessHardGatesPassed` in
backend/internal/server/knowledge.go) reads that same map, so it could only ever
fail on a missing harness, never on a real violation.
"""

from app.schemas import AlertAnalysisResponse
from app.services.harness import HarnessVerdict, evaluate, payload
from app.services.root_cause_ranking import RankedCause


def _response(detail: str = "## Root Cause\n\nA confident cause with no evidence.") -> AlertAnalysisResponse:
    return AlertAnalysisResponse(
        status="ok",
        thread_ts="",
        analysis=detail,
        analysis_summary="summary",
        analysis_detail=detail,
        analysis_type="firing",
        analysis_quality="medium",
        root_cause_family="gpu_hardware_error",
        missing_data=[],
        warnings=[],
        capabilities={},
        context={},
        artifacts=[],
    )


def test_evaluate_reports_no_gate_once_the_family_is_insufficient() -> None:
    """The mechanism behind the bug — pinned so it cannot be mistaken for a fix."""
    gated = evaluate(
        _response(), [], [RankedCause("gpu_hardware_error", "high", 9.0)]
    )
    after_abstain = evaluate(
        _response(), [], [RankedCause("insufficient_evidence", "low", 0.0)]
    )

    assert gated.failed_gates, "a high-confidence unsupported claim must fail a gate"
    assert not after_abstain.failed_gates


def test_persisted_payload_keeps_the_gates_that_forced_the_abstention() -> None:
    gated = evaluate(
        _response(), [], [RankedCause("gpu_hardware_error", "high", 9.0)]
    )
    rescored = evaluate(
        _response(), [], [RankedCause("insufficient_evidence", "low", 0.0)]
    )

    # What harness_stage now persists: the rewritten document's score, the
    # gated document's gate map.
    from dataclasses import replace

    persisted = payload(
        replace(rescored, gates=dict(gated.gates)), status="abstained", repairs=0
    )

    assert persisted["hard_gates"] == gated.gates
    assert persisted["violations"], "an abstained run must name its violations"
    assert persisted["status"] == "abstained"


def test_a_clean_run_still_reports_no_violations() -> None:
    """Guard against the fix inventing violations for healthy runs."""
    clean = HarnessVerdict("supported", 90, {}, {"unsupported_high_confidence": False}, [], [])

    persisted = payload(clean, status="pass", repairs=0)

    assert persisted["violations"] == []
    assert persisted["hard_gates"] == {"unsupported_high_confidence": False}
