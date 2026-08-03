"""The drill-down present+scoped gate: who can earn it, and who cannot.

``_typed_artifact_result`` in app.services.drilldown only lets a tool's own
claimed polarity/coverage survive as ``present``/``scoped`` (the only tier that
can substantiate a root cause — see EvidenceEligibility.from_fields in
evidence_blackboard.py) when the tool is marked ``_VERIFIED_OBSERVATION``.
Originally, exactly two tools ever earned that mark (change_query,
system_log_query); k8s_logs became the third (via kubernetes.py's own
``_pod_log_observation``); promql_query/logql_query became the fourth and
fifth (via the base collectors' own ``_prometheus_query_observation``/
``_loki_query_observation``, called with the real target — see the
"drilldown" case each classifier's target-scope function gained). Each of
these proves scope from its OWN RESPONSE, never from the LLM's request, so
this suite also proves every one of them — including the newly-verified
tools — still gets downgraded to unknown/partial when its OWN result does not
prove target/window scope. Every remaining tool (sql_select, k8s_read/
describe/exec, all 14 runai_* tools) has no verification mechanism at all and
always stays downgraded.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.collectors.base import AnalysisTarget, CollectorResult
from app.services import drilldown
from app.services.root_cause_ranking import _artifact_is_evidence
from tests.test_orchestrator import make_settings


def _settings(**overrides):
    return replace(
        make_settings(),
        enable_agent_drilldown=True,
        llm_base_url="https://llm.example/v1",
        llm_model="m",
        llm_api_key="k",
        **overrides,
    )


def _target(**overrides) -> AnalysisTarget:
    base = AnalysisTarget(
        cluster="",
        project="",
        queue="",
        namespace="runai-vision",
        workload_name="train-1",
        workload_type="",
        runai_workload_id="",
        node="",
        pod="trainer-0",
        severity="warning",
        alert_name="TestAlert",
        fired_at="2026-07-10T01:00:00Z",
        resolved_at="2026-07-10T01:10:00Z",
    )
    return replace(base, **overrides)


def _kubernetes_result() -> CollectorResult:
    return CollectorResult(agent="kubernetes", status="ok", summary="pod trainer-0 issue")


async def _run_k8s_logs(target, args) -> CollectorResult:
    result = _kubernetes_result()
    await drilldown._run_query(
        _settings(),
        result,
        {"k8s_logs": {"call": drilldown._tool_k8s_logs}},
        target,
        None,
        {"tool": "k8s_logs", "args": args},
        [],
        drilldown._drilldown_masker(_settings()),
    )
    return result


# Causal window for the target above: prelude(fired) .. resolved, i.e.
# 2026-07-10T00:55:00Z .. 2026-07-10T01:10:00Z (see causal_evidence_time_range).
_IN_WINDOW_LINE = "2026-07-10T01:01:00Z CUDA out of memory: killing process"
_OUT_OF_WINDOW_LINE = "2026-07-10T05:00:00Z CUDA out of memory: killing process"


def _direct_transport_log(*, namespace: str, pod: str, lines: list[str]) -> dict:
    """Shape returned by kubernetes.py's _direct_pod_logs: fully verified."""
    return {
        "namespace": namespace,
        "pod": pod,
        "container": "",
        "previous": False,
        "transport": "direct",
        "source_verified": True,
        "time_scope_verified": True,
        "observed_entity": {"kind": "pod", "name": pod, "namespace": namespace},
        "status_code": 200,
        "error": None,
        "lines": lines,
    }


# --- 1. a result that PROVES its scope reaches present+scoped --------------


