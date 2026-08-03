"""R3: "the alert target IS this platform component" must not be asserted
when the investigation scope itself already resolved to a USER workload --
the narrative just above it already says "this is a user workload... focus
on the Run:ai scheduler", so asserting platform identity on top of that is a
direct, published self-contradiction. Component identity may still steer
investigation ORDER (it stays the plan's hypothesis lead and ``plan.component``
either way); it must not assert an identity the scope determination refutes.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.collectors.base import AnalysisTarget
from app.schemas import Alert
from app.services.planner import plan_investigation
from tests.test_orchestrator import make_settings


def _target(**overrides) -> AnalysisTarget:
    base = dict(
        cluster="", project="", queue="", namespace="", workload_name="",
        workload_type="", runai_workload_id="", node="", pod="",
        severity="warning", alert_name="KubePodNotReady",
    )
    base.update(overrides)
    return AnalysisTarget(**base)


_TOOLKIT_POD = "runai-container-toolkit-vttmr"


@pytest.mark.asyncio
async def test_component_identity_narrative_is_suppressed_in_workload_scope() -> None:
    target = _target(namespace="runai-test1", pod=_TOOLKIT_POD, workload_name=_TOOLKIT_POD)
    alert = Alert(labels={"alertname": "KubePodNotReady"}, annotations={})

    plan = await plan_investigation(
        make_settings(), target, alert, kg_context=None, similar_incidents=None
    )

    # WHO the alert names is still resolved and still leads the hypotheses --
    # only the false "IS the platform component" narrative claim is dropped.
    assert plan.component == "runai-container-toolkit"
    assert "IS the platform component" not in plan.narrative
    assert "user workload" in plan.narrative


@pytest.mark.asyncio
async def test_component_identity_narrative_still_fires_in_platform_scope() -> None:
    """Guard against over-correction: the identical component match, this
    time genuinely in the platform's own namespace, still asserts identity."""
    target = _target(namespace="runai", pod=_TOOLKIT_POD, workload_name=_TOOLKIT_POD)
    alert = Alert(labels={"alertname": "KubePodNotReady"}, annotations={})

    plan = await plan_investigation(
        make_settings(), target, alert, kg_context=None, similar_incidents=None
    )

    assert plan.component == "runai-container-toolkit"
    assert "IS the platform component 'runai-container-toolkit'" in plan.narrative


@pytest.mark.asyncio
async def test_component_identity_narrative_still_fires_outside_any_namespace_scope() -> None:
    """Guard against over-correction: infra/namespace-less targets (where
    scope is neither 'platform' nor 'workload') are unaffected."""
    target = _target(pod=_TOOLKIT_POD, workload_name=_TOOLKIT_POD, node="dgx-1")
    alert = Alert(labels={"alertname": "KubePodNotReady"}, annotations={})

    plan = await plan_investigation(
        make_settings(), target, alert, kg_context=None, similar_incidents=None
    )

    assert "IS the platform component 'runai-container-toolkit'" in plan.narrative


@pytest.mark.asyncio
async def test_component_identity_narrative_is_localized_to_korean() -> None:
    target = _target(namespace="runai", pod=_TOOLKIT_POD, workload_name=_TOOLKIT_POD)
    alert = Alert(labels={"alertname": "KubePodNotReady"}, annotations={})
    settings = replace(make_settings(), language="ko")

    plan = await plan_investigation(
        settings, target, alert, kg_context=None, similar_incidents=None
    )

    assert "알림 대상은 플랫폼 컴포넌트 'runai-container-toolkit'입니다" in plan.narrative
