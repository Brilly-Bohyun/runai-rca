"""Rejecting every scoped positive fact is a target bug, and must say so.

`rejected_evidence_links` only records links somebody tried to cite, so a run
whose target identity is wrong discards its whole board in silence.
"""

from dataclasses import replace

from app.collectors.base import CollectorResult, artifact
from app.progress import ProgressReporter
from app.schemas import Alert, AlertAnalysisRequest, AlertAnalysisResponse
from app.services import pipeline
from app.services.evidence_blackboard import Blackboard
from tests.test_orchestrator import make_settings, make_target

FIRED_AT = "2026-07-31T04:30:37.599Z"
WINDOW = ("2026-07-31T04:25:37Z", "2026-07-31T04:45:37Z")


def _scoped_positive_card():
    return artifact(
        agent="kubernetes",
        source="kubernetes",
        type="kubernetes_pod_scheduling",
        status="ok",
        confidence="high",
        summary="PodScheduled=False (reason=unschedulable)",
        result={
            "observation": {
                "predicate": "kubernetes_pod_scheduling",
                "polarity": "present",
                "coverage": "scoped",
                "scheduling_reason": "unschedulable",
                "target_identity_verified": True,
                "observed_entity": {
                    "kind": "pod",
                    "name": "frac-test2-0-0",
                    "namespace": "runai-test1",
                },
            }
        },
    )


def _state(namespace: str, cards) -> pipeline.PipelineState:
    target = replace(
        make_target(),
        namespace=namespace,
        pod="frac-test2-0-0",
        workload_name="frac-test2-0",
        fired_at=FIRED_AT,
    )
    state = pipeline.PipelineState(
        settings=make_settings(),
        request=AlertAnalysisRequest(
            alert=Alert(status="firing", labels={}, annotations={}, startsAt=FIRED_AT)
        ),
        target=target,
        progress=ProgressReporter(make_settings(), run_id=""),
        masker=None,
        collectors=[],
    )
    state.blackboard = Blackboard()
    if cards:
        state.blackboard.add_result(
            "kubernetes",
            CollectorResult(agent="kubernetes", status="ok", summary="", artifacts=cards),
            entity="pod:frac-test2-0-0",
            timestamp=FIRED_AT,
            observed_window_start=WINDOW[0],
            observed_window_end=WINDOW[1],
        )
    return state


def _response():
    return AlertAnalysisResponse(
        status="ok",
        thread_ts="",
        analysis="",
        analysis_summary="",
        analysis_detail="",
        analysis_type="firing",
        analysis_quality="degraded",
        root_cause_family="insufficient_evidence",
        missing_data=[],
        warnings=[],
        capabilities={},
        context={},
        artifacts=[],
    )


def test_a_wrong_target_namespace_is_reported_as_a_target_problem() -> None:
    """The exact INC-…-000001 shape: facts on the board, none eligible."""
    state = _state("runai", [_scoped_positive_card()])
    response = _response()

    pipeline._warn_on_starved_evidence(state, response)

    assert any("check the analysis target identity" in w for w in response.warnings)
    assert any("conflicts with target entity scope" in w for w in response.warnings)


def test_a_correct_target_stays_silent() -> None:
    state = _state("runai-test1", [_scoped_positive_card()])
    response = _response()

    pipeline._warn_on_starved_evidence(state, response)

    assert response.warnings == []


def test_an_honest_evidence_gap_stays_silent() -> None:
    """Nothing scoped and positive on the board is a real gap, not a bug."""
    response = _response()

    pipeline._warn_on_starved_evidence(_state("runai-test1", []), response)

    assert response.warnings == []


def test_a_blackboard_without_facts_is_not_an_error() -> None:
    state = _state("runai-test1", [])
    state.blackboard = object()
    response = _response()

    pipeline._warn_on_starved_evidence(state, response)

    assert response.warnings == []


def test_starvation_check_is_wired_into_the_abstain_path() -> None:
    import inspect

    source = inspect.getsource(pipeline)
    marker = source.index('if final_family == "insufficient_evidence":')
    assert "_warn_on_starved_evidence(state, response)" in source[marker : marker + 260]
