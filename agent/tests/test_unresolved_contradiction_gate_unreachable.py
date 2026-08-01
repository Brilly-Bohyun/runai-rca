"""G4: harness.py's ``unresolved_contradiction`` hard gate is correctly wired
but provably cannot fire in the live pipeline today.

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
the real pipeline it is exclusively the second path. This file pins the two
independent reasons that path can never deliver a contradicted candidate as
``top``:

1. ``root_cause_ranking._confidence`` forces confidence to "low" the instant
   a candidate has ANY ``contradiction_evidence_ids``, and ``live_ranked``
   (inside ``rank_root_cause_candidates``) requires medium/high -- so a
   contradicted candidate can never be ``candidates[0]`` with a real family.
2. ``merge_open_world_candidates`` ``continue``-skips any open-world ledger
   entry that has a non-empty contradiction list *before* constructing the
   ``RankedCause`` for it, so ``RankedCause(..., contradiction_evidence_ids=
   contradict)`` there is only ever reached with ``contradict == []``.

Plus one more test proving harness.py's OWN consumption of
``top.contradiction_evidence_ids`` (no explicit ``evidence_links=`` kwarg) is
correctly wired and ready -- confirming the dead end is entirely upstream,
not a harness.py bug worth "fixing" by inventing new gate logic here.
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


def test_confidence_forces_low_whenever_a_candidate_has_a_contradiction_so_live_ranked_excludes_it() -> None:
    """Same score/agents/groups that would otherwise clear HIGH; only the
    presence of a contradiction id differs."""
    winning_inputs = dict(
        points=100.0,
        force_high=True,
        agents={"loki", "kubernetes"},
        support_source_groups={"loki", "kubernetes_api"},
    )
    clean = _Score(**winning_inputs)
    contradicted = _Score(**winning_inputs, contradiction_evidence_ids={"E02"})

    assert _confidence("gpu_hardware_error", clean, {}) == "high"
    # This is the reason live_ranked (confidence in {"medium", "high"}) can
    # never include a contradicted candidate: the ranker forces it to "low"
    # for exactly the same evidence that would otherwise have been "high".
    assert _confidence("gpu_hardware_error", contradicted, {}) == "low"


def test_merge_open_world_candidates_drops_any_ledger_entry_that_has_a_contradiction() -> None:
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

    # The candidate is dropped entirely, not merely stripped of its
    # contradiction -- proving the ``continue`` guard, not a later filter.
    assert contradicted == known
    assert any(c.novelty == "open_world" for c in clean)
    assert all(c.contradiction_evidence_ids == [] for c in clean if c.novelty == "open_world")


def test_gate_fires_correctly_if_a_confident_contradicted_candidate_ever_reaches_it() -> None:
    """harness.py's downstream half of the wiring is sound and ready: given a
    ``top`` whose ``contradiction_evidence_ids`` is non-empty -- WITHOUT an
    explicit ``evidence_links=`` kwarg, exercising the
    ``top.contradiction_evidence_ids`` branch the real pipeline would use --
    the gate correctly fires. The two tests above are what make this
    unreachable via the real ranker, not any defect here."""
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
