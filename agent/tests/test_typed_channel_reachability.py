"""2026-08-02 audit: three signals that could not reach a family's typed
support/contradiction channel, verified against the real collector/ranker
code paths rather than the raw-text keyword-scan compatibility path.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.collectors.base import CollectorResult, causal_evidence_time_range
from app.collectors.kubernetes import _container_lifecycle_artifact, _node_condition_artifacts
from app.knowledge import _keyword_hits
from app.services import pipeline
from app.services.root_cause_ranking import (
    _FAMILY_RULES,
    artifact_contradicts_family,
    artifact_supports_family,
    rank_root_cause_candidates,
    typed_reason_family,
)
from tests.test_orchestrator import make_settings, make_target

# --- 1: a node's NetworkUnavailable condition must reach cluster_network_error ----


def _network_condition_result(target, condition: dict[str, str]) -> CollectorResult:
    responses = [
        {
            "name": "node",
            "status_code": 200,
            "error": None,
            "data": {"name": target.node, "conditions": [condition]},
        }
    ]
    return CollectorResult(
        agent="kubernetes",
        status="ok",
        confidence="high",
        summary="Kubernetes node condition query completed.",
        artifacts=_node_condition_artifacts(
            "kubernetes",
            target,
            responses,
            time_range=causal_evidence_time_range(target),
        ),
    )


def test_true_network_unavailable_condition_supports_cluster_network_error() -> None:
    target = replace(
        make_target(),
        node="k8s-lb-03",
        fired_at="2026-07-14T01:00:00Z",
        resolved_at="2026-07-14T01:10:00Z",
    )
    result = _network_condition_result(
        target,
        {
            "type": "NetworkUnavailable",
            "status": "True",
            "lastHeartbeatTime": "2026-07-14T01:05:00Z",
        },
    )

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert artifact_supports_family("cluster_network_error", result.artifacts[0])
    # Over-correction guards: the condition must not leak into this node's OTHER
    # kubernetes-agent families -- resource pressure and the GPU interconnect
    # fabric are different mechanisms (network_fabric_error's canonical agents
    # are loki/system, which structurally excludes a kubernetes-sourced card).
    assert not artifact_supports_family("node_kubelet_pressure", result.artifacts[0])
    assert not artifact_supports_family("network_fabric_error", result.artifacts[0])

    assert rank_root_cause_candidates(target, [result])[0].family == "cluster_network_error"


def test_false_network_unavailable_condition_refutes_not_supports() -> None:
    target = replace(
        make_target(),
        node="k8s-lb-03",
        fired_at="2026-07-14T01:00:00Z",
        resolved_at="2026-07-14T01:10:00Z",
    )
    result = _network_condition_result(
        target,
        {
            "type": "NetworkUnavailable",
            "status": "False",
            "lastHeartbeatTime": "2026-07-14T01:05:00Z",
        },
    )

    observation = result.artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("absent", "scoped")
    assert artifact_contradicts_family("cluster_network_error", result.artifacts[0])
    assert not artifact_supports_family("cluster_network_error", result.artifacts[0])
    # A healthy node must not even look like a network-family candidate.
    assert rank_root_cause_candidates(target, [result])[0].family == "insufficient_evidence"


@pytest.mark.parametrize(
    "unrelated_summary",
    [
        "Node gpu-node-17 condition DiskPressure=True; pods evicted",
        "ImagePullBackOff: failed to pull image nvidia/cuda:12 not found",
        "NetworkPolicy default-deny blocks port 5555 to nvidia-dcgm",
    ],
)
def test_networkunavailable_keyword_does_not_fire_on_unrelated_text(
    unrelated_summary: str,
) -> None:
    _canonical, _agents, keywords = _FAMILY_RULES["cluster_network_error"]
    hits, _negated = _keyword_hits(unrelated_summary.casefold(), list(keywords))
    assert not hits


# --- 2: pipeline's dispositive-promotion table vs the ranker's reason->family ------
# classifier are two legitimately different structures: a curated SUBSET used
# for forced-high signature promotion + hand-written specific-cause narrative
# text (keyed family->reasons), versus the broad, authoritative closed-vocabulary
# classifier every typed reason routes through for general ranking/self-check/
# harness support (keyed reason->family). A prior audit compared their raw
# dict.keys() -- family names against reason tokens -- and called the mismatch
# "drift". The contract actually worth protecting is one-directional: whichever
# reason pipeline.py treats as dispositive for a family, the ranker's own
# closed-vocabulary classifier must independently agree it belongs to that SAME
# family, or the two mechanisms could promote/narrate one family while ranking
# another.


@pytest.mark.parametrize(
    ("family", "reason"),
    sorted(
        (family, reason)
        for family, reasons in pipeline._DISPOSITIVE_TYPED_REASONS.items()
        for reason in reasons
    ),
)
def test_dispositive_reason_agrees_with_ranker_family(family: str, reason: str) -> None:
    assert typed_reason_family(reason) == family


def test_containercannotrun_is_ranker_classified_but_not_dispositive() -> None:
    """Pins the one real asymmetry found while auditing the two tables:
    'ContainerCannotRun' IS in the ranker's closed vocabulary (so a standalone
    incident still ranks under workload_startup_error), but it is deliberately
    NOT one of pipeline.py's dispositive promotion reasons -- it only reaches
    the specific-cause narrative today as a nested "deeper reason" lookup
    underneath an already-established CrashLoopBackOff
    (_reason_specific_detail). If this starts failing because someone added it
    to _DISPOSITIVE_TYPED_REASONS, that is a deliberate upgrade -- update this
    test, don't revert it.
    """
    assert typed_reason_family("ContainerCannotRun") == "workload_startup_error"
    assert "ContainerCannotRun" not in pipeline._DISPOSITIVE_TYPED_REASONS["workload_startup_error"]


# --- 3: InvalidImageName / ImageInspectError must reach container_reason ----------


def _waiting_reason_artifact(reason: str):
    target = replace(
        make_target(),
        namespace="default",
        pod="bad-image",
        fired_at="2026-07-24T04:20:00Z",
        resolved_at="",
    )
    diagnostics = [
        {
            "name": "app",
            "restartCount": 0,
            "started": False,
            "state": {"phase": "waiting", "reason": reason, "message": f"{reason} observed"},
            "lastTerminated": None,
        }
    ]
    lifecycle = _container_lifecycle_artifact(
        "kubernetes",
        make_settings(),
        target,
        {"name": target.pod, "namespace": target.namespace},
        diagnostics,
        time_range={"start": "2026-07-24T04:20:00Z", "end": "2026-07-24T04:30:00Z"},
    )
    return target, lifecycle


@pytest.mark.parametrize("reason", ["InvalidImageName", "ImageInspectError"])
def test_stuck_waiting_image_reason_reaches_container_reason(reason: str) -> None:
    # Neither reason ever leaves the "waiting" container state (a malformed
    # reference or a failed inspect never starts the container, so it never
    # restarts or terminates either) -- so this is their ONLY path to typed
    # evidence.
    target, lifecycle = _waiting_reason_artifact(reason)

    observation = lifecycle.result["observation"]
    assert observation.get("container_reason") == reason.casefold()
    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")
    assert artifact_supports_family("image_pull_error", lifecycle)

    result = CollectorResult(agent="kubernetes", status="ok", summary=reason, artifacts=[lifecycle])
    assert rank_root_cause_candidates(target, [result])[0].family == "image_pull_error"
