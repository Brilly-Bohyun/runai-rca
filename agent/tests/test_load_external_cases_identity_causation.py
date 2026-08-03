"""S4: canonical_component_tokens (exact pod/product names like
gpu-operator, runai-scheduler-default) must never anchor the causal
`indicates` edge. A component name identifies WHO an incident touched, never
WHAT went wrong — _chain_specific's specificity heuristic (multi-word / >=12
chars / code-ish punctuation) can't tell the difference, since identity names
are routinely long and hyphenated and so pass it anyway. The loader must
exclude them by PROVENANCE (they came from canonical_component_tokens), not
by re-guessing identity back from the string's shape. They stay legitimate
for RETRIEVAL: a demoted (non-chain) case keeps its full keyword set,
including the identity tokens, so it is still findable."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ontology import ingest
from ontology import load_external_cases as lx


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


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "payload_schema_version": "2.0",
        "payload_kind": "historical_incident_candidate",
        "identity": {
            "source_system": "enterprise_support",
            "deduplication_key": "enterprise_support:c0ffee00",
            "source_revision_hash": "sha256:x",
        },
        "approval": {"curation_decision": "approved_for_ingestion"},
        "incident": {
            "title": "NodeFilesystemAlmostOutOfSpace",
            "masked_summary": "node-exporter pod is almost out of disk",
            "status": "resolved",
            "family": "observability_accuracy",
            "family_confidence": "medium",
            "confirmed_mechanism": "exporter disk-write bug filled the volume",
        },
        "searchable_context": {
            "error_signatures": [],
            "canonical_component_tokens": ["prometheus-node-exporter", "gpu-operator"],
        },
        "evidence_refs": [],
        "historical_actions": [],
        "historical_use": {
            "context_class": "evaluation_only",
            "allowed_uses": [],
            "prohibited_uses": [],
        },
    }
    base.update(overrides)
    return base


def test_component_identity_tokens_never_anchor_the_causal_chain(monkeypatch: Any) -> None:
    # NodeFilesystemAlmostOutOfSpace{pod=prometheus-node-exporter-x9k2l}: the
    # labels name the exporter, not the fault. A case whose ONLY signatures
    # are component-identity tokens must demote to retrieval-only, not
    # headline observability_accuracy for every alert naming that component.
    monkeypatch.setattr(
        ingest,
        "load_family_catalog",
        lambda _: SimpleNamespace(families={"observability_accuracy"}),
    )
    p = _payload()
    inc = lx._to_incident(p, "op", "t")
    keywords = lx._symptom_keywords(p)
    identity = lx._component_identity_tokens(p)
    assert identity == {"prometheus-node-exporter", "gpu-operator"}

    tx = _Tx()
    lx._write_case(tx, inc, keywords, identity)
    emitted = "\n".join(tx.queries)
    assert "insert (symptom: $s, cause: $rc) isa indicates" not in emitted
    # Retrieval concern is separate from causation: the demoted case keeps
    # its full keyword set, so an alert naming this pod/namespace can still
    # find the case as a labelled prior.
    assert 'has keyword "gpu-operator"' in emitted
    assert 'has keyword "prometheus-node-exporter"' in emitted


def test_identity_tokens_excluded_even_alongside_a_genuine_signature(monkeypatch: Any) -> None:
    """Over-correction guard: a genuine error-signature keyword from an
    external case must still reach the chain. The fix targets identity
    tokens specifically — it must not also blind chain_keywords to a real,
    specific signature sitting right next to one."""
    monkeypatch.setattr(
        ingest,
        "load_family_catalog",
        lambda _: SimpleNamespace(families={"network_fabric_error"}),
    )
    p = _payload(
        incident={
            "title": "RoCE link failure",
            "masked_summary": "fabric link down",
            "status": "resolved",
            "family": "network_fabric_error",
            "family_confidence": "high",
            "confirmed_mechanism": "switch port flapped",
        },
        searchable_context={
            "error_signatures": ["watchdog caught collective operation timeout"],
            "canonical_component_tokens": ["nvidia-fabricmanager"],
        },
    )
    inc = lx._to_incident(p, "op", "t")
    keywords = lx._symptom_keywords(p)
    identity = lx._component_identity_tokens(p)
    assert "nvidia-fabricmanager" in keywords  # still present for retrieval
    assert identity == {"nvidia-fabricmanager"}

    tx = _Tx()
    lx._write_case(tx, inc, keywords, identity)
    emitted = "\n".join(tx.queries)
    assert "insert (symptom: $s, cause: $rc) isa indicates" in emitted
    assert 'has keyword "watchdog caught collective operation timeout"' in emitted
    # The identity token rides on the SAME symptom entity as the causal
    # keyword, so once the chain is anchored it cannot also carry the
    # identity token (a single indicates edge can't be "half causal").
    assert 'has keyword "nvidia-fabricmanager"' not in emitted


def test_write_case_defaults_to_no_identity_tokens(monkeypatch: Any) -> None:
    """Backward compatibility: existing/legacy callers that don't pass
    identity_tokens (the 3-argument call) must keep working exactly as
    before — this fix only ever narrows what a NEW 4th argument gates."""
    monkeypatch.setattr(
        ingest,
        "load_family_catalog",
        lambda _: SimpleNamespace(families={"network_fabric_error"}),
    )
    p = _payload(
        incident={
            "title": "RoCE link failure",
            "masked_summary": "fabric link down",
            "status": "resolved",
            "family": "network_fabric_error",
            "family_confidence": "high",
            "confirmed_mechanism": "switch port flapped",
        },
        searchable_context={
            "error_signatures": ["watchdog caught collective operation timeout"],
        },
    )
    inc = lx._to_incident(p, "op", "t")
    tx = _Tx()
    lx._write_case(tx, inc, lx._symptom_keywords(p))  # no identity_tokens arg
    assert "insert (symptom: $s, cause: $rc) isa indicates" in "\n".join(tx.queries)
