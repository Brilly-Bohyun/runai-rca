"""planner._diagnostic_directive surfaces kg_enrichment.KGContext.probe_history
(prior trace-v3 probe-execution verdicts, family -> template_id -> {verdict:
count, ..., "total": N}) onto the matching probe, so a template that has
repeatedly come back inconclusive for this family is visibly less attractive
to the investigator LLM than an untried one."""

from __future__ import annotations

import pytest

from app.collectors.base import AnalysisTarget
from app.schemas import Alert
from app.services.planner import plan_investigation
from tests.test_orchestrator import make_settings


def _target(**overrides) -> AnalysisTarget:
    base = dict(
        cluster="",
        project="",
        queue="",
        namespace="",
        workload_name="",
        workload_type="",
        runai_workload_id="",
        node="",
        pod="",
        severity="warning",
        alert_name="RunAIAlert",
    )
    base.update(overrides)
    return AnalysisTarget(**base)


# "always": True keeps the walk independent of alert text -- only the family
# and the probe's template_id matter for this test.
_TREE = {
    "root": "scope",
    "nodes": {
        "scope": {
            "id": "scope",
            "question": "Scope the incident.",
            "match": {"always": True},
            "conclusion": {"family": "gpu_hardware_error"},
            "probes": [
                {
                    "id": "history-probe",
                    "tool": "k8s_read",
                    "arguments_template": {"kind": "events", "namespace": "{{namespace}}"},
                }
            ],
        }
    },
}


@pytest.mark.asyncio
async def test_probe_history_summary_is_attached_to_the_matching_probe() -> None:
    kg = {
        "diagnostic_tree": _TREE,
        "probe_history": {
            "gpu_hardware_error": {"history-probe": {"total": 4, "inconclusive": 4}}
        },
    }
    plan = await plan_investigation(
        make_settings(), _target(alert_name="NvidiaXidCriticalError"), Alert(), kg, []
    )
    probe = plan.diagnostic_directive["probes"][0]
    assert probe["template_id"] == "history-probe"
    assert probe["prior_verdict_summary"] == {"total": 4, "inconclusive": 4}


@pytest.mark.asyncio
async def test_no_probe_history_leaves_the_probe_without_the_key() -> None:
    kg = {"diagnostic_tree": _TREE}  # kg_enrichment disabled/unavailable: no probe_history at all
    plan = await plan_investigation(
        make_settings(), _target(alert_name="NvidiaXidCriticalError"), Alert(), kg, []
    )
    probe = plan.diagnostic_directive["probes"][0]
    assert "prior_verdict_summary" not in probe


@pytest.mark.asyncio
async def test_probe_history_for_a_different_family_does_not_attach() -> None:
    kg = {
        "diagnostic_tree": _TREE,
        "probe_history": {"some_other_family": {"history-probe": {"total": 9}}},
    }
    plan = await plan_investigation(
        make_settings(), _target(alert_name="NvidiaXidCriticalError"), Alert(), kg, []
    )
    probe = plan.diagnostic_directive["probes"][0]
    assert "prior_verdict_summary" not in probe
