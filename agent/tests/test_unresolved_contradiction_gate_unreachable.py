"""G4 (FIXED): harness.py's ``unresolved_contradiction`` hard gate is
correctly wired AND, as of the fix documented here, reachable in the live
pipeline.

``HarnessVerdict.gates["unresolved_contradiction"]`` (harness.py, in
``evaluate``) is ``bool(not insufficient and contradiction_ids)``, and
``contradiction_ids`` can only be non-empty when the ``top`` ``RankedCause``
passed into ``evaluate`` supplies one -- either via an explicit
``evidence_links=`` kwarg (a direct/manual caller; see
``test_typed_evidence_links_preserve_contradicting_evidence`` in
test_harness.py, which proves that path works) or via
``top.contradiction_evidence_ids`` (the field ``rank_root_cause_candidates``
and ``merge_open_world_candidates`` actually populate).

``pipeline.harness_stage`` never passes ``evidence_links=`` explicitly, so in
the real pipeline it is exclusively the second path. This file originally
pinned two independent reasons that path could never deliver a contradicted
candidate as ``top``; both producers now let the contradiction travel instead
of silently discarding it:

1. ``root_cause_ranking._confidence`` still forces confidence to "low" the
   instant a candidate has ANY ``contradiction_evidence_ids`` (correctly so
   -- a contradicted cause must never read as confident). What changed is
   ``live_ranked`` (inside ``rank_root_cause_candidates``): it used to
   require medium/high outright, which meant "low" also meant "can never be
   candidates[0]". It now admits a "low" candidate specifically when it
   carries a contradiction, so the confirmed-provisional candidate still
   reaches the top slot instead of being replaced by a contradiction-blind
   ``insufficient_evidence``. See
   ``test_typed_fact_counts_once_and_scoped_contradiction_reaches_the_ranked_top``
   in test_root_cause_ranking.py for the ranker-level proof, and
   test_unresolved_contradiction_gate_reaches_harness.py for the full
   ranker -> harness.evaluate path.
2. ``merge_open_world_candidates`` used to ``continue``-skip any open-world
   ledger entry that had a non-empty contradiction list *before*
   constructing the ``RankedCause`` for it, so ``RankedCause(...,
   contradiction_evidence_ids=contradict)`` there was only ever reached with
   ``contradict == []`` -- a dead assignment. It now keeps the entry, forced
   to "low" confidence exactly like the catalog path.

Plus one more test proving harness.py's OWN consumption of
``top.contradiction_evidence_ids`` (no explicit ``evidence_links=`` kwarg) is
correctly wired -- this half never needed a fix; the producers upstream were
the entire defect.
"""

from __future__ import annotations

from app.services.harness import assign_evidence_ids, evaluate
from app.services.root_cause_ranking import (
    RankedCause,
    _confidence,
    _Score,
    merge_open_world_candidates,
)
from tests.test_harness import _response, _result, _scoped_observation


def test_ranked_cause_has_no_evidence_links_attribute_so_that_supplied_link_branch_is_dead() -> None:
    """The first check in harness._supplied_evidence_links (``top.evidence_links``)
    reads a field ``RankedCause`` has never defined."""
    top = RankedCause("gpu_hardware_error", "high", 9.0, contradiction_evidence_ids=["E02"])
    assert getattr(top, "evidence_links", None) is None


def test_confidence_forces_low_whenever_a_candidate_has_a_contradiction() -> None:
    """Same score/agents/groups that would otherwise clear HIGH; only the
    presence of a contradiction id differs. This half of the design is
    unchanged by the G4 fix -- forcing "low" is correct, a contradicted
    cause must not read as confident. What changed is that "low" no longer
    also means live_ranked excludes it: see
    test_typed_fact_counts_once_and_scoped_contradiction_reaches_the_ranked_top
    in test_root_cause_ranking.py."""
    winning_inputs = dict(
        points=100.0,
        force_high=True,
        agents={"loki", "kubernetes"},
        support_source_groups={"loki", "kubernetes_api"},
    )
    clean = _Score(**winning_inputs)
    contradicted = _Score(**winning_inputs, contradiction_evidence_ids={"E02"})

    assert _confidence("gpu_hardware_error", clean, {}) == "high"
    assert _confidence("gpu_hardware_error", contradicted, {}) == "low"


def test_merge_open_world_candidates_keeps_a_contradicted_entry_at_low_confidence() -> None:
    """G4 fix: a contradicted open-world entry used to be dropped entirely
    (the ``continue`` guard this test used to pin), which made
    ``contradiction_evidence_ids=contradict`` in the constructor below it a
    dead assignment -- always ``[]``. It now survives, forced to "low"
    confidence exactly like the catalog path, carrying its contradiction."""
    known = [RankedCause("insufficient_evidence", "low", 0.0)]
    groups = {"E01": "loki", "E02": "kubernetes_api"}
    base_entry = {
        "status": "supported",
        "family": "novel_thing",
        "mechanism": "a novel mechanism causes X",
        "support_evidence_ids": ["E01", "E02"],
        "id": "H1",
    }

    contradicted = merge_open_world_candidates(
        known,
        [{**base_entry, "contradiction_evidence_ids": ["E03"]}],
        fact_groups=groups,
        enabled=True,
    )
    clean = merge_open_world_candidates(
        known,
        [{**base_entry, "contradiction_evidence_ids": []}],
        fact_groups=groups,
        enabled=True,
    )

    contradicted_novel = next(c for c in contradicted if c.novelty == "open_world")
    assert contradicted_novel.confidence == "low"
    assert contradicted_novel.contradiction_evidence_ids == ["E03"]
    # The clean twin is unaffected: still merged, still at its normal
    # (non-low) confidence, still carrying no contradiction.
    assert any(c.novelty == "open_world" for c in clean)
    assert all(c.contradiction_evidence_ids == [] for c in clean if c.novelty == "open_world")
    assert all(c.confidence != "low" for c in clean if c.novelty == "open_world")


def test_gate_fires_correctly_if_a_confident_contradicted_candidate_ever_reaches_it() -> None:
    """harness.py's downstream half of the wiring is sound and ready: given a
    ``top`` whose ``contradiction_evidence_ids`` is non-empty -- WITHOUT an
    explicit ``evidence_links=`` kwarg, exercising the
    ``top.contradiction_evidence_ids`` branch the real pipeline uses -- the
    gate correctly fires. This half of the wiring never needed a fix; the
    two tests above document the upstream producers that now deliver a
    contradicted candidate here instead of discarding it first."""
    results = [_result("loki"), _result("system", "NVIDIA XID errors were absent")]
    results[0].artifacts[0].result = {"observation": _scoped_observation()}
    results[1].artifacts[0].result = {
        "observation": {
            **_scoped_observation("absent"),
            "predicate": "node_log:nvidia_xid_errors",
        }
    }
    assign_evidence_ids(results)
    response = _response("## Root Cause\n\nLikely Xid [E01] despite the counter-signal [E02].")
    top = RankedCause(
        "gpu_hardware_error",
        "high",
        9.0,
        support_evidence_ids=["E01"],
        contradiction_evidence_ids=["E02"],
    )

    verdict = evaluate(response, results, [top])

    assert verdict.claims[0]["contradicting_evidence"] == ["E02"]
    assert verdict.gates["unresolved_contradiction"] is True
