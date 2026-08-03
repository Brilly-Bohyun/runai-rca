"""Regression tests for the four confirmed investigator probe/query feedback
defects (production run: 400/605s produced zero new evidence because dropped
probes and rejected queries never told the model what went wrong).

1. A probe naming a TOOL instead of a COLLECTOR was silently dropped.
2. The ad-hoc query rejection hint referenced adhoc_query_kinds without
   inlining it, so the model corrected spelling instead of vocabulary.
3. A rejected query never entered `seen_queries`, so it could be resubmitted
   forever.
4. `_reflect_hypotheses` could add an untestable hypothesis that then burned
   every later verification round.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest

from app.plan import InvestigationPlan
from app.services.investigator import _READ_KINDS, _rejected_adhoc_query_feedback, investigate
from tests.test_investigator import KubernetesCollector, RunaiCollector
from tests.test_orchestrator import make_settings, make_target


@pytest.mark.asyncio
async def test_probe_naming_a_tool_is_accepted_and_unknown_collector_gets_feedback(
    monkeypatch, caplog
) -> None:
    """Defect 1. Confirmed production failure: two re-analysis rounds named
    only the TOOL "k8s_read"/"k8s_describe" in probes[].collector (which
    expects a COLLECTOR name), so the probe was dropped with no query_feedback,
    no progress event, and no warning -- 191.6s of one run produced nothing.
    """
    settings = replace(
        make_settings(), llm_base_url="https://llm.example/v1", llm_model="m", llm_api_key="k"
    )
    kubernetes = KubernetesCollector()
    runai = RunaiCollector()
    prompts: list[str] = []
    decisions = iter(
        [
            # Exactly the confirmed production input: a TOOL name, not a collector.
            {"action": "probe", "probes": [{"collector": "k8s_read", "scope": {}}]},
            {"action": "probe", "probes": [{"collector": "not_a_real_thing"}]},
            {"action": "conclude"},
        ]
    )

    async def fake_complete_json(_settings, *, system, user, **_kwargs):
        if "final skeptical reflection" in system:
            return {"hypothesis_updates": [], "new_hypotheses": []}
        prompts.append(user)
        return next(decisions)

    monkeypatch.setattr("app.services.investigator.complete_json", fake_complete_json)
    caplog.set_level(logging.WARNING, logger="app.services.investigator")

    await investigate(
        settings, make_target(), [kubernetes, runai], InvestigationPlan(), {}, max_steps=3
    )

    # Accepted: the tool-name alias resolved to the real "kubernetes"
    # collector and it actually ran -- not silently dropped.
    assert kubernetes.calls == 1
    # Rejected-but-not-silent: an unresolvable value produced feedback that
    # reached a later prompt, naming the real collector vocabulary.
    assert len(prompts) == 3
    assert "not_a_real_thing" in prompts[-1]
    assert "Use one of: kubernetes, runai" in prompts[-1]
    # A WARNING was emitted for the anomaly (project rule: no happy-path
    # logs, WARNING on failure/anomaly).
    assert any("not_a_real_thing" in record.getMessage() for record in caplog.records)


def test_rejected_adhoc_query_feedback_inlines_allowed_kinds() -> None:
    """Defect 2. The correction hint said "Use one of adhoc_query_kinds" but
    never inlined the list, so a model retried "RoleBinding" then
    "rolebindings" -- it corrected the SPELLING, not the VOCABULARY, because
    the allowlist lived only at the top of a 3k+ token prompt.
    """
    feedback = _rejected_adhoc_query_feedback({"kind": "RoleBinding"})
    hint = feedback["failure"]["correction_hint"]

    for kind in sorted(_READ_KINDS):
        assert kind in hint, f"{kind!r} missing from inlined correction hint: {hint!r}"


@pytest.mark.asyncio
async def test_rejected_query_is_remembered_and_a_case_variant_is_not_new_work(
    monkeypatch,
) -> None:
    """Defect 3. A rejected query never reached `_adhoc_query_fingerprint`, so
    it never entered `seen_queries` -- only the trimmed `query_feedback[-8:]`
    remembered it. A same/case-variant resubmission must now be recognised as
    already-answered instead of buying another bounded round.
    """
    settings = replace(
        make_settings(), llm_base_url="https://llm.example/v1", llm_model="m", llm_api_key="k"
    )
    prompts: list[str] = []
    decisions = iter(
        [
            {"action": "probe", "queries": [{"kind": "RoleBinding", "namespace": "runai"}]},
            # Same invalid kind, different case -- must fingerprint identically.
            {"action": "probe", "queries": [{"kind": "rolebinding", "namespace": "runai"}]},
            {"action": "conclude"},
        ]
    )

    async def fake_complete_json(_settings, *, system, user, **_kwargs):
        if "final skeptical reflection" in system:
            return {"hypothesis_updates": [], "new_hypotheses": []}
        prompts.append(user)
        return next(decisions)

    monkeypatch.setattr("app.services.investigator.complete_json", fake_complete_json)

    # No collectors: isolates the ad-hoc query path from the probe fallback.
    await investigate(settings, make_target(), [], InvestigationPlan(), {}, max_steps=3)

    # The round-1 rejection is retryable, so round 2 runs and resubmits a
    # case-variant of the SAME invalid kind. Recognising it as already-seen
    # means round 2 produces no new work and the loop stops instead of
    # buying a 3rd round to reject the same request again.
    assert len(prompts) == 2
    assert '"category": "invalid_resource_kind"' in prompts[-1]


@pytest.mark.asyncio
async def test_untestable_new_hypothesis_does_not_consume_a_verification_round(
    monkeypatch,
) -> None:
    """Defect 4. Confirmed production case: reflection added a
    "runai_scheduling_permission" hypothesis whose only discriminator was
    RBAC roles/rolebindings, which are not in `_READ_KINDS` and have no
    owning collector -- every later round chasing it was dead before it
    started. It must still be recorded for the operator, just not chased.
    """
    settings = replace(
        make_settings(), llm_base_url="https://llm.example/v1", llm_model="m", llm_api_key="k"
    )
    verification_calls = 0

    async def fake_complete_json(_settings, *, system, **_kwargs):
        nonlocal verification_calls
        if "final skeptical reflection" in system:
            return {
                "hypothesis_updates": [],
                "new_hypotheses": [
                    {
                        "family": "runai_scheduling_permission",
                        "statement": "the scheduler service account lacks an RBAC binding",
                        "discriminator": "rolebindings",
                    }
                ],
            }
        if "verifying a hypothesis" in system:
            verification_calls += 1
        return {"action": "conclude"}

    monkeypatch.setattr("app.services.investigator.complete_json", fake_complete_json)

    _, context = await investigate(
        settings, make_target(), [], InvestigationPlan(), {}, max_steps=2
    )

    # Not silently dropped -- still on the ledger for the operator.
    ledger = context["hypothesis_ledger"]
    entry = next(
        (item for item in ledger if item.get("family") == "runai_scheduling_permission"), None
    )
    assert entry is not None
    assert entry.get("untestable_reason")
    # Does not consume a probe round: no verification LLM call was spent
    # chasing a hypothesis with no reachable read-only discriminator.
    assert verification_calls == 0