@pytest.mark.asyncio
async def test_k8s_logs_with_proven_scope_reaches_present_scoped(monkeypatch) -> None:
    """This is the teeth test: it must FAIL on pre-fix drilldown.py.

    Pre-fix, _tool_k8s_logs never set "observation"/"_verified_observation" at
    all, so _typed_artifact_result defaulted every k8s_logs artifact to
    unknown/partial no matter what the transport proved.
    """

    async def fake_k8s_logs(settings, namespace, pod, **kwargs):
        return _direct_transport_log(
            namespace=namespace, pod=pod, lines=[_IN_WINDOW_LINE]
        )

    monkeypatch.setattr(drilldown, "k8s_logs", fake_k8s_logs)
    target = _target()

    result = await _run_k8s_logs(target, {"pod": "trainer-0", "namespace": "runai-vision"})

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["observed_entity"] == {
        "kind": "pod",
        "name": "trainer-0",
        "namespace": "runai-vision",
    }
    assert _artifact_is_evidence(result.artifacts[0])


# --- 2. a result that does NOT prove its scope stays downgraded ------------
# This is the important case: it guards against over-opening the gate.


@pytest.mark.asyncio
async def test_k8s_logs_without_verification_flags_stays_downgraded(monkeypatch) -> None:
    """The common real shape: an MCP tail with no source/time verification."""

    async def fake_k8s_logs(settings, namespace, pod, **kwargs):
        # No source_verified / time_scope_verified / observed_entity at all —
        # exactly what an unstructured MCP text reply looks like.
        return {"error": None, "lines": [_IN_WINDOW_LINE]}

    monkeypatch.setattr(drilldown, "k8s_logs", fake_k8s_logs)
    target = _target()

    result = await _run_k8s_logs(target, {"pod": "trainer-0", "namespace": "runai-vision"})

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert not _artifact_is_evidence(result.artifacts[0])


@pytest.mark.asyncio
async def test_k8s_logs_untimed_mcp_tail_stays_downgraded_despite_source_match(
    monkeypatch,
) -> None:
    """source_verified alone is not enough: MCP cannot honor sinceTime."""

    async def fake_k8s_logs(settings, namespace, pod, **kwargs):
        return {
            "namespace": namespace,
            "pod": pod,
            "transport": "mcp",
            "source_verified": True,
            "time_scope_verified": False,
            "observed_entity": {"kind": "pod", "name": pod, "namespace": namespace},
            "error": None,
            "lines": [_IN_WINDOW_LINE],
        }

    monkeypatch.setattr(drilldown, "k8s_logs", fake_k8s_logs)
    target = _target()

    result = await _run_k8s_logs(target, {"pod": "trainer-0", "namespace": "runai-vision"})

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert not _artifact_is_evidence(result.artifacts[0])


@pytest.mark.asyncio
async def test_k8s_logs_out_of_window_line_stays_downgraded(monkeypatch) -> None:
    """Fully verified transport, but the only line is outside the causal window."""

    async def fake_k8s_logs(settings, namespace, pod, **kwargs):
        return _direct_transport_log(
            namespace=namespace, pod=pod, lines=[_OUT_OF_WINDOW_LINE]
        )

    monkeypatch.setattr(drilldown, "k8s_logs", fake_k8s_logs)
    target = _target()

    result = await _run_k8s_logs(target, {"pod": "trainer-0", "namespace": "runai-vision"})

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert not _artifact_is_evidence(result.artifacts[0])


@pytest.mark.asyncio
async def test_k8s_logs_for_a_different_real_pod_stays_downgraded(monkeypatch) -> None:
    """An LLM asking for the WRONG (but real, honestly-labeled) Pod's logs.

    _pod_log_observation alone would call this present+scoped (the response is
    perfectly honest about whose logs they are). The drill-down wrapper must
    additionally reject it because that Pod is not the alert's own target.
    """

    async def fake_k8s_logs(settings, namespace, pod, **kwargs):
        return _direct_transport_log(
            namespace=namespace, pod=pod, lines=[_IN_WINDOW_LINE]
        )

    monkeypatch.setattr(drilldown, "k8s_logs", fake_k8s_logs)
    target = _target()  # target.pod == "trainer-0"

    result = await _run_k8s_logs(
        target, {"pod": "some-other-pod", "namespace": "runai-vision"}
    )

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert not _artifact_is_evidence(result.artifacts[0])


