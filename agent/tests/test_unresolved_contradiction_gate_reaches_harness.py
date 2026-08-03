"""G4 fix: end-to-end proof that a scoped contradicting artifact travels all
the way from the deterministic ranker to harness.evaluate's
``unresolved_contradiction`` gate, without the contradicted candidate ever
reading as a confident conclusion.

Before the fix, a candidate with a scoped contradiction was collected and
typed correctly, but two producers in root_cause_ranking.py silently kept it
from ever becoming ``candidates[0]``:

1. ``rank_root_cause_candidates``'s ``live_ranked`` filter required
   confidence in {"medium", "high"}; ``_confidence`` forces "low" the instant
   a candidate has a contradiction, so the candidate was excluded from
   ``live_ranked`` and the run fell back to a contradiction-blind
   ``insufficient_evidence`` headline instead.
2. ``merge_open_world_candidates`` dropped (``continue``) any open-world
   ledger entry with a non-empty contradiction list before ever constructing
   its ``RankedCause``.

``harness.evaluate``'s ``unresolved_contradiction`` gate -- the mechanism
that turns "we found something that argues against this" into a visible
abstain -- only ever inspects ``candidates[0]``. With the contradiction
downgraded away before that point, the gate was correctly wired but
structurally unreachable in the live pipeline (see
test_unresolved_contradiction_gate_unreachable.py, which pinned that old
behaviour and has since been updated to pin the fix instead).

This file proves the fixed path with the REAL ranker (not a hand-built
``RankedCause``): a scoped contradicting artifact goes in,
``rank_root_cause_candidates`` comes out with a candidate carrying
``contradiction_evidence_ids``, and ``harness.evaluate`` -- called directly,
unmodified -- reports ``unresolved_contradiction: True``.

Two over-correction guards close the loop:

* ``test_contradicted_candidate_never_reads_as_high_confidence_even_when_
  evidence_would_otherwise_clear_it`` proves the fix did not simply delete
  the confidence floor -- the SAME evidence strength that scores "high"
  cleanly still scores "low" once contradicted, and the harness's
  ``diagnosis_state`` is "provisional", never "supported".
* ``test_uncontradicted_candidate_is_completely_unaffected_by_the_fix``
  pins concrete family/score/confidence values for a plain, uncontradicted
  candidate and independently re-derives them against the PRE-fix
  ``live_ranked`` filter to prove the OR-clause this fix added is a true
  no-op whenever there is no contradiction.
"""

from __future__ import annotations

from app.collectors.base import AnalysisTarget, CollectorResult, artifact
from app.services.harness import assign_evidence_ids, evaluate
from app.services.root_cause_ranking import rank_root_cause_candidates
from tests.test_harness import _response


def _target(**overrides: str) -> AnalysisTarget:
    base = dict(
        cluster="prod",
        project="research",
        queue="research-default",
        namespace="runai-research",
        workload_name="trainer",
        workload_type="Training",
        runai_workload_id="wl-1",
        node="gpu-node-17",
        pod="trainer-abc-x1",
        severity="critical",
        alert_name="KubePodNotReady",
    )
    base.update(overrides)
    return AnalysisTarget(**base)


def _scoped_kubernetes_results() -> list[CollectorResult]:
    """One family (``image_pull_error``) with a scoped supporting artifact
    AND a scoped, directly contradicting artifact -- both real typed
    observations from the SAME canonical collector, not context/metadata
    text a keyword scan could confuse for evidence."""
    # harness.evaluate derives its OWN eligibility (evidence_blackboard.
    # normalize_artifact, require_typed_observation=True) when no
    # evidence_eligibility/eligible_evidence_ids is supplied. Unlike the
    # ranker's own no-context fallback gate, that path demotes a
    # scoped+present/absent observation with no declared ``observed_entity``
    # to polarity="unknown" ("entity_not_named"), so the link is filtered out
    # as ineligible. Name the entity, matching the established
    # tests.test_harness._scoped_observation pattern.
    entity = {"observed_entity": {"kind": "pod", "name": "trainer-abc-x1"}}
    support = artifact(
        agent="kubernetes",
        source="kubernetes",
        type="warning_event",
        status="ok",
        confidence="high",
        summary="ImagePullBackOff ErrImagePull pull access denied",
        result={"observation": {"polarity": "present", "coverage": "scoped", **entity}},
    )
    contradiction = artifact(
        agent="kubernetes",
        source="kubernetes",
        type="warning_event",
        status="ok",
        confidence="high",
        summary="ImagePullBackOff was not observed for the target pod",
        result={"observation": {"polarity": "absent", "coverage": "scoped", **entity}},
    )
    result = CollectorResult(
        agent="kubernetes",
        status="ok",
        summary="",
        artifacts=[support, contradiction],
    )
    assign_evidence_ids([result])
    return [result]


