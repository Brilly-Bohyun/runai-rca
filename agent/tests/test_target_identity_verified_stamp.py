"""C9 fix: `observation["target_identity_verified"]` for the other five collectors.

`investigator._attach_typed_artifacts` (app/services/investigator.py, ~759)
only auto-attaches a present+scoped artifact to a ledger hypothesis the model
forgot to cite when the artifact's own observation carries
``target_identity_verified is True``. kubernetes.py (16 call sites) and
loki.py already stamped this; prometheus.py, change.py, postgres.py,
system.py and runai.py never did, so a legitimately present+scoped
observation from any of those five collectors could never reach that safety
net.

Each section below is one collector: one fixture that genuinely proves its
target carries the flag, and one that does NOT prove it and must NOT carry
the flag (the important case -- it guards against over-opening the gate).
The final test proves the actual consequence end to end with the real
investigator: a real runai.py artifact that
``investigator._attach_typed_artifacts`` could not attach before now
attaches to a matching ledger hypothesis, mirroring
``test_typed_target_verified_artifact_is_attached_to_matching_hypothesis`` in
tests/test_investigator.py, which already proved this mechanism works for
kubernetes.py.
"""

from __future__ import annotations

from dataclasses import replace

from app.collectors import change as change_mod
from app.collectors import postgres as postgres_mod
from app.collectors import prometheus as prometheus_mod
from app.collectors import runai as runai_mod
from app.collectors import system as system_mod
from app.collectors.base import AnalysisTarget, CollectorResult
from app.services.evidence_blackboard import Blackboard
from app.services.investigator import _apply_ledger_updates
from tests.test_orchestrator import make_target

# --- prometheus.py -----------------------------------------------------

_PROM_WINDOW = {"start": "2026-07-10T00:55:00Z", "end": "2026-07-10T01:15:00Z"}


def test_prometheus_scoped_series_carries_target_identity_verified() -> None:
    summary = prometheus_mod._prometheus_value_summary(
        [
            {
                "metric": {"namespace": "runai-vision", "pod": "trainer-0"},
                "values": [["2026-07-10T01:02:00Z", "1"], ["2026-07-10T01:03:00Z", "2"]],
            }
        ]
    )
    observation = prometheus_mod._prometheus_query_observation(
        {"name": "container_restarts", "series_count": 1, "value_summary": summary},
        target=make_target(),
        time_range=_PROM_WINDOW,
    )

    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["target_identity_verified"] is True


def test_prometheus_mismatched_series_does_not_carry_target_identity_verified() -> None:
    """The important case: a real, non-empty, in-window series -- for the
    WRONG pod. A proxy's broad vector must not inherit the alert's identity."""
    summary = prometheus_mod._prometheus_value_summary(
        [
            {
                "metric": {"namespace": "another-ns", "pod": "another-pod"},
                "values": [["2026-07-10T01:02:00Z", "1"], ["2026-07-10T01:03:00Z", "2"]],
            }
        ]
    )
    observation = prometheus_mod._prometheus_query_observation(
        {"name": "container_restarts", "series_count": 1, "value_summary": summary},
        target=make_target(),
        time_range=_PROM_WINDOW,
    )

    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert observation.get("target_identity_verified") is not True


# --- change.py -----------------------------------------------------------


def _change_target() -> AnalysisTarget:
    return AnalysisTarget(
        cluster="",
        project="",
        queue="",
        namespace="runai",
        workload_name="trainer",
        workload_type="",
        runai_workload_id="",
        node="gpu-node-1",
        pod="trainer-0",
        severity="warning",
        alert_name="RunAIAlert",
    )


def test_change_exact_pod_provenance_carries_target_identity_verified() -> None:
    observation = change_mod._collector_change_observation(
        changes=[
            {
                "kind": "PodDeleted",
                "name": "trainer-0",
                "namespace": "runai",
                "timestamp": "2026-07-13T00:12:00Z",
            }
        ],
        time_range={"start": "2026-07-13T00:00:00Z", "end": "2026-07-13T01:00:00Z"},
        historical_window=True,
        warnings=[],
        target=_change_target(),
    )

    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["target_identity_verified"] is True


def test_change_workload_prefix_match_does_not_carry_target_identity_verified() -> None:
    """The important case: a same-prefix Pod name is operator context, not
    proof it is the alert's own Pod."""
    observation = change_mod._collector_change_observation(
        changes=[
            {
                "kind": "PodCreated",
                "name": "trainer-worker-7f8d",
                "timestamp": "2026-07-13T00:12:00Z",
            }
        ],
        time_range={"start": "2026-07-13T00:00:00Z", "end": "2026-07-13T01:00:00Z"},
        historical_window=True,
        warnings=[],
        target=_change_target(),
    )

    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert observation.get("target_identity_verified") is not True


