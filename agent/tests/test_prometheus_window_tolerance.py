"""Regression coverage for the prometheus evidence-eligibility defect:

Real evidence a Prometheus query returned was unusable for RCA no matter its
shape (see agent/app/services/evidence_blackboard.py `EvidenceEligibility`:
only polarity="present"/coverage="scoped" can support a hypothesis, and only
polarity="absent"/coverage="scoped" can refute one -- everything else is
inert context).

Fixture shapes below are trimmed, REAL values copied from a production
incident (INC-1785472267676726366-000001, Grafana MCP transport), not
regenerated or read from disk at test time:
  - window: start=2026-07-31T04:25:37Z end=2026-07-31T04:50:37Z (25 minutes,
    so `_prometheus_range_step` == 60s).
  - `runai_control_plane_restarts` (75 series in production, trimmed to 1
    here): Grafana step-aligned the leading sample to 2026-07-31T04:25:00Z,
    epoch 1785471900 -- 37 seconds before `start`, one 60s step early.
  - `runai_control_plane_pending` (72 series in production): same alignment,
    all-zero gauge.
  - `container_restarts`: genuinely empty (series_count=0) under MCP.

Note on target scope: `_prometheus_query_observation` is called here without
`target=`, matching the many existing tests in test_incident_window_collectors
that isolate window/polarity logic from `_prometheus_target_scope`. In the
real run these two control-plane query names are not in
`_prometheus_target_scope`'s recognized-entity list (it only recognizes
container_*, namespace_*, runai_queue_*, runai_project_* names), so a `target`
downgrades them to unknown/partial regardless of window verification -- a
separate, pre-existing gap, not part of this fix.
"""

from __future__ import annotations

from app.collectors import prometheus

_WINDOW = {"start": "2026-07-31T04:25:37Z", "end": "2026-07-31T04:50:37Z"}

# One series trimmed from the real E58 (`runai_control_plane_restarts`)
# response body.
_STEP_ALIGNED_SERIES = {
    "first_timestamp": "1785471900",  # 2026-07-31T04:25:00Z -- 37s before start
    "last_timestamp": "1785472680",  # 2026-07-31T04:38:00Z
    "sample_timestamps": [
        "1785471900",
        "1785471960",
        "1785472020",
        "1785472080",
        "1785472140",
        "1785472200",
        "1785472260",
        "1785472320",
        "1785472380",
        "1785472440",
        "1785472500",
        "1785472560",
        "1785472620",
        "1785472680",
    ],
}


def test_step_aligned_leading_sample_is_tolerated() -> None:
    """The real E58 shape: every sample verifies in-window once the leading
    one (37s early, one 60s step before `start`) is no longer rejected."""
    summary = {"sample_windows": [_STEP_ALIGNED_SERIES]}

    assert prometheus._prometheus_samples_in_window(summary, _WINDOW) is True


def test_sample_an_hour_early_is_still_rejected() -> None:
    """Teeth: tolerance is bounded to one step (60s here), not unlimited.
    An interior sample a full hour before `start` (real leading-sample epoch
    minus 3600) must still fail verification."""
    an_hour_early = {
        "sample_windows": [
            {
                "first_timestamp": "1785471900",
                "last_timestamp": "1785472680",
                "sample_timestamps": [
                    "1785468300",  # 2026-07-31T03:25:00Z: one hour before start
                    *_STEP_ALIGNED_SERIES["sample_timestamps"],
                ],
            }
        ]
    }

    assert prometheus._prometheus_samples_in_window(an_hour_early, _WINDOW) is False


def test_sample_past_end_is_still_rejected() -> None:
    """Teeth: the tolerance only loosens the `start` boundary; `end` is untouched."""
    past_end = {
        "sample_windows": [
            {
                "first_timestamp": "1785471900",
                "last_timestamp": "1785473500",  # a minute after end (1785473437)
                "sample_timestamps": ["1785471900", "1785473500"],
            }
        ]
    }

    assert prometheus._prometheus_samples_in_window(past_end, _WINDOW) is False


def test_no_samples_returns_none_not_verified() -> None:
    """Teeth: an empty series list must not spuriously verify as in-window
    (this is what E52-E57's genuinely-empty responses look like)."""
    assert prometheus._prometheus_samples_in_window({"sample_windows": []}, _WINDOW) is None


