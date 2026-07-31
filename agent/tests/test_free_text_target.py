"""A chat request names its subject in prose; the plan must find it — or nothing."""

import asyncio

import pytest

from app.collectors import kubernetes as k8s


def _cluster(**kinds):
    async def fake_read(settings, kind, **kwargs):
        items = [
            {"metadata": {"name": name, "namespace": namespace}}
            for namespace, name in kinds.get(kind, [])
        ]
        return {"data": {"items": items}}

    return fake_read


def test_resolves_a_two_word_subject_to_the_live_workload(monkeypatch):
    monkeypatch.setattr(
        k8s,
        "k8s_read",
        _cluster(
            deployments=[("runai-backend", "thanos-query")],
            statefulsets=[("runai-backend", "runai-backend-thanos-receive")],
        ),
    )
    assert asyncio.run(
        k8s.resolve_target_from_text(None, "Thanos Receive 가 OOMKilled 반복돼서 죽어요")
    ) == ("runai-backend", "runai-backend-thanos-receive")


def test_an_ambiguous_name_resolves_to_nothing(monkeypatch):
    """Two thanos workloads and only the bare word: guessing would misdirect the run."""
    monkeypatch.setattr(
        k8s,
        "k8s_read",
        _cluster(
            deployments=[("runai-backend", "thanos-query"), ("runai-backend", "thanos-store")]
        ),
    )
    assert asyncio.run(k8s.resolve_target_from_text(None, "thanos 가 이상합니다")) == ("", "")


def test_prose_without_a_subject_resolves_to_nothing(monkeypatch):
    monkeypatch.setattr(k8s, "k8s_read", _cluster(deployments=[("runai", "scheduler")]))
    assert asyncio.run(k8s.resolve_target_from_text(None, "클러스터가 느려요")) == ("", "")


@pytest.mark.parametrize(
    ("name", "expected"),
    [("runai-backend-thanos-receive", True), ("receiver-gateway", False), ("thanos", False)],
)
def test_matching_is_anchored_on_hyphen_boundaries(name, expected):
    assert k8s._text_target_matches(name, ["thanos-receive"]) is expected
