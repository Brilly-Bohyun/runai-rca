"""A fact's identity must not depend on WHEN the run computed it.

For an unresolved alert `causal_evidence_time_range` ends at `now()`. That value
reached `stable_fact_id`, so every seeding phase minted a fresh fact for the same
observation and a later re-derivation could no longer name it.
"""

from app.collectors.base import CollectorResult, artifact
from app.services.evidence_blackboard import Blackboard, normalize_artifact

START = "2026-07-31T04:25:37Z"
FIRED = "2026-07-31T04:30:37.599Z"


def _card(summary: str = "PodScheduled=False (reason=unschedulable)"):
    return artifact(
        agent="kubernetes",
        source="kubernetes",
        type="kubernetes_pod_scheduling",
        status="ok",
        confidence="high",
        summary=summary,
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


def _fact(card, end: str, *, start: str = START, run_id: str = "INC-1"):
    return normalize_artifact(
        card,
        entity="pod:frac-test2-0-0",
        timestamp=FIRED,
        observed_window_start=start,
        observed_window_end=end,
        run_id=run_id,
        require_typed_observation=True,
    )


def test_a_moving_causal_end_does_not_change_the_fact_id() -> None:
    card = _card()

    early = _fact(card, "2026-07-31T04:33:13Z")
    late = _fact(card, "2026-07-31T04:41:17Z")

    assert early.fact_id == late.fact_id


def test_reseeding_later_in_the_run_does_not_mint_a_phantom_fact() -> None:
    """Pipeline seeds, then drill-down seeds again minutes later — one fact."""
    card = _card()
    board = Blackboard()
    result = CollectorResult(agent="kubernetes", status="ok", summary="", artifacts=[card])
    for end in ("2026-07-31T04:33:09Z", "2026-07-31T04:34:50Z", "2026-07-31T04:35:19Z"):
        board.add_result(
            "kubernetes",
            result,
            entity="pod:frac-test2-0-0",
            timestamp=FIRED,
            observed_window_start=START,
            observed_window_end=end,
        )

    assert len(board.facts()) == 1


def test_a_collector_declared_window_still_identifies_the_fact() -> None:
    """A declared window is part of WHAT was observed, so it must keep isolating."""
    def declared(start: str, end: str):
        card = _card()
        card.result["observation"]["evidence_window"] = {"start": start, "end": end}
        return _fact(card, "2026-07-31T04:41:17Z")

    incident = declared("2026-07-31T04:29:00Z", "2026-07-31T04:30:00Z")
    last_month = declared("2026-06-30T00:00:00Z", "2026-06-30T00:01:00Z")

    assert incident.fact_id != last_month.fact_id


def test_the_incident_start_still_separates_two_incidents() -> None:
    card = _card()

    assert _fact(card, "2026-07-31T04:41:17Z").fact_id != _fact(
        card, "2026-06-30T00:10:00Z", start="2026-06-30T00:00:00Z"
    ).fact_id


def test_run_identity_still_separates_two_runs() -> None:
    card = _card()

    assert _fact(card, "2026-07-31T04:41:17Z").fact_id != _fact(
        card, "2026-07-31T04:41:17Z", run_id="INC-2"
    ).fact_id