def test_scoped_contradiction_reaches_harness_unresolved_contradiction_gate() -> None:
    """The full path: rank_root_cause_candidates -> harness.evaluate."""
    results = _scoped_kubernetes_results()
    candidates = rank_root_cause_candidates(_target(), results)

    top = candidates[0]
    assert top.family == "image_pull_error"
    assert top.confidence == "low"
    assert top.contradiction_evidence_ids == ["E02"]

    response = _response(
        "## Root Cause\n\nLikely an image pull failure [E01], "
        "despite a counter-signal [E02]."
    )
    verdict = evaluate(response, results, candidates)

    assert verdict.gates["unresolved_contradiction"] is True
    assert verdict.claims[0]["contradicting_evidence"] == ["E02"]
    assert "unresolved_contradiction" in verdict.failed_gates


def test_contradicted_candidate_never_reads_as_high_confidence() -> None:
    """Over-correction guard #1: same evidence strength, only a contradiction
    differs. 3 canonical kubernetes facts + 1 loki fact score 7.0 across 2
    independent source groups -- comfortably clearing the >=5.0-points/
    >=2-groups HIGH bar, proven below by running the identical support with
    NO contradiction and getting "high". Adding one scoped, directly
    contradicting artifact must flip confidence to "low" and keep the
    harness diagnosis "provisional" -- never "high" / "supported" -- while
    STILL reaching candidates[0] carrying the contradiction."""
    entity = {"observed_entity": {"kind": "pod", "name": "trainer-abc-x1"}}

    def _support(i: int):
        return artifact(
            agent="kubernetes",
            source="kubernetes",
            type="warning_event",
            status="ok",
            confidence="high",
            summary=f"ImagePullBackOff ErrImagePull pull access denied variant {i}",
            result={"observation": {"polarity": "present", "coverage": "scoped", **entity}},
        )

    loki_support = artifact(
        agent="loki",
        source="loki",
        type="log",
        status="ok",
        confidence="high",
        summary="ImagePullBackOff ErrImagePull registry denies pull",
        result={"observation": {"polarity": "present", "coverage": "scoped", **entity}},
    )
    contradiction = artifact(
        agent="kubernetes",
        source="kubernetes",
        type="warning_event",
        status="ok",
        confidence="high",
        summary="ImagePullBackOff was not observed for the target pod",
        result={"observation": {"polarity": "absent", "coverage": "scoped", **entity}},
    )

    # Counterfactual: the identical support, with NO contradiction, is high.
    clean_k8s = CollectorResult(
        agent="kubernetes",
        status="ok",
        summary="",
        artifacts=[_support(0), _support(1), _support(2)],
    )
    clean_loki = CollectorResult(agent="loki", status="ok", summary="", artifacts=[loki_support])
    clean_candidates = rank_root_cause_candidates(_target(), [clean_k8s, clean_loki])
    assert clean_candidates[0].score == 7.0
    assert clean_candidates[0].confidence == "high"

    # Same evidence, plus the contradiction.
    k8s_result = CollectorResult(
        agent="kubernetes",
        status="ok",
        summary="",
        artifacts=[_support(0), _support(1), _support(2), contradiction],
    )
    loki_result = CollectorResult(agent="loki", status="ok", summary="", artifacts=[loki_support])
    results = [k8s_result, loki_result]
    assign_evidence_ids(results)
    candidates = rank_root_cause_candidates(_target(), results)
    top = candidates[0]

    assert top.family == "image_pull_error"
    assert top.score == 7.0  # identical underlying evidence strength
    assert top.confidence == "low"  # never "high" -- the guard
    assert top.contradiction_evidence_ids  # non-empty: it still travels

    response = _response(
        "## Root Cause\n\nLikely an image pull failure, despite a counter-signal."
    )
    verdict = evaluate(response, results, candidates)

    assert verdict.claims[0]["confidence"] == "low"
    assert verdict.diagnosis_state == "provisional"  # never "supported"
    assert verdict.gates["unresolved_contradiction"] is True


def test_uncontradicted_candidate_is_completely_unaffected_by_the_fix() -> None:
    """Over-correction guard #2: a plain, uncontradicted candidate is pinned
    to concrete values, not just "it still passes".

    The fix only added an ``or candidate.contradiction_evidence_ids`` arm to
    ``live_ranked``'s boolean gate. For a candidate with no contradiction
    that arm is False (asserted below), so the gate's truth value is decided
    exclusively by the untouched original ``confidence in {"medium",
    "high"}`` arm -- an ``X or False`` that is provably identical to the
    pre-fix ``X``, not merely observed to still work."""
    entity = {"observed_entity": {"kind": "pod", "name": "trainer-abc-x1"}}
    support = artifact(
        agent="kubernetes",
        source="kubernetes",
        type="warning_event",
        status="ok",
        confidence="high",
        summary="ImagePullBackOff ErrImagePull pull access denied",
        result={"observation": {"polarity": "present", "coverage": "scoped", **entity}},
    )
    result = CollectorResult(agent="kubernetes", status="ok", summary="", artifacts=[support])
    assign_evidence_ids([result])

    candidates = rank_root_cause_candidates(_target(), [result])
    top = candidates[0]

    # Concrete pinned values.
    assert top.family == "image_pull_error"
    assert top.score == 2.0
    assert top.confidence == "medium"
    assert top.contradiction_evidence_ids == []

    # The new OR-arm is a provable no-op for this candidate: arm B is False,
    # and arm A alone already admits it -- exactly the pre-fix behaviour.
    assert not top.contradiction_evidence_ids
    assert top.confidence in {"medium", "high"}
