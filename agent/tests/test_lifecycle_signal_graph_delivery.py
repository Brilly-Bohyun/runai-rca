"""``requires_lifecycle_signal`` must survive the TypeDB round-trip into the
real gate that consumes it — ``pipeline._gate_lifecycle_symptoms``.

Before this, ``_KNOWLEDGE_QUERY``/the per-symptom queries in kg_enrichment.py
never selected the attribute, so a ``platform_lifecycle_change`` symptom
sourced from the graph always reached the gate with the key ABSENT. Since the
gate reads ``sym.get("requires_lifecycle_signal")`` (falsy when absent), the
guard that exists to stop a coincidental unrelated rollout from promoting
``platform_lifecycle_change`` never fired on the TypeDB path — only on the
degraded YAML fallback, where ``app/knowledge.py::_load_failure_modes``
already carried the field.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from app.collectors.base import AnalysisTarget
from app.knowledge import load_failure_modes, match_failure_mode_symptoms
from app.services.kg_enrichment import _query_kg
from app.services.pipeline import _gate_lifecycle_symptoms
from ontology.load_knowledge import _ensure_symptom

_OBSERVED = "controller deployment mid-rollout restart on node gpu-1"


def _target() -> AnalysisTarget:
    return AnalysisTarget(
        cluster="", project="", queue="", namespace="", workload_name="",
        workload_type="", runai_workload_id="", node="gpu-1", pod="",
        severity="warning", alert_name="KubeDeploymentRolloutStuck",
    )


class _FakeClient:
    """Mocks a TypeDB reader carrying one lifecycle-gated symptom, exactly as
    ontology/load_knowledge.py + the schema.tql attribute would produce it."""

    @contextmanager
    def open_reader(self):
        def run(query: str) -> list[dict]:
            if "not {" in query:
                return []
            if "has keyword $kw" in query:
                return [
                    {
                        "fam": "platform_lifecycle_change",
                        "sn": "Mid-Rollout Restart",
                        "kw": "mid-rollout",
                        "st": "Wait for the rollout to complete.",
                    }
                ]
            if "has requires_lifecycle_signal $requires_lifecycle_signal" in query:
                return [{"sn": "Mid-Rollout Restart", "requires_lifecycle_signal": True}]
            return []

        yield run


class _FakeTx:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def query(self, query: str) -> Any:
        self.queries.append(query)
        return self

    def resolve(self) -> Any:
        return self

    def as_concept_rows(self) -> list[Any]:
        return []


def test_loader_writes_the_flag_for_every_authored_lifecycle_symptom() -> None:
    """YAML -> TypeDB loader leg: every ``requires_lifecycle_signal: true``
    symptom in failure_modes.yaml must actually issue the write."""
    modes = load_failure_modes("knowledge/failure_modes.yaml")
    lifecycle_symptoms = [
        symptom
        for symptom in modes.get("platform_lifecycle_change", [])
        if symptom.get("requires_lifecycle_signal")
    ]
    assert len(lifecycle_symptoms) == 3  # pins the authored count

    for symptom in lifecycle_symptoms:
        tx = _FakeTx()
        _ensure_symptom(
            tx,
            symptom["symptom"],
            symptom["keywords"],
            requires_lifecycle_signal=True,
        )
        assert "has requires_lifecycle_signal true" in "\n".join(tx.queries), symptom["symptom"]


def test_graph_symptom_carries_the_flag_into_the_knowledge_dict() -> None:
    knowledge = _query_kg(_FakeClient(), _target())["knowledge"]  # type: ignore[arg-type]

    symptom = knowledge["platform_lifecycle_change"][0]
    assert symptom["requires_lifecycle_signal"] is True


def test_real_pipeline_gate_now_drops_the_graph_symptom_without_an_active_rollout() -> None:
    """The actual production gate (unmodified) must react to the delivered flag."""
    knowledge = _query_kg(_FakeClient(), _target())["knowledge"]  # type: ignore[arg-type]
    matches = match_failure_mode_symptoms(knowledge, _OBSERVED)
    assert [fam for fam, _sym in matches] == ["platform_lifecycle_change"]

    gated = _gate_lifecycle_symptoms(matches, lifecycle=None)
    assert gated == []

    # An active rollout signal still lets it through ungated.
    still_active = _gate_lifecycle_symptoms(matches, lifecycle={"active": True})
    assert [fam for fam, _sym in still_active] == ["platform_lifecycle_change"]


def test_pinning_the_bug_a_symptom_missing_the_key_is_never_gated() -> None:
    """Documents the exact failure mode this closes: when the key is absent
    (the old graph shape), ``.get()`` is falsy and the gate is a permanent
    no-op, regardless of whether a rollout is actually in progress."""
    matches = [("platform_lifecycle_change", {"symptom": "Mid-Rollout Restart"})]

    gated = _gate_lifecycle_symptoms(matches, lifecycle=None)

    assert gated == matches  # never dropped -- the gate could not see the flag
