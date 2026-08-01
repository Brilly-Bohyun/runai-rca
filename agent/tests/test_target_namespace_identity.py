"""The plan may widen WHERE we read; it may not move the target's identity."""

from dataclasses import replace

from app.collectors.base import AnalysisTarget
from app.collectors.kubernetes import _scope_target
from app.plan import InvestigationPlan
from app.progress import ProgressReporter
from app.schemas import Alert, AlertAnalysisRequest
from app.services import pipeline
from tests.test_orchestrator import make_settings, make_target


def _state(target: AnalysisTarget, plan: InvestigationPlan) -> pipeline.PipelineState:
    return pipeline.PipelineState(
        settings=make_settings(),
        request=AlertAnalysisRequest(
            alert=Alert(status="firing", labels={}, annotations={}, startsAt=target.fired_at)
        ),
        target=target,
        progress=ProgressReporter(make_settings(), run_id=""),
        masker=None,
        collectors=[],
        plan=plan,
    )


def test_component_namespace_never_replaces_the_alert_namespace() -> None:
    """INC-…-000001: the planner LLM named runai-scheduler-default, which put the
    component's home namespace first; the target then moved to `runai` and every
    runai-test1 observation failed eligibility as "conflicts with target entity scope"."""
    target = replace(make_target(), namespace="runai-test1", pod="frac-test2-0-0")
    plan = InvestigationPlan(
        pod="frac-test2-0-0",
        workload="runai-scheduler-default",
        component="runai-scheduler-default",
        namespaces=["runai", "runai-test1", "runai-backend"],
    )

    effective = pipeline._apply_effective_target(_state(target, plan))

    assert effective.namespace == "runai-test1"
    # The plan still gets to widen the read scope.
    assert plan.namespaces == ["runai", "runai-test1", "runai-backend"]


def test_plan_still_supplies_a_namespace_when_the_alert_has_none() -> None:
    """Operator chat requests carry no labels; the component's namespace is the
    only identity they have, and must keep being adopted."""
    target = replace(make_target(), namespace="", pod="", workload_name="")
    plan = InvestigationPlan(workload="thanos-receive", namespaces=["monitoring"])

    assert pipeline._apply_effective_target(_state(target, plan)).namespace == "monitoring"


def test_live_pod_and_node_resolution_still_applies() -> None:
    """The reason the scoped target is persisted at all: a stale alert Pod."""
    target = replace(make_target(), namespace="runai-test1", pod="trainer-dead", node="")
    plan = InvestigationPlan(pod="trainer-live", node="dgx01", namespaces=["runai-test1"])

    effective = pipeline._apply_effective_target(_state(target, plan))

    assert (effective.pod, effective.node) == ("trainer-live", "dgx01")


def test_per_probe_scoping_can_still_narrow_to_another_namespace() -> None:
    """`_scope_target` is also the per-probe scoper: an LLM probe that asks for
    namespace `runai` must still reach it."""
    target = replace(make_target(), namespace="runai-test1", pod="frac-test2-0-0")

    scoped = _scope_target(target, InvestigationPlan(namespaces=["runai"]))

    assert scoped.namespace == "runai"
