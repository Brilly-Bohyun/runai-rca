"""G5: ``response.context["evidence_links"]`` must actually be written.

Before this fix, nothing in agent/, backend/, or frontend/ ever wrote
``response.context["evidence_links"]``. Two things read it: ``analysis_hash``
(harness.py) hashed it as part of the RCA snapshot identity, and
``_supplied_evidence_links`` used it as a last-resort fallback when there was
no ranked ``top`` and no explicit ``evidence_links=`` kwarg. Both reads were
therefore dead: ``analysis_hash`` always hashed a constant ``"evidence_links":
null`` -- defeating its own documented contract that snapshot identity must
change when evidence links change -- and the fallback branch had nothing to
ever return.

``evaluate()`` (harness.py) now writes ``response.context["evidence_links"]``
on every call, from the same claim-link data already surfaced in
``verdict.claims[0]["evidence_links"]``. These tests pin both reads becoming
live.
"""

from __future__ import annotations

from app.services.harness import (
    EvidenceLink,
    _supplied_evidence_links,
    analysis_hash,
    assign_evidence_ids,
    evaluate,
)
from app.services.root_cause_ranking import RankedCause
from tests.test_harness import _response, _result, _scoped_observation


def test_evaluate_writes_the_resolved_claim_links_into_response_context() -> None:
    results = [_result("loki")]
    results[0].artifacts[0].result = {"observation": _scoped_observation()}
    assign_evidence_ids(results)
    response = _response("## Root Cause\n\nLikely cause [E01].")

    verdict = evaluate(
        response,
        results,
        [RankedCause("gpu_hardware_error", "high", 9.0)],
        evidence_links=[EvidenceLink("E01", "support", "the log line")],
    )

    assert response.context["evidence_links"] == verdict.claims[0]["evidence_links"]
    assert response.context["evidence_links"] == [
        {"evidence_id": "E01", "role": "support", "explanation": "the log line"}
    ]


def test_analysis_hash_changes_when_evidence_links_change() -> None:
    """Pins the docstring's own contract: identical prose, different links,
    different hash -- previously impossible because the field was always
    null."""
    results = [_result("loki"), _result("system", "NVIDIA XID errors were absent")]
    results[0].artifacts[0].result = {"observation": _scoped_observation()}
    results[1].artifacts[0].result = {
        "observation": {
            **_scoped_observation("absent"),
            "predicate": "node_log:nvidia_xid_errors",
        }
    }
    assign_evidence_ids(results)
    candidates = [RankedCause("gpu_hardware_error", "high", 9.0)]
    response = _response("## Root Cause\n\nLikely Xid [E01] despite the counter-signal [E02].")

    evaluate(response, results, candidates, evidence_links=[EvidenceLink("E01", "support")])
    hash_support_only = analysis_hash(response)

    evaluate(
        response,
        results,
        candidates,
        evidence_links=[EvidenceLink("E01", "support"), EvidenceLink("E02", "contradict")],
    )
    hash_with_contradiction = analysis_hash(response)

    assert hash_support_only != hash_with_contradiction


def test_supplied_evidence_links_context_fallback_now_has_something_to_read() -> None:
    """Reachable whenever neither an explicit kwarg nor ``top`` itself
    supplies v2 link data -- no ranked top at all, or (as the ranker's own
    compatibility comment notes) a top with empty v2 lists. Exercise it
    directly rather than assembling that whole scenario through evaluate()."""
    response = _response()
    response.context["evidence_links"] = [{"evidence_id": "E01", "role": "support"}]
    empty_top = RankedCause("gpu_hardware_error", "medium", 5.0)

    assert _supplied_evidence_links(response, None, None) == [
        {"evidence_id": "E01", "role": "support"}
    ]
    assert _supplied_evidence_links(response, empty_top, None) == [
        {"evidence_id": "E01", "role": "support"}
    ]


def test_supplied_evidence_links_context_fallback_is_still_not_consulted_when_top_has_real_links() -> None:
    """Precedence is intentional, not a bug: a ranked top's OWN links must
    not be silently replaced by a stale context value from an earlier call."""
    response = _response()
    response.context["evidence_links"] = [{"evidence_id": "E99", "role": "support"}]
    top = RankedCause("gpu_hardware_error", "medium", 5.0, support_evidence_ids=["E01"])

    assert _supplied_evidence_links(response, top, None) == [
        {"evidence_id": "E01", "role": "support"}
    ]
