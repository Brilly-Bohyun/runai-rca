"""Regression coverage for the system-agent evidence-eligibility defect:

`_system_observation`'s time-windowed branch only ever looked at
journal/fabricmanager (`_TIME_WINDOWABLE_SOURCES`); a real dmesg/nvidia-smi
hit was invisible to it whenever the alert carried a firing window (i.e.
always), so XID/NVRM/MCE evidence could never support or refute anything
(see agent/app/services/evidence_blackboard.py `EvidenceEligibility`: only
polarity="present"/coverage="scoped" can support a hypothesis).

Fixture shapes below are trimmed, REAL values copied from a production
incident (INC-1785472267676726366-000001), not regenerated or read from disk
at test time:
  - window: start=2026-07-31T04:25:37Z end=2026-07-31T04:50:37Z.
  - node dgx01 (real artifact E114): journal and fabricmanager both verified
    clean (error_count=0); dmesg matched 7 real XID/OOM lines (trimmed to one
    representative line here), nvidia-smi matched 20.
  - node k8s-master-01 (real artifact E118): a non-GPU node, everything
    clean.

In the real run the alert never names a node (`KubePodNotReady` only carries
namespace/pod), so the node collector fell back to a cluster-wide scan and
every node's identity is unverified (`historical_node_scope_verified=False`,
`node_origin="cluster_scan"`) -- a separate, orthogonal limitation from this
fix. The tests below cover both that real (unverified-node) case and the
node-verified case the fix also unlocks (e.g. an alert that names its node
directly), constructed as a realistic variant of the same shapes.
"""

from __future__ import annotations

import pytest

from app.collectors import system as system_mod
from app.collectors.base import AnalysisTarget
from app.collectors.http_json import JsonResponse
from app.collectors.system import SystemCollector

_TIME_RANGE = {"start": "2026-07-31T04:25:37Z", "end": "2026-07-31T04:50:37Z"}

# Trimmed from the real run, node dgx01 (E114): dmesg had 7 real XID/OOM
# lines, nvidia-smi had 20 matches; journal and fabricmanager -- the only
# _TIME_WINDOWABLE_SOURCES -- both came back clean.
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
        "source": "syslog",
        "error": None,
        "error_count": 0,
        "historical_scope": False,
        "historical_window_verified": False,
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
    {
        "source": "nvidia-smi",
        "error": None,
        "error_count": 20,
        "historical_scope": False,
        "historical_window_verified": False,
        "matching_timestamps": [],
    },
    {
        "source": "nvlink",
        "error": None,
        "error_count": 0,
        "historical_scope": False,
        "historical_window_verified": False,
        "matching_timestamps": [],
    },
]

# Real E118 (k8s-master-01) shape: a non-GPU node (GPU-only sources skipped
# upstream), everything clean.
_ALL_CLEAN_SOURCES = [
    {
        "source": "dmesg",
        "error": None,
        "error_count": 0,
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
        "source": "syslog",
        "error": None,
        "error_count": 0,
        "historical_scope": False,
        "historical_window_verified": False,
        "matching_timestamps": [],
    },
]


def test_snapshot_error_sources_finds_dmesg_and_nvidia_smi() -> None:
    hits = system_mod._snapshot_error_sources(_DGX01_SOURCES)

    assert {item["source"] for item in hits} == {"dmesg", "nvidia-smi"}


def test_snapshot_error_sources_excludes_windowable_sources_even_with_hits() -> None:
    """The filter is by source identity, not merely error_count > 0: a
    journal/fabricmanager hit (already handled by the primary branch) must
    never be double-counted as a 'snapshot' hit."""
    sources = [
        {**item, "error_count": 3} if item["source"] in ("journal", "fabricmanager") else item
        for item in _DGX01_SOURCES
    ]

    hits = system_mod._snapshot_error_sources(sources)

    assert {item["source"] for item in hits} == {"dmesg", "nvidia-smi"}