# --- 3. promql_query / logql_query now earn scope from RESPONSE labels -----
# UPDATED: promql_query/logql_query used to have no target/window
# verification mechanism at all (see git history for the prior version of
# this section). They now reuse the base collector's own
# _prometheus_query_observation / _loki_query_observation, called WITH the
# real target, whose target-scope classifiers gained a "drilldown" case.
# Scope must still be proven from the RESPONSE's own labels -- the query text
# (the args the LLM sent) is never consulted.

_PROM_WINDOW = {"start": "2026-07-10T00:55:00Z", "end": "2026-07-10T01:15:00Z"}
_IN_WINDOW_TS = "2026-07-10T01:01:00Z"
_OUT_OF_WINDOW_TS = "2020-01-01T00:00:00Z"


def _prom_value_summary(*, namespace: str, pod: str, timestamp: str) -> dict:
    return {
        "numeric_sample_count": 1,
        "all_zero": False,
        "series_count_observed": 1,
        "observed_label_values": {"namespace": [namespace], "pod": [pod]},
        "observed_label_series_counts": {"namespace": 1, "pod": 1},
        "sample_windows": [{"sample_timestamps": [timestamp]}],
        "sample_timestamp_verification_required": True,
    }


async def _run_promql(monkeypatch, *, namespace: str, pod: str, timestamp: str):
    async def fake_prom_mcp(settings, name, query, *, time_range=None):
        return {
            "name": "drilldown",
            "error": None,
            "series_count": 1,
            "transport": "mcp",
            "sample": [{"metric": {"pod": pod, "namespace": namespace}, "values": [[1, "1"]]}],
            "value_summary": _prom_value_summary(namespace=namespace, pod=pod, timestamp=timestamp),
        }

    monkeypatch.setattr(drilldown, "prom_mcp_query", fake_prom_mcp)
    settings = _settings(prometheus_mcp_url="http://prom-mcp")
    result = CollectorResult(agent="prometheus", status="ok", summary="metric check")

    await drilldown._run_query(
        settings,
        result,
        {"promql_query": {"call": drilldown._tool_promql}},
        _target(),
        None,
        {
            "tool": "promql_query",
            "args": {"query": 'kube_pod_status_phase{pod="trainer-0",namespace="runai-vision"}'},
        },
        [],
        drilldown._drilldown_masker(settings),
    )
    return result


@pytest.mark.asyncio
async def test_promql_with_proven_scope_reaches_present_scoped(monkeypatch) -> None:
    """The teeth test: it must FAIL before _tool_promql classifies its result.

    Every returned series' OWN namespace+pod labels equal the alert target,
    and the sample timestamp is inside the incident window.
    """
    result = await _run_promql(
        monkeypatch, namespace="runai-vision", pod="trainer-0", timestamp=_IN_WINDOW_TS
    )

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["observed_entity"] == {"kind": "pod", "name": "trainer-0"}
    assert _artifact_is_evidence(result.artifacts[0])


@pytest.mark.asyncio
async def test_promql_for_a_different_real_pod_stays_downgraded(monkeypatch) -> None:
    """This is the important case: a real series, in the alert's own
    namespace, but for a DIFFERENT pod (the production E68 bug: a
    `namespace="runai"` Pending-phase sweep with no pod matcher returned 37
    OTHER pods, none the alert's target). Must stay unknown/partial even
    though the response is genuine, non-empty, in-window data.
    """
    result = await _run_promql(
        monkeypatch, namespace="runai-vision", pod="some-other-pod", timestamp=_IN_WINDOW_TS
    )

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert not _artifact_is_evidence(result.artifacts[0])


@pytest.mark.asyncio
async def test_promql_with_matching_labels_but_no_window_proof_stays_downgraded(
    monkeypatch,
) -> None:
    """Matching namespace+pod labels are not enough without a sample timestamp
    inside the incident window."""
    result = await _run_promql(
        monkeypatch, namespace="runai-vision", pod="trainer-0", timestamp=_OUT_OF_WINDOW_TS
    )

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert not _artifact_is_evidence(result.artifacts[0])


