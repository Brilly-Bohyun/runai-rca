"""C7: ``runai_queue_quota`` was hardcoded unknown/partial forever, even when the
Queue's own live status shows this project is currently being granted fewer GPUs
than it is asking for while its Pod sits unschedulable -- the same live-snapshot
rule already trusted for node GPU exhaustion (`_gpu_node_resource_artifact`) and
an unbound PVC claim (`_storage_claim_artifacts`). Numbers below are verbatim
from a real production run (E16): quota 16, requested "15400m" (15.4 GPU,
Kubernetes' own milli-quantity string), allocated 9.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from app.collectors import kubernetes as k8s
from tests.test_orchestrator import make_settings, make_target

_TIME_RANGE = {"start": "2026-07-31T04:25:37Z", "end": "2026-07-31T04:50:37Z"}


def _queue(*, quota="16", requested="15400m", allocated="9") -> dict:
    return {
        "metadata": {"name": "test1", "labels": {"project": "test1"}},
        "spec": {
            "parentQueue": "q-4500000",
            "priority": 100,
            "resources": {"gpu": {"quota": quota, "limit": -1, "overQuotaWeight": 16}},
        },
        "status": {
            "requested": {"nvidia.com/gpu": requested},
            "allocated": {"nvidia.com/gpu": allocated},
        },
    }


def _run(target, *, time_range=_TIME_RANGE, queue=None):
    async def fake_read(settings, kind, **kwargs):  # noqa: ANN001, ANN202
        assert kind == "queues"
        return {"kind": kind, "error": None, "data": {"items": [queue or _queue()]}}

    async def go():
        import unittest.mock

        with unittest.mock.patch.object(k8s, "k8s_read", fake_read):
            return await k8s._queue_quota_artifacts(
                "kubernetes", make_settings(), target, time_range=time_range
            )

    return asyncio.run(go())


def _target(**kwargs) -> object:
    return replace(make_target(), project="test1", **kwargs)


def test_live_deficit_while_firing_is_present_and_scoped() -> None:
    """Textbook proof: firing + this queue currently grants less than it asks."""
    items = _run(_target())

    assert len(items) == 1
    observation = items[0].result["observation"]
    assert observation["polarity"] == "present"
    assert observation["coverage"] == "scoped"
    assert observation["target_identity_verified"] is True
    assert observation["observation_window"] == _TIME_RANGE
    assert observation["snapshot_role"] == "live_incident"


def test_no_deficit_stays_unknown_partial() -> None:
    """Requested <= allocated: no live shortfall, so it must NOT be promoted."""
    items = _run(_target(), queue=_queue(requested="5000m", allocated="9"))

    observation = items[0].result["observation"]
    assert observation["polarity"] == "unknown"
    assert observation["coverage"] == "partial"
    assert observation["observation_window"] == {}
    assert observation["snapshot_role"] == "current_context"
    # Identity is still verified -- only the incident-window proof is denied.
    assert observation["target_identity_verified"] is True


def test_resolved_incident_does_not_backdate_a_live_read() -> None:
    """A live quota read cannot explain an incident that already ended."""
    resolved = _target(resolved_at="2026-07-31T05:00:00Z")

    items = _run(resolved)

    observation = items[0].result["observation"]
    assert observation["polarity"] == "unknown"
    assert observation["coverage"] == "partial"


def test_missing_time_range_does_not_promote() -> None:
    """No incident window to anchor to: stays context even with a live deficit."""
    items = _run(_target(), time_range=None)

    observation = items[0].result["observation"]
    assert observation["polarity"] == "unknown"
    assert observation["coverage"] == "partial"


def test_unparseable_quantities_do_not_promote() -> None:
    """A malformed/missing status field must fail closed, never assume a deficit."""
    items = _run(_target(), queue=_queue(requested="not-a-number", allocated="9"))

    observation = items[0].result["observation"]
    assert observation["polarity"] == "unknown"
    assert observation["coverage"] == "partial"


def test_gpu_share_quantity_parses_the_kubernetes_milli_suffix() -> None:
    from decimal import Decimal

    assert k8s._gpu_share_quantity("15400m") == Decimal("15.4")
    assert k8s._gpu_share_quantity("9") == Decimal("9")
    assert k8s._gpu_share_quantity("") is None
    assert k8s._gpu_share_quantity(None) is None
    assert k8s._gpu_share_quantity("not-a-number") is None