# --- postgres.py -----------------------------------------------------------


def _postgres_target() -> AnalysisTarget:
    return AnalysisTarget(
        cluster="",
        project="vision",
        queue="gpu-a",
        namespace="runai",
        workload_name="trainer",
        workload_type="Deployment",
        runai_workload_id="",
        node="",
        pod="",
        severity="",
        alert_name="",
        fired_at="2026-07-10T01:00:00Z",
        resolved_at="2026-07-10T01:10:00Z",
    )


def test_postgres_verified_row_carries_target_identity_verified() -> None:
    history = {
        "time_range": {"start": "2026-07-10T00:55:00Z", "end": "2026-07-10T01:15:00Z"},
        "tables": [
            {
                "schema": "audit",
                "table": "events",
                "target_correlation_available": True,
                "target_aggregate_verified": True,
                "target_matching_rows": 1,
                "context_columns": ["workload_name", "namespace", "project", "queue"],
                "target_rows": [
                    {
                        "event_time": "2026-07-10T01:04:00Z",
                        "workload_name": "trainer",
                        "namespace": "runai",
                        "project": "vision",
                        "queue": "gpu-a",
                    }
                ],
            }
        ],
    }

    artifacts = postgres_mod._postgres_history_artifacts(_postgres_target(), history)
    observation = artifacts[0].result["observation"]

    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["target_identity_verified"] is True


def test_postgres_unverified_row_does_not_carry_target_identity_verified() -> None:
    """The important case: the aggregate says 1 match, but the sampled row's
    own identity does not agree with the alert target.
    _verified_target_history_rows must refuse it -- see its docstring: 'must
    not be promoted merely because it says matching_rows > 0'."""
    history = {
        "time_range": {"start": "2026-07-10T00:55:00Z", "end": "2026-07-10T01:15:00Z"},
        "tables": [
            {
                "schema": "audit",
                "table": "events",
                "target_correlation_available": True,
                "target_aggregate_verified": True,
                "target_matching_rows": 1,
                "context_columns": ["workload_name", "namespace", "project", "queue"],
                "target_rows": [
                    {
                        "event_time": "2026-07-10T01:04:00Z",
                        "workload_name": "some-other-workload",
                        "namespace": "runai",
                        "project": "vision",
                        "queue": "gpu-a",
                    }
                ],
            }
        ],
    }

    artifacts = postgres_mod._postgres_history_artifacts(_postgres_target(), history)
    observation = artifacts[0].result["observation"]

    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert observation.get("target_identity_verified") is not True


# --- system.py (two independent sites) --------------------------------------


def test_system_log_query_observation_always_carries_target_identity_verified() -> None:
    """system_log_query() -- the only caller -- already refuses any node
    argument that doesn't match target.node before this function ever runs
    (system.py:97-102), so node identity is proven upstream, not here."""
    present = system_mod._system_log_observation(
        source="journal",
        node="dgx01",
        lookback_seconds=900,
        limit=100,
        scanned=10,
        matching=["2026-07-10T01:02:00Z NVRM: Xid 79"],
        matching_timestamps=["2026-07-10T01:02:00Z"],
        observation_window={"start": "2026-07-10T00:55:00Z", "end": "2026-07-10T01:15:00Z"},
        historical_scope=True,
    )
    absent = system_mod._system_log_observation(
        source="journal",
        node="dgx01",
        lookback_seconds=900,
        limit=100,
        scanned=10,
        matching=[],
        matching_timestamps=[],
        observation_window={"start": "2026-07-10T00:55:00Z", "end": "2026-07-10T01:15:00Z"},
        historical_scope=True,
    )

    assert (present["polarity"], present["coverage"]) == ("present", "scoped")
    assert present["target_identity_verified"] is True
    assert absent["target_identity_verified"] is True


# Real trimmed fixture from tests/test_system_source_polarity.py (production
# incident INC-1785472267676726366-000001, node dgx01): dmesg had a real
# XID/OOM hit, journal/fabricmanager both came back clean.
_DGX01_SOURCES = [
    {
        "source": "dmesg",
        "error": None,
        "error_count": 7,
        "historical_scope": False,
        "historical_window_verified": False,
        "matching_timestamps": [],
    },
    {
        "source": "journal",
        "error": None,
        "error_count": 0,
        "historical_scope": True,
        "historical_window_verified": True,
        "matching_timestamps": [],
    },
    {
        "source": "fabricmanager",
        "error": None,
        "error_count": 0,
        "historical_scope": True,
        "historical_window_verified": True,
        "matching_timestamps": [],
    },
]
_SYSTEM_TIME_RANGE = {"start": "2026-07-31T04:25:37Z", "end": "2026-07-31T04:50:37Z"}