def _loki_entry(*, namespace: str, pod: str, timestamp: str) -> dict:
    return {
        "timestamp": timestamp,
        "line": "CUDA out of memory: killing process",
        "labels": {"namespace": namespace, "pod": pod},
    }


async def _run_logql(monkeypatch, *, namespace: str, pod: str, timestamp: str):
    async def fake_loki_mcp(settings, name, query, *, time_range=None):
        return {
            "name": "drilldown",
            "error": None,
            "line_count": 1,
            "stream_count": 0,
            "transport": "mcp",
            "sample_entries": [_loki_entry(namespace=namespace, pod=pod, timestamp=timestamp)],
            "stream_labels": [],
            "stream_labels_complete": False,
        }

    monkeypatch.setattr(drilldown, "loki_mcp_query", fake_loki_mcp)
    settings = _settings(loki_mcp_url="http://loki-mcp")
    result = CollectorResult(agent="loki", status="ok", summary="log check")

    await drilldown._run_query(
        settings,
        result,
        {"logql_query": {"call": drilldown._tool_logql}},
        _target(),
        None,
        {"tool": "logql_query", "args": {"query": '{namespace="runai-vision",pod="trainer-0"}'}},
        [],
        drilldown._drilldown_masker(settings),
    )
    return result


@pytest.mark.asyncio
async def test_logql_with_proven_scope_reaches_present_scoped(monkeypatch) -> None:
    """The teeth test: it must FAIL before _tool_logql classifies its result.

    A returned, in-window, failure-affirming entry carries the target's own
    namespace+pod labels.
    """
    result = await _run_logql(
        monkeypatch, namespace="runai-vision", pod="trainer-0", timestamp=_IN_WINDOW_TS
    )

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["observed_entity"] == {"kind": "pod", "name": "trainer-0"}
    assert _artifact_is_evidence(result.artifacts[0])


@pytest.mark.asyncio
async def test_logql_for_a_different_real_pod_stays_downgraded(monkeypatch) -> None:
    """This is the important case: a real, in-window, failure-affirming log
    line in the alert's own namespace, but labeled with a DIFFERENT pod (the
    production E112/E113 bug: a `namespace="gpu-operator"` / scheduler-pod
    sweep returned real lines for pods that were not the alert's target).
    """
    result = await _run_logql(
        monkeypatch, namespace="runai-vision", pod="some-other-pod", timestamp=_IN_WINDOW_TS
    )

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert not _artifact_is_evidence(result.artifacts[0])


@pytest.mark.asyncio
async def test_logql_with_matching_labels_but_no_window_proof_stays_downgraded(
    monkeypatch,
) -> None:
    """Matching namespace+pod labels are not enough without a parseable
    in-window timestamp on the returned entry."""
    result = await _run_logql(monkeypatch, namespace="runai-vision", pod="trainer-0", timestamp="")

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert not _artifact_is_evidence(result.artifacts[0])


@pytest.mark.asyncio
async def test_sql_select_with_real_rows_still_stays_downgraded(monkeypatch) -> None:
    """sql_select is arbitrary SELECT text: no entity or window concept exists."""

    async def fake_run_select_mcp(settings, sql):
        return [{"table_name": "workloads"}]

    monkeypatch.setattr(drilldown, "_run_select_mcp", fake_run_select_mcp)
    settings = _settings(postgres_mcp_url="http://postgres-mcp")
    result = CollectorResult(agent="postgres", status="ok", summary="db check")

    await drilldown._run_query(
        settings,
        result,
        {"sql_select": {"call": drilldown._tool_sql_select}},
        _target(),
        None,
        {"tool": "sql_select", "args": {"query": "SELECT table_name FROM workloads"}},
        [],
        drilldown._drilldown_masker(settings),
    )

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert not _artifact_is_evidence(result.artifacts[0])