def test_control_plane_restarts_reaches_scoped_after_tolerance_fix() -> None:
    """Full pipeline, real E58 shape: was unknown/partial (sample_window_verified
    False) end to end; now reaches absent+scoped (refutation-eligible).
    `any_series_changed_during_window=False` means the restart counts that
    exist are stale, not new during the incident -- a real refuting fact."""
    item = {
        "name": "runai_control_plane_restarts",
        "series_count": 1,
        "transport": "mcp",
        "error": None,
        "value_summary": {
            "sample_windows": [_STEP_ALIGNED_SERIES],
            "sample_timestamp_verification_required": True,
            "numeric_sample_count": 14,
            "all_zero": False,
            "series_with_multiple_samples": 1,
            "any_series_changed_during_window": False,
        },
    }

    observation = prometheus._prometheus_query_observation(item, time_range=_WINDOW)

    assert (observation["polarity"], observation["coverage"]) == ("absent", "scoped")
    assert observation["sample_window_verified"] is True


def test_control_plane_pending_reaches_scoped_after_tolerance_fix() -> None:
    """Full pipeline, real E59 shape: an all-zero gauge now reaches absent+scoped."""
    item = {
        "name": "runai_control_plane_pending",
        "series_count": 1,
        "transport": "mcp",
        "error": None,
        "value_summary": {
            "sample_windows": [_STEP_ALIGNED_SERIES],
            "sample_timestamp_verification_required": True,
            "numeric_sample_count": 14,
            "all_zero": True,
        },
    }

    observation = prometheus._prometheus_query_observation(item, time_range=_WINDOW)

    assert (observation["polarity"], observation["coverage"]) == ("absent", "scoped")


def test_empty_verified_mcp_result_now_reaches_scoped_absence() -> None:
    """UPDATED by the MCP-empty-absence fix (real E52-E57 shape, e.g.
    container_restarts): this used to stay unknown/partial forever, because
    `_prometheus_mcp_flat_result_complete` accepted an EMPTY MCP result as
    "complete" unconditionally -- no structural check at all, unlike a
    non-empty one, so it proved LESS than a direct HTTP response's empty
    result. `_prometheus_mcp_empty_result_verified` closed that gap by
    requiring the envelope's own explicit `status: success` before treating
    an empty MCP body as complete (native or flat shape). By the time an item
    reaches `_prometheus_query_observation` with `transport: "mcp"`,
    `series_count: 0`, and `error: None`, that proof already happened during
    item construction (`_prometheus_mcp_item`/`_prometheus_mcp_tool_item`) --
    an unverified empty response is stopped there with an explicit `error`
    instead (see `test_unverified_empty_mcp_envelope_stays_incomplete` in
    tests/test_prometheus_mcp_empty_absence.py for that boundary)."""
    item = {
        "name": "container_restarts",
        "series_count": 0,
        "transport": "mcp",
        "error": None,
        "value_summary": {
            "sample_windows": [],
            "sample_timestamp_verification_required": True,
            "numeric_sample_count": 0,
        },
    }

    observation = prometheus._prometheus_query_observation(item, time_range=_WINDOW)

    assert (observation["polarity"], observation["coverage"]) == ("absent", "scoped")


def test_empty_direct_result_is_unaffected_baseline() -> None:
    """Direct transport's pre-existing empty-result absence semantics (the
    other side of the same branch) are untouched by this fix."""
    item = {
        "name": "container_restarts",
        "series_count": 0,
        "transport": "direct",
        "error": None,
        "value_summary": {"numeric_sample_count": 0},
    }

    observation = prometheus._prometheus_query_observation(item, time_range=_WINDOW)

    assert (observation["polarity"], observation["coverage"]) == ("absent", "scoped")


def test_a_source_that_returned_nothing_does_not_become_present() -> None:
    """Teeth: the tolerance change must not manufacture evidence out of nothing."""
    item = {
        "name": "runai_control_plane_restarts",
        "series_count": 0,
        "transport": "mcp",
        "error": None,
        "value_summary": {"sample_windows": [], "numeric_sample_count": 0},
    }

    observation = prometheus._prometheus_query_observation(item, time_range=_WINDOW)

    assert observation["polarity"] != "present"
