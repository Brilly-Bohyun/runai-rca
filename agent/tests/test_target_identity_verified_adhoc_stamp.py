"""Follow-up to test_target_identity_verified_stamp.py ("C9 fix"): that fix
stamped ``target_identity_verified`` in each collector's MAIN observation
builder (prometheus/change/postgres/system/runai). Four of those collectors
ALSO expose an ad-hoc LLM drill-down tool (see app.services.drilldown) whose
result can independently reach present+scoped, through a code path the C9
fix never touched. This file resolves each of the four, site by site:

  * change.py   -- REAL GAP. ``change_query()``'s own ``_change_observation``
    builder (kind "change_query") is separate from the fixed
    ``_collector_change_observation`` and never stamped the flag either.
    Fixed here by reusing ``_collector_change_target_scope`` -- the exact
    same proof the sibling already uses -- gated so the ad-hoc tool's
    LLM-narrowable query (a ``source``/``component`` filter the main
    collector's own fixed, comprehensive query never has) cannot inherit
    that function's "empty sweep = proof" shortcut.
  * prometheus.py -- NON-ISSUE, already fixed. ``drilldown._tool_promql``
    calls the very same (already-fixed) ``_prometheus_query_observation``
    with ``name="drilldown"`` and the real target; ``_prometheus_target_scope``
    has a dedicated "drilldown" branch. Pinned below so the wiring cannot
    silently regress.
  * postgres.py / runai.py -- NON-ISSUE, and there is nothing to fix: neither
    file contains a second observation builder at all. Their ad-hoc tools
    (``sql_select``; the 14 ``runai_*`` MCP tools) are implemented entirely
    inside drilldown.py and never set ``_verified_observation``, so
    ``_typed_artifact_result`` (drilldown.py ~848) discards whatever they
    return and force-downgrades to unknown/partial -- see its own docstring
    and tests/test_drilldown_verification_gate.py. Pinned below by feeding
    ``_typed_artifact_result`` a best-case, identity-shaped outcome and
    showing it still cannot reach present+scoped.
"""

from __future__ import annotations

import pytest

from app.collectors import change as change_mod
from app.collectors import prometheus as prometheus_mod
from app.collectors.base import AnalysisTarget
from app.services import drilldown
from tests.test_drilldown_verification_gate import _run_promql
from tests.test_orchestrator import make_target

# --- change.py: real gap, fixed -------------------------------------------


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


_CHANGE_WINDOW = {"start": "2026-07-13T00:00:00Z", "end": "2026-07-13T01:00:00Z"}


def _change_query_observation(changes: list[dict]) -> dict:
    """Call the ad-hoc drill-down tool's OWN builder (change_query's
    _change_observation), not the already-fixed _collector_change_observation."""
    return change_mod._change_observation(
        namespace="runai",
        node="",
        source="pod",
        lookback_seconds=7200,
        limit=20,
        changes=changes,
        context_changes=[],
        truncated=0,
        warnings=[],
        component="",
        observation_window=_CHANGE_WINDOW,
        historical_window=True,
        causal_window=_CHANGE_WINDOW,
        target=_change_target(),
    )


def test_change_query_exact_pod_carries_target_identity_verified() -> None:
    """Teeth test: FAILS before the fix. Pre-fix, _change_observation never
    computed or returned target_scope_verified/target_identity_verified at
    all, so ``observation["target_identity_verified"]`` raised KeyError and
    ``observation.get(...)`` was always None (never True)."""
    observation = _change_query_observation(
        changes=[
            {
                "kind": "Pod",
                "name": "trainer-0",
                "namespace": "runai",
                "timestamp": "2026-07-13T00:12:00Z",
            }
        ]
    )

    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["target_identity_verified"] is True


def test_change_query_workload_prefix_match_does_not_carry_target_identity_verified() -> None:
    """The important case: change_query()'s _partition_target_changes treats
    a same-prefix Pod as "correlated" (not "context"), so coverage still
    reaches scoped -- exactly mirroring
    test_change_workload_prefix_match_does_not_carry_target_identity_verified
    in test_target_identity_verified_stamp.py for the main builder. A prefix
    match is not proof it is the alert's own Pod."""
    observation = _change_query_observation(
        changes=[
            {
                "kind": "Pod",
                "name": "trainer-worker-7f8d",
                "namespace": "runai",
                "timestamp": "2026-07-13T00:12:00Z",
            }
        ]
    )

    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation.get("target_identity_verified") is not True


def test_change_query_empty_sweep_does_not_borrow_the_main_builders_shortcut() -> None:
    """_collector_change_target_scope treats an EMPTY sweep as proof of
    absence, but only because the main collector's own query is always
    comprehensive for the target. The ad-hoc tool lets the LLM narrow
    ``source``/``component`` to something unrelated to the target's pod, so
    _change_observation must not call that shortcut when it has no records
    to actually check -- see the comment above target_scope_verified in
    change.py's _change_observation."""
    observation = _change_query_observation(changes=[])

    assert (observation["polarity"], observation["coverage"]) == ("absent", "scoped")
    assert observation.get("target_identity_verified") is not True


