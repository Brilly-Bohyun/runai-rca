"""Never conclude "no evidence" about evidence the run discarded, silently."""

from app.schemas import AlertAnalysisResponse
from app.services import pipeline
from app.services.pipeline import _public_v3_hypothesis, _warn_on_discarded_support


class _State:
    def __init__(self, links):
        self.investigation_context = {"reasoning_trace_v3": {"rejected_evidence_links": links}}


def _response(warnings=()):
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
        warnings=list(warnings),
        capabilities={},
        context={},
        artifacts=[],
    )


def test_abstain_with_discarded_support_warns() -> None:
    state = _State(
        [
            {
                "hypothesis_id": "H1",
                "evidence_id": "E15",
                "role": "support",
                "reason": "evidence conflicts with target entity scope",
            }
        ]
    )
    response = _response()

    _warn_on_discarded_support(state, response)

    assert any("discarding 1 support link" in warning for warning in response.warnings)
    assert any("conflicts with target entity scope" in warning for warning in response.warnings)


def test_no_warning_without_discarded_support() -> None:
    response = _response()
    _warn_on_discarded_support(_State([]), response)
    assert response.warnings == []


def test_contradiction_only_rejections_do_not_warn() -> None:
    """A dropped refutation is not the starvation this signal is about."""
    response = _response()
    _warn_on_discarded_support(
        _State([{"evidence_id": "E1", "role": "contradict", "reason": "outside window"}]),
        response,
    )
    assert response.warnings == []


def test_missing_trace_is_not_an_error() -> None:
    state = _State([])
    state.investigation_context = {}
    response = _response()
    _warn_on_discarded_support(state, response)
    assert response.warnings == []


def test_published_status_cannot_claim_support_with_no_eligible_evidence() -> None:
    published = _public_v3_hypothesis(
        {"id": "H1", "family": "k8s_scheduling_error", "status": "supported"},
        evidence_for=[],
        evidence_against=[],
        facts_by_evidence={},
    )

    assert published["status"] == "testing"


def test_published_status_is_kept_when_eligible_evidence_survives() -> None:
    published = _public_v3_hypothesis(
        {"id": "H1", "family": "k8s_scheduling_error", "status": "supported"},
        evidence_for=["E15"],
        evidence_against=[],
        facts_by_evidence={},
    )

    assert published["status"] == "supported"


def test_warning_is_wired_into_the_abstain_path() -> None:
    """Guard the call site, not just the helper."""
    import inspect

    source = inspect.getsource(pipeline)
    marker = source.index('if final_family == "insufficient_evidence":')
    assert "_warn_on_discarded_support(state, response)" in source[marker : marker + 200]
