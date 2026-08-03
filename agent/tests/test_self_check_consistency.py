"""Regression tests for self_check.py's signature-vs-ranker refutation contract.

1. OWNER DECISION (2026-07-31): "no eligible evidence" refutes a root-cause
   family ONLY when it was promoted by a DISPOSITIVE signature (NVIDIA XID /
   a typed, machine-reported Kubernetes state) -- a specific, verified claim
   with nothing behind it. Everything else with no eligible evidence --
   a RANKER-derived family, or one promoted only by a curated known-issue /
   curated symptom KEYWORD hit against the alert's own free-form prose -- is
   merely unconfirmed (absence of evidence is not evidence of absence):
   confidence drops one level, but it is not refuted. This replaces the old
   pinned divergence, where the deterministic paths only downgraded and the
   LLM path force-refuted on ANY missing evidence regardless of provenance.

   Two things this is NOT (both verified against the current test suite, not
   just this decision's prose):
   - "any signature-promotion kind refutes" -- treating known-issue/curated-
     symptom keyword hits as refutable-on-missing-evidence broke ~14 scenarios
     in tests/test_troubleshooting_scenarios.py (e.g. admission-webhook x509
     -> k8s_control_plane_error), which never simulate real collector
     evidence and rely on exactly this leniency for a plain keyword match.
   - "ranker-derived never refutes on a present LLM verdict" -- a standalone/
     legacy caller that passes no evidence_eligibility map (tests/
     test_self_check.py's `_top()` scenarios) keeps has_evidence as an
     unconditional upper bound on the model's verdict, same as before; the
     new leniency is scoped to callers with a real eligibility map, since
     only those have a rigorous "no eligible evidence" signal to act on.

   A scoped contradiction still refutes either way, unchanged.
2. The module must log a WARNING on its two silent-failure paths (blanket
   exception handler; LLM returned nothing) per the project's
   warning-only-on-failure logging convention.
3. The "no evidence" operator caveat must not claim the canonical collector
   specifically was consulted and came back empty when it never ran at all.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from app.collectors.base import CollectorResult
from app.schemas import AlertAnalysisArtifact
from app.services.root_cause_ranking import RankedCause
from app.services.self_check import refute_top_cause
from tests.test_orchestrator import make_settings


def _run(coro):
    return asyncio.run(coro)


def _top(family="node_kubelet_pressure", confidence="medium"):
    # canonical collector for node_kubelet_pressure is "kubernetes"; ranker-
    # derived (no score_breakdown "signature" stage) -- NOT signature-promoted.
    return RankedCause(
        family=family,
        confidence=confidence,
        score=6.0,
        rationale=["kubernetes evidence matched diskpressure"],
        evidence_agents=["kubernetes", "prometheus"],
    )


def _signature_top(family="gpu_hardware_error", confidence="medium"):
    # Mirrors pipeline._promote_xid_cause's fresh-candidate construction: a
    # DISPOSITIVE signature (kind="nvidia_xid") -- see _is_signature_promoted.
    rationale = "NVIDIA XID 79 present in the alert/evidence"
    return RankedCause(
        family=family,
        confidence=confidence,
        score=10.0,
        rationale=[rationale],
        evidence_agents=["alert"],
        score_breakdown=[
            {
                "stage": "signature",
                "kind": "nvidia_xid",
                "label": rationale,
                "score_floor": 10.0,
                "force_high": True,
            }
        ],
    )


def _llm_settings():
    return replace(make_settings(), llm_model_self_check="m")


def test_ranker_derived_missing_evidence_downgrades_but_never_refutes(monkeypatch):
    """A ranker-derived family (no signature stage) with no eligible evidence
    is UNCONFIRMED, not REFUTED, on every self-check path: confidence drops
    one level and `refuted` stays False.
    """
    results = [
        CollectorResult(
            agent="kubernetes",
            status="ok",
            summary="DiskPressure=True",
            artifacts=[
                AlertAnalysisArtifact(
                    evidence_id="E01",
                    agent="kubernetes",
                    source="kubernetes",
                    type="node_condition",
                    status="ok",
                    summary="DiskPressure active during incident window",
                    result={
                        "observation": {"polarity": "present", "coverage": "scoped"}
                    },
                )
            ],
        )
    ]
    top = _top()

    out_no_llm = _run(
        refute_top_cause(make_settings(), top, results, evidence_eligibility={})
    )
    assert out_no_llm["refuted"] is False, out_no_llm
    assert out_no_llm["confidence"] == "low", out_no_llm  # downgraded one level

    settings_llm = _llm_settings()
    monkeypatch.setattr("app.services.self_check.llm_configured", lambda *_a, **_k: True)

    async def fake_none(*_a, **_k):
        return None

    monkeypatch.setattr("app.services.self_check.complete_json", fake_none)
    out_llm_none = _run(
        refute_top_cause(settings_llm, top, results, evidence_eligibility={})
    )
    assert out_llm_none["refuted"] is False, out_llm_none
    assert out_llm_none["confidence"] == "low", out_llm_none

    async def fake_supported(*_a, **_k):
        return {"supported": True, "confidence": "medium", "caveat": "", "next_check": ""}

    monkeypatch.setattr("app.services.self_check.complete_json", fake_supported)
    out_llm_verdict = _run(
        refute_top_cause(settings_llm, top, results, evidence_eligibility={})
    )
    assert out_llm_verdict["refuted"] is False, out_llm_verdict  # was the pinned divergence
    assert out_llm_verdict["confidence"] == "low", out_llm_verdict


def test_signature_promoted_missing_evidence_is_refuted_on_all_three_paths(monkeypatch):
    """A signature-promoted family makes a specific claim ("this exact
    mechanism happened"); no eligible evidence for it means there was never
    anything behind that claim, so it IS refuted -- on every self-check path,
    even when the model itself claims "supported": true.
    """
    top = _signature_top(confidence="high")
    results: list[CollectorResult] = []  # nothing eligible anywhere

    out_no_llm = _run(
        refute_top_cause(make_settings(), top, results, evidence_eligibility={})
    )
    assert out_no_llm["refuted"] is True, out_no_llm
    assert out_no_llm["confidence"] == "medium", out_no_llm  # still one level down

    settings_llm = _llm_settings()
    monkeypatch.setattr("app.services.self_check.llm_configured", lambda *_a, **_k: True)

    async def fake_none(*_a, **_k):
        return None

    monkeypatch.setattr("app.services.self_check.complete_json", fake_none)
    out_llm_none = _run(
        refute_top_cause(settings_llm, top, results, evidence_eligibility={})
    )
    assert out_llm_none["refuted"] is True, out_llm_none
    assert out_llm_none["confidence"] == "medium", out_llm_none

    async def fake_supported(*_a, **_k):
        return {"supported": True, "confidence": "high", "caveat": "", "next_check": ""}

    monkeypatch.setattr("app.services.self_check.complete_json", fake_supported)
    out_llm_verdict = _run(
        refute_top_cause(settings_llm, top, results, evidence_eligibility={})
    )
    assert out_llm_verdict["refuted"] is True, out_llm_verdict  # model cannot override
    assert out_llm_verdict["confidence"] == "medium", out_llm_verdict


def test_curated_symptom_keyword_hit_does_not_force_refutation(monkeypatch):
    """A curated-symptom/known-issue KEYWORD match is not a DISPOSITIVE
    signature: it is a heuristic hint against the alert's own free-form
    prose, not a verified fact. With no eligible evidence it must be treated
    like a ranker-derived family (downgrade only), not force-refuted.

    This is the one that bites: naively treating every score_breakdown
    "signature" stage as refutable-on-missing-evidence breaks ~14 real
    scenarios in tests/test_troubleshooting_scenarios.py (e.g. admission-
    webhook x509 -> k8s_control_plane_error), which are exactly this shape --
    a curated-symptom match with no simulated collector evidence.
    """
    rationale = "matched curated symptom: Admission Webhook Timeout / Unreachable"
    top = RankedCause(
        family="k8s_control_plane_error",
        confidence="high",
        score=7.0,
        rationale=[rationale],
        evidence_agents=["signature"],
        score_breakdown=[
            {
                "stage": "signature",
                "kind": "curated_symptom",
                "label": rationale,
                "score_floor": 7.0,
            }
        ],
    )
    results: list[CollectorResult] = []  # nothing eligible anywhere

    out_no_llm = _run(
        refute_top_cause(make_settings(), top, results, evidence_eligibility={})
    )
    assert out_no_llm["refuted"] is False, out_no_llm
    assert out_no_llm["confidence"] == "medium", out_no_llm

    settings_llm = _llm_settings()
    monkeypatch.setattr("app.services.self_check.llm_configured", lambda *_a, **_k: True)

    async def fake_supported(*_a, **_k):
        return {"supported": True, "confidence": "medium", "caveat": "", "next_check": ""}

    monkeypatch.setattr("app.services.self_check.complete_json", fake_supported)
    out_llm_verdict = _run(
        refute_top_cause(settings_llm, top, results, evidence_eligibility={})
    )
    assert out_llm_verdict["refuted"] is False, out_llm_verdict
    assert out_llm_verdict["confidence"] == "medium", out_llm_verdict


def test_contradiction_still_refutes_ranker_derived_candidate(monkeypatch):
    """A direct scoped contradiction refutes a candidate regardless of
    signature-vs-ranker provenance -- unchanged by the missing-evidence
    conditional above."""
    results = [
        CollectorResult(
            agent="kubernetes",
            status="ok",
            summary="DiskPressure=False",
            artifacts=[
                AlertAnalysisArtifact(
                    evidence_id="E02",
                    agent="kubernetes",
                    source="kubernetes",
                    type="node_condition",
                    status="ok",
                    summary="DiskPressure not active during incident window",
                    result={
                        "observation": {"polarity": "absent", "coverage": "scoped"}
                    },
                )
            ],
        )
    ]
    top = _top()  # ranker-derived, not signature-promoted

    out_no_llm = _run(refute_top_cause(make_settings(), top, results))
    assert out_no_llm["refuted"] is True, out_no_llm

    settings_llm = _llm_settings()
    monkeypatch.setattr("app.services.self_check.llm_configured", lambda *_a, **_k: True)

    async def fake_supported(*_a, **_k):
        return {"supported": True, "confidence": "medium", "caveat": "", "next_check": ""}

    monkeypatch.setattr("app.services.self_check.complete_json", fake_supported)
    out_llm = _run(refute_top_cause(settings_llm, top, results))
    assert out_llm["refuted"] is True, out_llm


def test_exception_path_emits_warning(caplog):
    """DEFECT 2: the blanket `except Exception` must not fail silently."""

    class Broken:
        confidence = "high"
        family = "node_kubelet_pressure"

        @property
        def rationale(self):  # pragma: no cover - defensive
            raise RuntimeError("boom")

    with caplog.at_level(logging.WARNING, logger="app.services.self_check"):
        out = _run(refute_top_cause(make_settings(), Broken(), []))

    assert out["confidence"] == "high"  # safe default still preserved
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("self-check failed" in r.getMessage() for r in warnings), caplog.text


def test_llm_returns_none_emits_warning(monkeypatch, caplog):
    """DEFECT 2: an empty/None LLM verdict must not fail silently either."""
    settings = replace(make_settings(), llm_model_self_check="m")

    async def fake_complete_json(*_a, **_k):
        return None

    monkeypatch.setattr("app.services.self_check.llm_configured", lambda *_a, **_k: True)
    monkeypatch.setattr("app.services.self_check.complete_json", fake_complete_json)
    results = [CollectorResult(agent="kubernetes", status="unavailable", summary="")]

    with caplog.at_level(logging.WARNING, logger="app.services.self_check"):
        out = _run(refute_top_cause(settings, _top(confidence="high"), results))

    assert out["confidence"] == "medium"  # deterministic-gate fallback still applies
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("no verdict" in r.getMessage() for r in warnings), caplog.text


def test_caveat_does_not_claim_canonical_source_was_the_gap_when_it_never_ran():
    """DEFECT 3: kubernetes is node_kubelet_pressure's canonical collector, but it
    never ran here -- only prometheus did, and found nothing eligible. The
    caveat must not claim kubernetes specifically was checked and came back
    empty; it may honestly say no collector had usable evidence.
    """
    results = [
        CollectorResult(agent="prometheus", status="ok", summary="node metrics nominal"),
    ]

    out = _run(refute_top_cause(make_settings(), _top(confidence="high"), results))

    assert out["confidence"] == "medium"
    caveat = out["caveat"]
    assert "canonical evidence source (kubernetes)" not in caveat, caveat
    assert "returned no usable evidence" not in caveat, caveat
    assert "no collector returned usable scoped evidence" in caveat, caveat