# --- prometheus.py: non-issue, already fixed -------------------------------

_PROM_WINDOW = {"start": "2026-07-10T00:55:00Z", "end": "2026-07-10T01:15:00Z"}


def test_promql_drilldown_scoped_series_carries_target_identity_verified() -> None:
    """Pin WHY prometheus.py needs no separate fix: drilldown._tool_promql
    (app/services/drilldown.py:2506) calls this exact function -- the SAME
    one the main collector path uses, already carrying the C9 fix -- with
    name="drilldown" and the real alert target. _prometheus_target_scope's
    dedicated "drilldown" branch (prometheus.py:1246) then proves identity
    from the response's OWN labels."""
    summary = prometheus_mod._prometheus_value_summary(
        [
            {
                "metric": {"namespace": "runai-vision", "pod": "trainer-0"},
                "values": [["2026-07-10T01:02:00Z", "1"]],
            }
        ]
    )
    observation = prometheus_mod._prometheus_query_observation(
        {"name": "drilldown", "series_count": 1, "value_summary": summary},
        target=make_target(),
        time_range=_PROM_WINDOW,
    )

    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["target_identity_verified"] is True


def test_promql_drilldown_mismatched_pod_does_not_carry_target_identity_verified() -> None:
    """The production bug _prometheus_target_scope's "drilldown" branch
    closed: a namespace-wide sweep with no pod matcher can return real,
    non-empty, in-window data for a DIFFERENT pod."""
    summary = prometheus_mod._prometheus_value_summary(
        [
            {
                "metric": {"namespace": "runai-vision", "pod": "some-other-pod"},
                "values": [["2026-07-10T01:02:00Z", "1"]],
            }
        ]
    )
    observation = prometheus_mod._prometheus_query_observation(
        {"name": "drilldown", "series_count": 1, "value_summary": summary},
        target=make_target(),
        time_range=_PROM_WINDOW,
    )

    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")
    assert observation.get("target_identity_verified") is not True


@pytest.mark.asyncio
async def test_tool_promql_end_to_end_carries_target_identity_verified(monkeypatch) -> None:
    """Full-wiring pin, reusing test_drilldown_verification_gate.py's own
    helper: drilldown._tool_promql really does route through
    _prometheus_query_observation end to end, including the
    ``_VERIFIED_OBSERVATION`` marker that lets the observation survive
    _typed_artifact_result intact."""
    result = await _run_promql(
        monkeypatch,
        namespace="runai-vision",
        pod="trainer-0",
        timestamp="2026-07-10T01:01:00Z",
    )

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert observation["target_identity_verified"] is True


# --- postgres.py / runai.py: non-issue, nothing to fix ----------------------
#
# Neither collector has a second observation builder: sql_select and the 14
# runai_* MCP tools are implemented entirely inside drilldown.py (_tool_sql_
# select, _official_runai_tool/_official_workload_tool) and never construct
# an "observation" dict or set "_verified_observation" -- confirmed by
# reading their source, not merely asserted here. _typed_artifact_result
# therefore discards whatever they return and force-downgrades polarity/
# coverage. Prove that even a best-case, identity-shaped outcome cannot
# reach present+scoped, so target_identity_verified is moot for both.


def test_sql_select_outcome_cannot_reach_present_scoped_regardless_of_content() -> None:
    outcome = {
        "query": "SELECT * FROM workloads",
        "title": "t",
        "error": None,
        "result": {"rows": [{"namespace": "runai-vision", "pod": "trainer-0"}]},
        # Even an (unrealistic) best-case top-level claim of scoped presence
        # must not survive -- _typed_artifact_result trusts self-reported
        # polarity/coverage only from a marked adapter.
        "polarity": "present",
        "coverage": "scoped",
    }

    payload = drilldown._typed_artifact_result(
        outcome, error=None, tool="sql_select", artifact_type="drilldown_query"
    )

    observation = payload["observation"]
    assert (observation["polarity"], observation["coverage"]) != ("present", "scoped")
    assert observation.get("target_identity_verified") is not True


def test_runai_mcp_tool_outcome_cannot_reach_present_scoped_regardless_of_content() -> None:
    outcome = {
        "query": "MCP get_workload_status",
        "title": "t",
        "error": None,
        "result": {"workloadId": "550e8400-e29b-41d4-a716-446655440000", "name": "trainer"},
        "polarity": "present",
        "coverage": "scoped",
    }

    payload = drilldown._typed_artifact_result(
        outcome, error=None, tool="runai_workload_status", artifact_type="drilldown_query"
    )

    observation = payload["observation"]
    assert (observation["polarity"], observation["coverage"]) != ("present", "scoped")
    assert observation.get("target_identity_verified") is not True
