"""Some causes are only ever witnessed by one source group.

An OOMKilled container or an unschedulable Pod condition exists in the
Kubernetes API and nowhere else; a two-telemetry-group floor for early-stop
made those permanently unreachable. The exception is the controlled reason
VOCABULARY, never the card's prose.
"""

from dataclasses import replace

from app.collectors.base import CollectorResult, artifact
from app.services.evidence_blackboard import Blackboard, normalize_artifact
from app.services.investigator import _evidence_sufficiency
from tests.test_orchestrator import make_target

FIRED_AT = "2026-07-31T04:30:37.599Z"
WINDOW = ("2026-07-31T04:25:37Z", "2026-07-31T04:45:37Z")


def _card(*, reason: str | None, summary: str):
    observation = {
        "predicate": "kubernetes_target_container_lifecycle",
        "polarity": "present",
        "coverage": "scoped",
        "target_identity_verified": True,
        "observed_entity": {"kind": "pod", "name": "trainer-0", "namespace": "runai-vision"},
    }
    if reason:
        observation["container_reason"] = reason
    return artifact(
        agent="kubernetes",
        source="kubernetes",
        type="kubernetes_container_lifecycle",
        status="ok",
        confidence="high",
        summary=summary,
        result={"observation": observation},
    )


def _target():
    return replace(make_target(), namespace="runai-vision", pod="trainer-0", fired_at=FIRED_AT)


def _board(card):
    board = Blackboard()
    board.add_result(
        "kubernetes",
        CollectorResult(agent="kubernetes", status="ok", summary="", artifacts=[card]),
        entity="pod:trainer-0",
        timestamp=FIRED_AT,
        observed_window_start=WINDOW[0],
        observed_window_end=WINDOW[1],
    )
    return board


def _verdict(card, family: str):
    board = _board(card)
    fact_id = next(iter(board.facts())).fact_id
    ledger = [
        {"id": "H1", "family": family, "status": "supported", "evidence_for": [fact_id]}
    ]
    evidence = {
        "kubernetes": CollectorResult(
            agent="kubernetes", status="ok", summary="", artifacts=[card]
        )
    }
    return _evidence_sufficiency(ledger, evidence, board, _target())


def test_a_typed_kubernetes_reason_is_dispositive_on_its_own() -> None:
    verdict = _verdict(
        _card(reason="OOMKilled", summary="target container lastTerminated reason=OOMKilled"),
        "workload_runtime_error",
    )

    assert verdict["sufficient"] is True
    assert verdict["reason"] == "dispositive_signature"


def test_the_same_finding_as_prose_still_needs_a_second_source_group() -> None:
    """Without the typed reason the card is prose, and prose is not dispositive."""
    verdict = _verdict(
        _card(reason=None, summary="target container lastTerminated reason=OOMKilled"),
        "workload_runtime_error",
    )

    assert verdict["sufficient"] is False


def test_a_typed_reason_cannot_be_dispositive_for_another_family() -> None:
    """The vocabulary names ONE family; it must not license an unrelated one."""
    verdict = _verdict(
        _card(reason="OOMKilled", summary="pod is pending and unschedulable, 0/3 nodes"),
        "k8s_scheduling_error",
    )

    assert verdict["sufficient"] is False


def test_a_reason_is_never_projected_onto_a_non_positive_fact() -> None:
    """Refutation reads scoped ABSENCES; a typed reason must not narrow which
    family an absence can contradict."""
    from dataclasses import replace as replace_fact

    from app.services.investigator import _fact_as_artifact

    fact = normalize_artifact(
        _card(reason="OOMKilled", summary="reason=OOMKilled"),
        entity="pod:trainer-0",
        timestamp=FIRED_AT,
        observed_window_start=WINDOW[0],
        observed_window_end=WINDOW[1],
        require_typed_observation=True,
    )
    absent = replace_fact(fact, polarity="absent")

    projected = _fact_as_artifact(absent).result["observation"]

    assert "container_reason" not in projected
    assert "container_reason" in _fact_as_artifact(fact).result["observation"]


def test_carrying_the_typed_reason_does_not_change_the_evidence_id() -> None:
    """Evidence IDs are response-local and cited in reports; they must not churn."""
    card = _card(reason="OOMKilled", summary="reason=OOMKilled")
    seeded = normalize_artifact(
        card,
        entity="pod:trainer-0",
        timestamp=FIRED_AT,
        observed_window_start=WINDOW[0],
        observed_window_end=WINDOW[1],
        require_typed_observation=True,
    )

    assert seeded.typed_reason == "oomkilled"
    assert seeded.fact_id == next(iter(_board(card).facts())).fact_id
