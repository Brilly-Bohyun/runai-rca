"""ontology/incident.py — dead RootCause/blast_radius cleanup (2026-08 audit #3).

`RootCause.blast_radius` was declared, constructed nowhere (grep for
`RootCause(` across the whole repo turned up zero call sites), and the planner
reads a completely different key (`blast_radius_workloads`, computed live by
kg_enrichment). schema.tql's matching `root_cause.blast_radius` attribute is
deleted alongside this dead pydantic field.
"""

from __future__ import annotations

from pathlib import Path

from ontology.incident import OntologyIncident


def test_ontology_incident_has_no_dead_root_cause_field() -> None:
    assert "root_cause" not in OntologyIncident.model_fields
    assert not hasattr(OntologyIncident(incident_id="INC-1"), "root_cause")


def test_root_cause_class_is_gone_not_just_unused() -> None:
    import ontology.incident as incident_module

    assert not hasattr(incident_module, "RootCause")


def test_schema_no_longer_declares_blast_radius() -> None:
    schema = Path("ontology/schema.tql").read_text(encoding="utf-8")
    assert "blast_radius" not in schema
