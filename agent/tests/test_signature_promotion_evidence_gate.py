"""_promote_signature_cause: the specificity/score gates apply to EVERY match,
agreement-with-the-ranker included (S3), and a bare signature must not
leapfrog a stronger evidence-backed candidate (S2).

S7 (alert-sourced promotions are structurally support-less) was attempted in
its broad form -- require ANY catalog-family promotion to be grounded in
non-alert evidence -- and reverted: ``_alert_text`` is a first-class
signature source everywhere in this pipeline (its own docstring: "it often
carries the signature ... even when every collector comes back empty"), and
dozens of existing tests (test_troubleshooting_scenarios.py) depend on an
alert's summary/description alone reaching the correct CATALOG family with
zero collector evidence. Gating that would violate S7's own guardrail ("must
not kill a promotion whose keyword IS in the evidence" -- alert text counts,
by this codebase's definition). What S7 leaves behind here: the PRE-EXISTING
non-catalog evidence gate now also applies in the agreement branch (it used
to be unreachable there, see test_agreement_no_longer_exempts_a_non_catalog_
family_from_its_evidence_gate below) -- a narrow, safe slice of S3's fix.
"""

from __future__ import annotations

from app.services.pipeline import _promote_signature_cause
from app.services.root_cause_ranking import FAMILIES, RankedCause

NON_CATALOG_FAMILY = "unmapped_signature_family"
assert NON_CATALOG_FAMILY not in FAMILIES


# --- S2: a promotion may not displace a stronger evidence-backed candidate ---


def test_signature_does_not_displace_a_stronger_evidence_backed_candidate() -> None:
    """Measured: a 7.0/medium support=[] signature was placed above a
    9.5/high support=['E01','E02'] evidence-backed candidate."""
    strong = RankedCause(
        family="gpu_hardware_error",
        confidence="high",
        score=9.5,
        support_evidence_ids=["E01", "E02"],
    )
    symptom = [(
        "observability_accuracy",
        {"symptom": "False Alarm", "matched_keywords": ["prometheus-operator"]},
    )]

    out = _promote_signature_cause(
        [strong], [], [], symptom, evidence_text="prometheus-operator"
    )

    assert out[0].family == "gpu_hardware_error", (
        "a bare signature must not leapfrog a stronger, evidence-backed ranked cause"
    )


def test_signature_still_wins_when_the_incumbent_has_no_real_support() -> None:
    """Guard against over-correction: the rule is score AND support, not score
    alone -- a merely high-scoring but unsupported incumbent must still lose
    to a real signature (matches test_catalog_promotion_single_specific_keyword_ok)."""
    unsupported = RankedCause(family="workload_startup_error", confidence="high", score=9.0)
    known_issue = [{
        "issue": "Scheduler Reclaim Panic",
        "family": "platform_version_bug",
        "matched_keywords": ["scheduler", "reclaim"],
    }]

    out = _promote_signature_cause(
        [unsupported], [], known_issue, [], evidence_text="scheduler reclaim"
    )

    assert out[0].family == "platform_version_bug"


def test_xid_promotion_is_not_stopped_by_the_displacement_guard() -> None:
    """Guard against over-correction: S2 must not stop a legitimate XID
    promotion from leading, even over a stronger evidence-backed candidate."""
    strong = RankedCause(
        family="node_kubelet_pressure",
        confidence="high",
        score=9.9,
        support_evidence_ids=["E01", "E02"],
    )

    out = _promote_signature_cause([strong], [79], [], [])

    assert out[0].family == "gpu_hardware_error"
    assert out[0].confidence == "high"


def test_typed_state_promotion_is_not_stopped_by_the_displacement_guard() -> None:
    """Guard against over-correction: same for a dispositive typed-state promotion."""
    strong = RankedCause(
        family="node_kubelet_pressure",
        confidence="high",
        score=9.9,
        support_evidence_ids=["E01", "E02"],
    )

    out = _promote_signature_cause(
        [strong], [], [], [], typed_state=("image_pull_error", "typed state", ["E01"])
    )

    assert out[0].family == "image_pull_error"


# --- S3: the specificity gate applies BEFORE the agreement branch ------------


def test_a_non_promotable_match_does_not_floor_the_ranked_score_on_agreement() -> None:
    """(a) A keyword explicitly not promotable must not floor an unearned
    score/confidence even when it names the ranker's own top family."""
    ranked = [RankedCause(family="node_kubelet_pressure", confidence="low", score=3.0)]
    weak = [{
        "issue": "Weak generic hit",
        "family": "node_kubelet_pressure",
        "matched_keywords": ["node"],  # short, single, generic -> not promotable
    }]

    out = _promote_signature_cause(ranked, [], weak, [], evidence_text="node")

    assert out[0].score == 3.0, "a non-promotable match must not floor the score to 8.0"
    assert out[0].confidence == "low", "a non-promotable match must not upgrade low->medium"


def test_a_weak_match_does_not_abort_the_loop_before_a_later_stronger_signature() -> None:
    """(b) Measured: a weak thanos known-issue hit blocked a real
    'uncorrectable ecc error' signature for a different family."""
    ranked = [RankedCause(family="runai_control_plane_error", confidence="medium", score=3.0)]
    matches = [
        {
            "issue": "Weak thanos mention",
            "family": "runai_control_plane_error",  # == top_family, but too weak
            "matched_keywords": ["thanos"],
        },
        {
            "issue": "GPU uncorrectable ECC",
            "family": "gpu_hardware_error",
            "matched_keywords": ["uncorrectable ecc error"],
        },
    ]

    out = _promote_signature_cause(
        ranked, [], matches, [], evidence_text="uncorrectable ecc error"
    )

    assert out[0].family == "gpu_hardware_error", (
        "the weak same-family hit must not return early and hide the later, "
        "stronger signature for a different family"
    )


def test_agreement_no_longer_exempts_a_non_catalog_family_from_its_evidence_gate() -> None:
    """S3+S7 interaction: the OLD code's ``if family == top_family: return`` sat
    BEFORE both the specificity gate and the non-catalog evidence gate, so a
    non-catalog family already in the lead got its score floored on the
    strength of the alert alone. The gate now runs first, agreement included."""
    ranked = [RankedCause(family=NON_CATALOG_FAMILY, confidence="low", score=3.0)]
    two_keywords = [{
        "issue": "Unmapped issue",
        "family": NON_CATALOG_FAMILY,
        "matched_keywords": ["--backoff-limit", "master-restart-policy"],
    }]

    out = _promote_signature_cause(
        ranked, [], two_keywords, [], evidence_text="collector had no matching signature"
    )

    assert out[0].score == 3.0, "ungrounded non-catalog agreement must not floor the score"

    # Guard against over-correction: grounded evidence still promotes normally.
    grounded = _promote_signature_cause(
        ranked,
        [],
        two_keywords,
        [],
        evidence_text="--backoff-limit master-restart-policy",
    )
    assert grounded[0].score == 8.0


def test_catalog_family_agreement_needs_no_evidence_grounding() -> None:
    """Guard against over-correction: a CATALOG family's alert-sourced
    agreement match is unaffected -- alert text is a legitimate signature
    source for the closed, validated family catalog (unlike an unvalidated
    non-catalog label)."""
    ranked = [RankedCause(family="gpu_hardware_error", confidence="low", score=3.0)]
    known_issue = [{
        "issue": "GPU issue",
        "family": "gpu_hardware_error",
        "matched_keywords": ["fallen off the bus"],
    }]

    out = _promote_signature_cause(ranked, [], known_issue, [])

    assert out[0].score == 8.0
    assert out[0].confidence == "medium"
