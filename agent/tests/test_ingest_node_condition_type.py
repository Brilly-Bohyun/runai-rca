"""ontology/ingest.py — node.condition_type fill (2026-08 audit item #3).

schema.tql declared `node owns condition_type` since the infra-layer
simplification, but nothing ever wrote it even though node conditions ARE
observed every run (collectors/kubernetes.py._node_condition_artifacts) — so
"past incidents on nodes with MemoryPressure" was unanswerable. This pins the
write; kg_enrichment's existing location_history query now returns real values
for it instead of silently omitting the column.
"""

from __future__ import annotations

from typing import Any

from ontology import ingest
from ontology.incident import OntologyIncident


def _condition_artifact(condition: str, polarity: str) -> dict[str, Any]:
    return {
        "type": "kubernetes_node_condition",
        "result": {
            "node": "gpu-node-1",
            "condition": condition,
            "status": "True" if polarity == "present" else "Unknown",
            "observation": {
                "kind": "kubernetes_node_condition",
                "predicate": f"kubernetes_node_condition:{condition.casefold()}",
                "polarity": polarity,
                "observed_entity": {"kind": "node", "name": "gpu-node-1"},
            },
        },
    }


def test_node_condition_type_returns_the_present_condition() -> None:
    inc = OntologyIncident(incident_id="INC-1", node="gpu-node-1", artifacts=[
        _condition_artifact("MemoryPressure", "present"),
    ])
    assert ingest._node_condition_type(inc) == "MemoryPressure"


def test_node_condition_type_ignores_non_present_polarity() -> None:
    """unknown/absent means the condition was inspected but not confirmed true
    — never a fact worth attaching to the node."""
    inc = OntologyIncident(incident_id="INC-1", node="gpu-node-1", artifacts=[
        _condition_artifact("DiskPressure", "unknown"),
        _condition_artifact("PIDPressure", "absent"),
    ])
    assert ingest._node_condition_type(inc) == ""


def test_node_condition_type_ignores_other_artifact_types() -> None:
    inc = OntologyIncident(incident_id="INC-1", node="gpu-node-1", artifacts=[
        {"type": "workload_topology", "result": {"condition": "MemoryPressure"}},
    ])
    assert ingest._node_condition_type(inc) == ""


def test_node_condition_type_empty_without_artifacts() -> None:
    assert ingest._node_condition_type(OntologyIncident(incident_id="INC-1")) == ""


class _Result:
    def resolve(self) -> "_Result":
        return self

    def as_concept_rows(self) -> list[Any]:
        return []


class _Tx:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def query(self, query: str) -> _Result:
        self.queries.append(query)
        return _Result()


def test_write_incident_stamps_the_observed_node_condition() -> None:
    tx = _Tx()
    inc = OntologyIncident(
        incident_id="INC-1",
        node="gpu-node-1",
        cluster="prod-a",
        artifacts=[_condition_artifact("MemoryPressure", "present")],
    )

    ingest._write_incident(tx, inc)

    emitted = "\n".join(tx.queries)
    assert 'insert $x has condition_type "MemoryPressure";' in emitted


def test_write_incident_writes_no_condition_type_when_none_observed() -> None:
    tx = _Tx()
    inc = OntologyIncident(incident_id="INC-1", node="gpu-node-1", cluster="prod-a")

    ingest._write_incident(tx, inc)

    assert not any("condition_type" in q for q in tx.queries)