def test_firing_dmesg_hit_with_verified_node_reaches_present_scoped() -> None:
    """The fix's full reachable outcome: a firing alert whose node is
    verified as the alert's own turns a dmesg/nvidia-smi hit into real,
    support-eligible evidence (was unknown/partial end to end before)."""
    observation = system_mod._system_observation(
        _DGX01_SOURCES,
        time_range=_TIME_RANGE,
        node="dgx01",
        historical_node_scope_verified=True,
        firing=True,
    )

    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")


def test_firing_dmesg_hit_with_unverified_node_stays_present_partial() -> None:
    """Teeth (spatial axis): the real E114 shape. The alert never names a
    node, so dgx01 came from a cluster-wide scan, not a verified match.
    present (visible), but not scoped (not support-eligible) -- the same bar
    an unverified journal hit is already held to by the existing
    `causal_errors and not historical_node_scope_verified` branch."""
    observation = system_mod._system_observation(
        _DGX01_SOURCES,
        time_range=_TIME_RANGE,
        node="dgx01",
        historical_node_scope_verified=False,
        firing=True,
    )

    assert (observation["polarity"], observation["coverage"]) == ("present", "partial")


def test_resolved_dmesg_hit_stays_unknown() -> None:
    """Teeth (temporal axis): a resolved/historical alert gets no override --
    identical to pre-fix behavior (matches
    test_historical_incident_scopes_journal_and_ignores_current_tails in
    test_system_collector.py, which uses a resolved target with the same
    dmesg-hit/journal-clean shape and must keep passing unmodified)."""
    observation = system_mod._system_observation(
        _DGX01_SOURCES,
        time_range=_TIME_RANGE,
        node="dgx01",
        historical_node_scope_verified=True,
        firing=False,
    )

    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")


def test_all_clean_sources_stay_unknown_even_when_firing() -> None:
    """Teeth: a source that returned nothing must not become present. Real
    E118 (k8s-master-01) shape -- every source clean."""
    observation = system_mod._system_observation(
        _ALL_CLEAN_SOURCES,
        time_range=_TIME_RANGE,
        node="k8s-master-01",
        historical_node_scope_verified=False,
        firing=True,
    )

    assert observation["polarity"] != "present"
    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")


class _Settings:
    enable_system_agent = True
    system_agent_url = "http://{node}:9095"
    system_agent_token = ""
    system_agent_timeout_seconds = 6
    system_agent_max_nodes = 12
    llm_base_url = ""
    llm_model = ""
    llm_api_key = ""


def _target(*, node: str, resolved_at: str) -> AnalysisTarget:
    return AnalysisTarget(
        cluster="",
        project="",
        queue="",
        namespace="runai-test1",
        workload_name="",
        workload_type="",
        runai_workload_id="",
        node=node,
        pod="frac-test2-0-0",
        severity="warning",
        alert_name="KubePodNotReady",
        fired_at="2026-07-31T04:30:37Z",
        resolved_at=resolved_at,
    )


@pytest.mark.asyncio
async def test_collector_end_to_end_surfaces_dmesg_xid_for_a_firing_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real bug, reproduced end to end through SystemCollector.collect():
    journal/fabricmanager clean, dmesg carries a real XID line, the alert
    names its node directly (so node scope is verified), and the alert is
    still firing. Before this fix the observation reached
    ('unknown', 'partial') and the summary claimed no error signatures were
    found, even though dmesg had one."""

    async def fake_get_json(*, params, **_kwargs):
        source = params["source"]
        lines = (
            ["NVRM: Xid (PCI:0000:65:00): 79, GPU has fallen off the bus."]
            if source == "dmesg"
            else ["all good"]
        )
        data = {"lines": lines}
        if source in ("journal", "fabricmanager"):
            data.update({"source": source, "since": params["since"], "until": params["until"]})
        return JsonResponse(url="http://node/logs", status_code=200, data=data)

    monkeypatch.setattr(system_mod, "get_json", fake_get_json)
    target = _target(node="dgx01", resolved_at="")

    result = await SystemCollector(_Settings()).collect(target)

    assert result.status == "ok"
    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert "dmesg" in result.summary
