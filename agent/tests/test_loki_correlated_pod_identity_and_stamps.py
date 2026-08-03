"""C8 + C9 regression coverage for loki.py.

C8a: ``workload_history_logs`` / ``runai_control_plane_for_workload`` required
``target.runai_workload_id`` to ever become target-scoped support. A
Kubernetes-origin alert (KubePodNotReady etc.) never carries that field, so
these two queries were permanently decorative for it even though rows kept
coming back (measured on a real run: 20 lines / 10-11 affirmative, killed by
``target_scope_verified: False``). The resolved Pod name is now an accepted
fallback identifier -- bounded the same way the workload ID already is, so a
workload-NAME-only match (kept context-only elsewhere in this module) still
cannot pass.

C8b: an unrecognized query name silently returned unscoped forever with no
diagnostic trail. It must now log a warning.

C9: only kubernetes.py ever stamped ``target_identity_verified``, so
``investigator._attach_typed_artifacts`` could never auto-attach a genuinely
scoped Loki artifact. loki.py must now mirror ``target_scope_verified`` into
``target_identity_verified`` whenever it actually ran the check.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from types import SimpleNamespace

from app.collectors import loki
from tests.test_orchestrator import make_target

_TIME_RANGE = {"start": "2026-07-31T04:25:37Z", "end": "2026-07-31T04:50:37Z"}
_POD = "frac-test2-0-0"


def _k8s_origin_target(**kwargs) -> object:
    """A KubePodNotReady-style alert: namespace/pod identity, no Run:ai ID."""
    fields = {
        "runai_workload_id": "",
        "namespace": "runai-test1",
        "pod": _POD,
        "workload_name": "frac-test2",
        **kwargs,
    }
    return replace(make_target(), **fields)


def _entry(line: str, *, namespace: str) -> dict:
    return {
        "timestamp": "2026-07-31T04:34:35Z",
        "line": line,
        "labels": {"namespace": namespace, "pod": "runai-scheduler-default-0"},
    }


def test_workload_history_promotes_a_row_that_names_the_target_pod() -> None:
    """Body text carrying the exact target Pod name is strong enough proof."""
    target = _k8s_origin_target()
    observation = loki._loki_query_observation(
        {
            "name": "workload_history_logs",
            "query": loki._workload_history_query(target),
            "transport": "mcp",
            "line_count": 1,
            "stream_count": 1,
            "sample_entries": [
                _entry(f"preempted pod {_POD} for over-quota project", namespace="runai-test1")
            ],
        },
        target=target,
        time_range=_TIME_RANGE,
    )

    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["target_scope_verified"] is True
    assert observation["target_identity_verified"] is True
    assert observation["observed_entity"] == {"kind": "pod", "name": _POD}


def test_control_plane_correlation_promotes_a_row_naming_the_target_pod() -> None:
    """Same fallback for the control-plane (different-namespace) correlation."""
    target = _k8s_origin_target()
    selector = loki._namespace_regex_selector(("runai", "runai-backend"))
    observation = loki._loki_query_observation(
        {
            "name": "runai_control_plane_for_workload",
            "query": f"{selector} |~ \"(?i)(frac-test2)\"",
            "transport": "mcp",
            "line_count": 1,
            "stream_count": 1,
            "sample_entries": [
                _entry(f"unschedulable pod {_POD}: insufficient nvidia.com/gpu", namespace="runai")
            ],
        },
        target=target,
        time_range=_TIME_RANGE,
    )

    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["target_scope_verified"] is True
    assert observation["target_identity_verified"] is True
    assert observation["observed_entity"] == {"kind": "pod", "name": _POD}


def test_row_without_the_pod_token_stays_unscoped() -> None:
    """No over-opening: a correlated hit that never names the Pod stays context.

    This is the real-run shape (E103/E105): scheduler preempt/gang-eviction
    lines that talk about the workload only by internal request ID, never by
    the alert's own Pod name.
    """
    target = _k8s_origin_target()
    observation = loki._loki_query_observation(
        {
            "name": "workload_history_logs",
            "query": loki._workload_history_query(target),
            "transport": "mcp",
            "line_count": 1,
            "stream_count": 1,
            "sample_entries": [
                _entry(
                    "[c602fbf6-ad70-4d23-abe0-8bead89149e1] preempt: end scheduling cycle",
                    namespace="runai-test1",
                )
            ],
        },
        target=target,
        time_range=_TIME_RANGE,
    )

    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert observation["target_scope_verified"] is False
    assert observation["target_identity_verified"] is False


def test_workload_name_alone_still_cannot_satisfy_the_fallback() -> None:
    """The pod fallback must not quietly relax back to the rejected name-match."""
    target = _k8s_origin_target()
    observation = loki._loki_query_observation(
        {
            "name": "workload_history_logs",
            "query": loki._workload_history_query(target),
            "transport": "mcp",
            "line_count": 1,
            "stream_count": 1,
            "sample_entries": [
                _entry("workload frac-test2 failed scheduling", namespace="runai-test1")
            ],
        },
        target=target,
        time_range=_TIME_RANGE,
    )

    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert observation["target_scope_verified"] is False


def test_workload_id_is_still_preferred_over_pod_when_both_are_present() -> None:
    """A Run:ai-origin alert must keep using the stronger immutable ID, not Pod."""
    workload_id = "550e8400-e29b-41d4-a716-446655440000"
    target = replace(_k8s_origin_target(), runai_workload_id=workload_id)
    observation = loki._loki_query_observation(
        {
            "name": "workload_history_logs",
            "query": loki._workload_history_query(target),
            "transport": "mcp",
            "line_count": 1,
            "stream_count": 1,
            "sample_entries": [
                _entry(f"workload {workload_id} failed scheduling", namespace="runai-test1")
            ],
        },
        target=target,
        time_range=_TIME_RANGE,
    )

    assert observation["observed_entity"] == {"kind": "runai_workload_id", "name": workload_id}


def test_no_pod_and_no_workload_id_leaves_the_query_unscoped() -> None:
    target = _k8s_origin_target(pod="", runai_workload_id="")
    observation = loki._loki_query_observation(
        {
            "name": "workload_history_logs",
            "query": loki._workload_history_query(target),
            "transport": "mcp",
            "line_count": 1,
            "stream_count": 1,
            "sample_entries": [
                _entry("workload frac-test2 failed scheduling", namespace="runai-test1")
            ],
        },
        target=target,
        time_range=_TIME_RANGE,
    )

    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")


def test_too_short_a_pod_name_does_not_open_the_fallback() -> None:
    """A 1-2 char Pod name is not a safe body-text token; guard like elsewhere."""
    target = _k8s_origin_target(pod="ab", runai_workload_id="")
    entity, scoped = loki._loki_correlated_target_scope(
        "workload_history_logs",
        {
            "query": loki._workload_history_query(replace(target, pod="ab")),
            "sample_entries": [_entry("pod ab restarted", namespace="runai-test1")],
        },
        target=target,
        plan=None,
        time_range=_TIME_RANGE,
    )

    assert (entity, scoped) == (None, False)


def test_plan_pod_override_is_used_ahead_of_the_stale_target_pod() -> None:
    """Mirrors the primary branch: a fresher plan.pod wins over target.pod."""
    target = _k8s_origin_target(pod="old-replaced-pod")
    plan = SimpleNamespace(pod="frac-test2-0-1")
    entity, scoped = loki._loki_correlated_target_scope(
        "workload_history_logs",
        {
            "query": loki._workload_history_query(target),
            "sample_entries": [
                _entry("preempted pod frac-test2-0-1 on node dgx01", namespace="runai-test1")
            ],
        },
        target=target,
        plan=plan,
        time_range=_TIME_RANGE,
    )

    assert scoped is True
    assert entity == {"kind": "pod", "name": "frac-test2-0-1"}


def test_target_identity_verified_mirrors_target_scope_verified_for_primary_queries() -> None:
    """C9 also covers the primary (non-correlated) error_logs/recent_logs path."""
    target = replace(make_target(), pod="trainer-0", namespace="runai-vision")
    observation = loki._loki_query_observation(
        {
            "name": "error_logs",
            "line_count": 1,
            "stream_count": 1,
            "sample_entries": [
                {
                    "timestamp": "2026-07-10T01:00:00Z",
                    "line": "OOMKilled",
                    "labels": {"namespace": "runai-vision", "pod": "trainer-0"},
                }
            ],
        },
        target=target,
        time_range={"start": "2026-07-10T00:55:00Z", "end": "2026-07-10T01:15:00Z"},
    )

    assert observation["target_scope_verified"] is True
    assert observation["target_identity_verified"] is True


def test_unrecognized_query_name_logs_a_warning_instead_of_failing_silently(
    caplog,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.collectors.loki"):
        entity, scoped = loki._loki_target_scope(
            "some_future_query_nobody_wired_up",
            {"sample_entries": []},
            target=make_target(),
            plan=None,
            time_range=_TIME_RANGE,
        )

    assert (entity, scoped) == (None, False)
    assert any(
        "some_future_query_nobody_wired_up" in record.getMessage()
        for record in caplog.records
    )