def test_system_scan_node_verified_carries_target_identity_verified() -> None:
    observation = system_mod._system_observation(
        _DGX01_SOURCES,
        time_range=_SYSTEM_TIME_RANGE,
        node="dgx01",
        historical_node_scope_verified=True,
        firing=True,
    )

    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["target_identity_verified"] is True


def test_system_scan_node_unverified_does_not_carry_target_identity_verified() -> None:
    """The important case: the real production shape -- the alert never
    names a node, so dgx01 came from a cluster-wide scan, not a verified
    match against the alert's own node."""
    observation = system_mod._system_observation(
        _DGX01_SOURCES,
        time_range=_SYSTEM_TIME_RANGE,
        node="dgx01",
        historical_node_scope_verified=False,
        firing=True,
    )

    assert (observation["polarity"], observation["coverage"]) == ("present", "partial")
    assert observation["target_identity_verified"] is False


# --- runai.py --------------------------------------------------------------


def test_runai_identity_match_carries_target_identity_verified() -> None:
    observation = runai_mod._runai_query_observation(
        {
            "name": "workloads",
            "status_code": 200,
            "data": {
                "workloads": [
                    {"name": "trainer", "projectName": "vision", "queueName": "gpu-a"}
                ]
            },
        },
        target=make_target(),  # workload_name="trainer", project="vision", queue="gpu-a"
        used_mcp=True,
    )

    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["target_identity_verified"] is True


def test_runai_exact_404_carries_target_identity_verified() -> None:
    target = replace(
        make_target(),
        fired_at="2026-07-10T01:00:00Z",
        runai_workload_id="550e8400-e29b-41d4-a716-446655440000",
    )
    observation = runai_mod._runai_query_observation(
        {"name": "workload_by_id", "status_code": 404, "error": "HTTP 404", "data": None},
        target=target,
        used_mcp=False,
    )

    assert (observation["polarity"], observation["coverage"]) == ("absent", "scoped")
    assert observation["target_identity_verified"] is True


def test_runai_broad_nonmatch_does_not_carry_target_identity_verified() -> None:
    """The important case: a real, non-empty, successful response -- for a
    DIFFERENT resource. An ignored server-side filter is not proof."""
    observation = runai_mod._runai_query_observation(
        {"name": "projects", "status_code": 200, "data": {"projects": [{"name": "other"}]}},
        target=make_target(),
        used_mcp=True,
    )

    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert observation.get("target_identity_verified") is not True


# --- the point of the whole task: the attach gate actually opens now -------


def test_runai_present_scoped_artifact_now_attaches_to_a_matching_hypothesis() -> None:
    """Before this fix, runai.py never set target_identity_verified, so
    investigator._attach_typed_artifacts could never auto-attach even a
    genuinely present+scoped runai artifact the model forgot to cite."""
    target = make_target()  # workload_name="trainer", project="vision", queue="gpu-a"
    item = runai_mod._validated_runai_query_results(
        [
            {
                "name": "workloads",
                "status_code": 200,
                "transport": "direct",
                "data": {
                    "workloads": [
                        {
                            "name": "trainer",
                            "projectName": "vision",
                            "queueName": "gpu-a",
                            "reason": "Preempted: queue is over quota",
                        }
                    ]
                },
            }
        ]
    )[0]
    signal = runai_mod._runai_query_artifact("runai", item, target=target, used_mcp=False)

    observation = signal.result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["target_identity_verified"] is True

    result = CollectorResult(agent="runai", status="ok", summary="runai", artifacts=[signal])
    board = Blackboard()
    board.add_result("runai", result, entity="workload:trainer")
    fact_id = board.evidence_id_for(signal)
    # "runai_scheduling_quota" (knowledge/families.yaml) allows agent "runai"
    # and keyword "quota"; _runai_workload_status_reasons surfaces the fake
    # API's "reason" field into the artifact's highlights, which is what
    # root_cause_ranking.artifact_supports_family scans -- a real match, not
    # a stub.
    ledger = [{"id": "H1", "family": "runai_scheduling_quota", "status": "supported"}]

    _apply_ledger_updates(
        ledger,
        [],
        blackboard=board,
        artifacts=[signal],
        eligible_support_ids={fact_id},
    )

    assert ledger[0]["evidence_for"] == [fact_id]
