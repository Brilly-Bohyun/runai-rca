"""The auto-attach safety net must survive the pipeline's own fact seeding.

`Blackboard.add_result` is called by the pipeline WITH the incident timestamp and
causal window; `evidence_id_for` re-hashes without them, so the ID it produced
never matched a seeded fact and the attachment silently did nothing in every
real run.  These tests pin the seeding the pipeline actually performs.
"""

from dataclasses import replace

from app.collectors.base import CollectorResult, artifact
from app.services.evidence_blackboard import Blackboard
from app.services.investigator import _apply_ledger_updates, _eligible_support_ids
from tests.test_orchestrator import make_target

WINDOW = ("2026-07-31T04:25:37Z", "2026-07-31T04:45:37Z")
FIRED_AT = "2026-07-31T04:30:37.599Z"


def _target():
    return replace(
        make_target(),
        namespace="runai-test1",
        pod="frac-test2-0-0",
        workload_name="frac-test2-0",
        fired_at=FIRED_AT,
    )


def _scheduling_card():
    return artifact(
        agent="kubernetes",
        source="kubernetes",
        type="kubernetes_pod_scheduling",
        status="ok",
        confidence="high",
        summary="대상 Pod의 PodScheduled 조건이 False입니다(reason=unschedulable).",
        result={
            "observation": {
                "predicate": "kubernetes_pod_scheduling",
                "kind": "kubernetes_pod_scheduling",
                "polarity": "present",
                "coverage": "scoped",
                "scheduling_reason": "unschedulable",
                "target_identity_verified": True,
                "observed_entity": {
                    "kind": "pod",
                    "name": "frac-test2-0-0",
                    "namespace": "runai-test1",
                },
            },
            "condition": {
                "type": "PodScheduled",
                "status": "False",
                "reason": "unschedulable",
                "message": "<dgx01>: Node didn't have enough resources: GPUs, requested: 8 X 0.8",
            },
        },
    )


def _seed_like_the_pipeline(card):
    board = Blackboard()
    board.add_result(
        "kubernetes",
        CollectorResult(
            agent="kubernetes", status="ok", summary="scheduling", artifacts=[card]
        ),
        entity="pod:frac-test2-0-0",
        timestamp=FIRED_AT,
        observed_window_start=WINDOW[0],
        observed_window_end=WINDOW[1],
    )
    return board


def test_evidence_id_for_does_not_match_a_pipeline_seeded_fact() -> None:
    """The exact identity mismatch that killed the attachment."""
    card = _scheduling_card()
    board = _seed_like_the_pipeline(card)

    assert board.evidence_id_for(card) not in {f.fact_id for f in board.facts()}


def test_typed_support_attaches_under_pipeline_seeding() -> None:
    card = _scheduling_card()
    board = _seed_like_the_pipeline(card)
    ledger = [{"id": "H1", "family": "k8s_scheduling_error", "status": "testing"}]

    _apply_ledger_updates(
        ledger,
        [],
        blackboard=board,
        artifacts=[card],
        eligible_support_ids=_eligible_support_ids(board),
    )

    assert ledger[0]["evidence_for"] == [next(iter(board.facts())).fact_id]


def test_attachment_still_refuses_a_family_the_card_does_not_support() -> None:
    card = _scheduling_card()
    board = _seed_like_the_pipeline(card)
    ledger = [{"id": "H1", "family": "image_pull_error", "status": "testing"}]

    _apply_ledger_updates(
        ledger,
        [],
        blackboard=board,
        artifacts=[card],
        eligible_support_ids=_eligible_support_ids(board),
    )

    assert not ledger[0].get("evidence_for")


def test_attachment_is_skipped_when_two_facts_share_one_artifact_identity() -> None:
    """Ambiguity must stay uncitable: same wording, two different incidents."""
    card = _scheduling_card()
    board = _seed_like_the_pipeline(card)
    board.add_result(
        "kubernetes",
        CollectorResult(
            agent="kubernetes", status="ok", summary="scheduling", artifacts=[card]
        ),
        entity="pod:frac-test2-0-0",
        timestamp="2026-06-30T00:00:00Z",
        observed_window_start="2026-06-30T00:00:00Z",
        observed_window_end="2026-06-30T00:10:00Z",
    )
    ledger = [{"id": "H1", "family": "k8s_scheduling_error", "status": "testing"}]

    assert len(board.facts()) == 2
    _apply_ledger_updates(
        ledger,
        [],
        blackboard=board,
        artifacts=[card],
        eligible_support_ids=_eligible_support_ids(board),
    )

    assert not ledger[0].get("evidence_for")


def _out_of_window_board(card):
    board = Blackboard()
    board.add_result(
        "kubernetes",
        CollectorResult(
            agent="kubernetes", status="ok", summary="scheduling", artifacts=[card]
        ),
        entity="pod:frac-test2-0-0",
        timestamp="2026-01-01T00:00:00Z",
        observed_window_start="2026-01-01T00:00:00Z",
        observed_window_end="2026-01-01T00:10:00Z",
    )
    return board


def test_out_of_window_support_is_refused_when_the_target_is_known() -> None:
    """Reviving the attachment must not admit what the trace and harness discard.

    The card is present/scoped/target-verified, so polarity and coverage alone
    accept it; only the incident window rejects it.
    """
    card = _scheduling_card()
    board = _out_of_window_board(card)
    ledger = [{"id": "H1", "family": "k8s_scheduling_error", "status": "testing"}]

    _apply_ledger_updates(
        ledger,
        [],
        blackboard=board,
        artifacts=[card],
        eligible_support_ids=_eligible_support_ids(board, _target()),
    )

    assert not ledger[0].get("evidence_for")


def test_in_window_support_still_attaches_with_the_target_applied() -> None:
    card = _scheduling_card()
    board = _seed_like_the_pipeline(card)
    ledger = [{"id": "H1", "family": "k8s_scheduling_error", "status": "testing"}]

    _apply_ledger_updates(
        ledger,
        [],
        blackboard=board,
        artifacts=[card],
        eligible_support_ids=_eligible_support_ids(board, _target()),
    )

    assert ledger[0]["evidence_for"] == [next(iter(board.facts())).fact_id]


def test_a_caller_without_a_target_keeps_the_looser_verdict() -> None:
    """Back-compat: no target must not silently starve the ledger."""
    card = _scheduling_card()

    assert _eligible_support_ids(_out_of_window_board(card), None)
