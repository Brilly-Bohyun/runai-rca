"""TASK 2: an empty MCP PromQL result can become a verified scoped absence.

Before this fix, `_prometheus_mcp_flat_result_complete` validated the shape
of a NON-empty flat result (every item must look like a real `value`/
`values` sample) but accepted an EMPTY list unconditionally -- so an empty
MCP response proved LESS than an empty direct HTTP one, and
`_prometheus_query_observation` only granted scoped absence when
`transport == "direct"` (see `test_incident_window_collectors.py::
test_prometheus_empty_vector_requires_direct_native_transport`, which locks
that OLD behavior and is owned by another worker).

The fix: `_prometheus_mcp_empty_result_verified` requires the envelope's own
explicit `status: success` before an EMPTY MCP result (native or flat shape)
counts as complete at all. Only once that is proven does
`_prometheus_query_observation` treat `transport == "mcp"` the same as
`transport == "direct"` for an empty result.

This file tests three layers: the validator functions directly, the item
construction boundary (`_prometheus_mcp_item`) where an unverified empty
response is stopped with an explicit `error`, and the full collector
pipeline end to end.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.collectors import prometheus
from tests.test_datasource_mcp_collectors import _McpResult, _patch_mcp_calls
from tests.test_orchestrator import make_settings, make_target

_WINDOW = {"start": "2026-07-10T00:55:00Z", "end": "2026-07-10T01:15:00Z"}


# --- 1. the validator functions, directly ----------------------------------


def test_empty_result_verified_requires_explicit_success_status() -> None:
    assert prometheus._prometheus_mcp_empty_result_verified({"status": "success"}) is True
    assert prometheus._prometheus_mcp_empty_result_verified({"status": "success", "data": {}}) is True


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"status": "unknown"},
        {"data": {"result": []}},  # native shape, but no status at all
        {"result": []},  # flat shape, but no status at all
        "not a dict",
        None,
        [],
    ],
)
def test_empty_result_verified_rejects_missing_or_non_success_status(data) -> None:
    assert prometheus._prometheus_mcp_empty_result_verified(data) is False


def test_flat_result_complete_empty_case_delegates_to_empty_verifier() -> None:
    # Empty list: complete only when the envelope proves status success.
    assert prometheus._prometheus_mcp_flat_result_complete([], {"status": "success"}) is True
    assert prometheus._prometheus_mcp_flat_result_complete([], {"status": "unknown"}) is False
    assert prometheus._prometheus_mcp_flat_result_complete([], {}) is False


def test_flat_result_complete_non_empty_case_is_unchanged_by_the_fix() -> None:
    # Non-empty: still validated per-item, regardless of status (unaffected
    # regression check -- the flat fallback can legitimately omit `status` on
    # a genuine non-empty answer; only the empty case needed tightening).
    valid = [{"metric": {}, "value": [1, "1"]}]
    invalid = [{"metric": {}}]
    assert prometheus._prometheus_mcp_flat_result_complete(valid, {}) is True
    assert prometheus._prometheus_mcp_flat_result_complete(invalid, {"status": "success"}) is False


class _EmptyEnvelope:
    """Payloads exercising both accepted MCP result shapes (native + flat)."""

    NATIVE_VERIFIED = {"status": "success", "data": {"result": []}}
    NATIVE_UNVERIFIED = {"data": {"result": []}}  # no status: the closed native loophole
    FLAT_RESULT_VERIFIED = {"status": "success", "result": []}
    FLAT_RESULT_UNVERIFIED = {"result": []}
    FLAT_DATA_VERIFIED = {"status": "success", "data": []}
    FLAT_DATA_UNVERIFIED = {"data": []}
    MISROUTED = {"datasources": [{"uid": "loki", "type": "loki"}]}


@pytest.mark.parametrize(
    "data",
    [
        _EmptyEnvelope.NATIVE_VERIFIED,
        _EmptyEnvelope.FLAT_RESULT_VERIFIED,
        _EmptyEnvelope.FLAT_DATA_VERIFIED,
    ],
)
def test_mcp_response_complete_accepts_well_formed_empty_envelopes(data) -> None:
    assert prometheus._prometheus_mcp_response_complete(data) is True
    assert prometheus._prometheus_mcp_result(data) == []


@pytest.mark.parametrize(
    "data",
    [
        _EmptyEnvelope.NATIVE_UNVERIFIED,
        _EmptyEnvelope.FLAT_RESULT_UNVERIFIED,
        _EmptyEnvelope.FLAT_DATA_UNVERIFIED,
        _EmptyEnvelope.MISROUTED,
    ],
)
def test_mcp_response_complete_rejects_unverified_or_misrouted_envelopes(data) -> None:
    assert prometheus._prometheus_mcp_response_complete(data) is False


# --- 2. the item-construction boundary (_prometheus_mcp_item) --------------


def test_verified_empty_mcp_item_carries_no_error() -> None:
    item = prometheus._prometheus_mcp_item(
        "container_restarts", "up", "http://mcp", _EmptyEnvelope.NATIVE_VERIFIED, _WINDOW
    )
    assert item["error"] is None
    assert item["series_count"] == 0
    assert item["transport"] == "mcp"


def test_unverified_empty_mcp_envelope_stays_incomplete() -> None:
    """The teeth test for the item-construction boundary: an empty MCP result
    with no proof the query ran successfully is stopped HERE with an explicit
    error, before it can ever reach `_prometheus_query_observation` as a
    clean `series_count == 0` with no error."""
    item = prometheus._prometheus_mcp_item(
        "container_restarts", "up", "http://mcp", _EmptyEnvelope.NATIVE_UNVERIFIED, _WINDOW
    )
    assert item["error"] == "Prometheus MCP response missing a recognized metric result"


# --- 3. the classifier gate (_prometheus_query_observation) ----------------


def test_verified_empty_mcp_result_reaches_absent_scoped() -> None:
    item = {
        "name": "container_restarts",
        "series_count": 0,
        "transport": "mcp",
        "error": None,
        "value_summary": {"sample_windows": [], "sample_timestamp_verification_required": True},
    }
    observation = prometheus._prometheus_query_observation(item, time_range=_WINDOW)
    assert (observation["polarity"], observation["coverage"]) == ("absent", "scoped")


# --- 4. the full collector pipeline, end to end -----------------------------


@pytest.mark.asyncio
async def test_collector_treats_well_formed_empty_mcp_response_as_scoped_absence(
    monkeypatch,
) -> None:
    async def fake_mcp_call(url, tool, arguments):
        if tool == "list_datasources":
            return _McpResult([{"type": "prometheus", "uid": "prom"}])
        return _McpResult(_EmptyEnvelope.NATIVE_VERIFIED)

    _patch_mcp_calls(monkeypatch, prometheus, fake_mcp_call)
    # queue/project cleared: those metrics are CONTEXT_ONLY (never scoped
    # regardless of this fix) and would otherwise dilute the assertion below.
    # container_restarts is the one query in this reduced set with ordinary
    # absent/scoped semantics for an empty, target-scoped result.
    result = await prometheus.PrometheusCollector(
        replace(make_settings(), prometheus_mcp_url="http://grafana-mcp/mcp")
    ).collect(
        replace(
            make_target(),
            queue="",
            project="",
            fired_at="2026-07-10T01:00:00Z",
            resolved_at="2026-07-10T01:10:00Z",
        )
    )

    assert all(query["error"] is None for query in result.details["queries"])
    signals = [artifact for artifact in result.artifacts if artifact.type == "promql_signal"]
    restarts = next(a for a in signals if "container_restarts" in a.title)
    assert (
        restarts.result["observation"]["polarity"],
        restarts.result["observation"]["coverage"],
    ) == ("absent", "scoped")
    assert restarts.result["observation"]["observed_entity"] == {
        "kind": "pod",
        "name": "trainer-0",
    }


@pytest.mark.asyncio
async def test_collector_does_not_trust_an_empty_mcp_response_with_no_status(
    monkeypatch,
) -> None:
    """Same empty result list, but the envelope never asserts success -- must
    NOT reach absent+scoped; the query is reported as failed instead."""

    async def fake_mcp_call(url, tool, arguments):
        if tool == "list_datasources":
            return _McpResult([{"type": "prometheus", "uid": "prom"}])
        return _McpResult(_EmptyEnvelope.NATIVE_UNVERIFIED)

    _patch_mcp_calls(monkeypatch, prometheus, fake_mcp_call)
    result = await prometheus.PrometheusCollector(
        replace(make_settings(), prometheus_mcp_url="http://grafana-mcp/mcp")
    ).collect(
        replace(
            make_target(),
            fired_at="2026-07-10T01:00:00Z",
            resolved_at="2026-07-10T01:10:00Z",
        )
    )

    assert all(query["error"] for query in result.details["queries"])
    signals = [artifact for artifact in result.artifacts if artifact.type == "promql_signal"]
    assert all(artifact.result["observation"]["polarity"] == "unavailable" for artifact in signals)
