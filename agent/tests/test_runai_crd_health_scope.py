"""C5: a Run:ai CRD condition that entered a bad state BEFORE the causal
window and never recovered IS evidence. lastTransitionTime records when the
condition started, not when it stopped being true; _runai_crd_health_artifacts
only ever receives CURRENTLY-bad findings (see _crd_not_ready), so one that
began before the window and is still bad now was bad throughout it too. The
old scope test additionally required the transition to fall AFTER the
window's start, which a steady-state condition — one transition, then it
just sits — can never satisfy: the causal window is minutes wide, real
Run:ai CRD transitions sit days to weeks before it.

Literal timestamps below are the real values from a 2026-07-31 incident's
20 runai_crd_health findings (E20-E39): all 20 transitioned before the
causal window closed, none inside it, none after it."""

from __future__ import annotations

from app.collectors import kubernetes as k8s
from tests.test_orchestrator import make_settings

_TIME_RANGE = {"start": "2026-07-31T04:25:37Z", "end": "2026-07-31T04:32:49Z"}


def _finding(**overrides: str) -> dict[str, str]:
    base = {
        "kind": "InteractiveWorkload",
        "name": "aiperftest",
        "namespace": "runai-test1",
        "reason": "Unschedulable",
        "message": "",
        "lastTransitionTime": "2026-07-22T01:29:13Z",
    }
    base.update(overrides)
    return base


def test_transition_before_the_window_that_is_still_bad_is_scoped() -> None:
    # Real value from the incident: transitioned 9 days before the window.
    artifacts = k8s._runai_crd_health_artifacts(
        "kubernetes", make_settings(), [_finding()], time_range=_TIME_RANGE
    )
    observation = artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")


def test_transition_weeks_before_the_window_that_is_still_bad_is_also_scoped() -> None:
    # Real value from the incident: transitioned about a month before the
    # window (2026-06-29). Steady state has no freshness deadline — it is
    # either still true (evidence) or it isn't (absent from `findings`
    # entirely, since _crd_not_ready only reports current status).
    artifacts = k8s._runai_crd_health_artifacts(
        "kubernetes",
        make_settings(),
        [_finding(lastTransitionTime="2026-06-29T07:09:33Z", name="aler-test3")],
        time_range=_TIME_RANGE,
    )
    observation = artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")


def test_transition_after_the_window_is_still_rejected() -> None:
    """Over-correction guard: a condition that only went bad AFTER the causal
    window closed did not cause it — it is a later, unrelated change (or a
    resolved condition's stale reporting) and must stay unscoped."""
    artifacts = k8s._runai_crd_health_artifacts(
        "kubernetes",
        make_settings(),
        [_finding(lastTransitionTime="2026-07-31T04:40:00Z")],  # after `end`
        time_range=_TIME_RANGE,
    )
    observation = artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")


def test_transition_still_inside_the_window_stays_scoped() -> None:
    # The original, already-working case must not regress.
    artifacts = k8s._runai_crd_health_artifacts(
        "kubernetes",
        make_settings(),
        [_finding(lastTransitionTime="2026-07-31T04:28:00Z")],
        time_range=_TIME_RANGE,
    )
    observation = artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("present", "scoped")


def test_cluster_scoped_crd_without_namespace_stays_unscoped() -> None:
    # Unchanged guard: a cluster-scoped CRD cannot stand in for a namespaced
    # incident target, regardless of its transition time.
    artifacts = k8s._runai_crd_health_artifacts(
        "kubernetes",
        make_settings(),
        [_finding(namespace="")],
        time_range=_TIME_RANGE,
    )
    observation = artifacts[0].result["observation"]
    assert (observation["polarity"], observation["coverage"]) == ("unknown", "partial")


def test_all_20_real_incident_findings_reach_present_scoped_after_the_fix() -> None:
    """MEASURE: the real 2026-07-31 incident shipped 20 runai_crd_health
    findings (E20-E39), all InteractiveWorkload conditions in runai-test1,
    lastTransitionTime ranging 2026-06-29 .. 2026-07-31T04:14:53Z — all
    before the causal window, none after it. Before this fix: 0/20
    present+scoped (every transition predates `start`). After: all 20,
    because every one of them satisfies transition <= end and none of them
    transitioned after the window — there is no field in this real dataset
    that would justify rejecting any of them. (Contrast
    test_transition_after_the_window_is_still_rejected above, which proves
    the scope test still has teeth: it is not simply gone.)"""
    transition_times = [
        "2026-07-22T01:29:13Z",
        "2026-06-29T07:09:33Z",
        "2026-07-01T06:42:03Z",
        "2026-07-02T01:51:05Z",
        "2026-07-31T04:14:53Z",
        "2026-07-30T19:00:40Z",
        "2026-07-01T05:37:03Z",
        "2026-07-01T05:37:23Z",
        "2026-07-01T06:42:03Z",
        "2026-07-01T06:42:13Z",
        "2026-07-01T06:57:13Z",
        "2026-07-01T08:07:33Z",
        "2026-07-01T08:07:33Z",
        "2026-07-01T08:07:33Z",
        "2026-07-02T01:51:05Z",
        "2026-07-01T08:48:03Z",
        "2026-07-01T08:55:13Z",
        "2026-07-01T08:57:33Z",
        "2026-07-01T08:58:43Z",
        "2026-07-01T08:59:23Z",
    ]
    findings = [
        _finding(name=f"workload-{i}", lastTransitionTime=t)
        for i, t in enumerate(transition_times)
    ]
    artifacts = k8s._runai_crd_health_artifacts(
        "kubernetes", make_settings(), findings, time_range=_TIME_RANGE
    )
    scoped = [
        a
        for a in artifacts
        if a.result["observation"]["polarity"] == "present"
        and a.result["observation"]["coverage"] == "scoped"
    ]
    assert len(scoped) == 20
