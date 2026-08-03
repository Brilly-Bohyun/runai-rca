"""Regression coverage for the learned-knowledge wire shape the Go backend
actually emits (backend/internal/server/knowledge.go).

An approved learned package carries BOTH a top-level ``kind`` field
(knowledge.go:911, struct tag at :104) AND the real compiled content under
``compiled.failure_modes`` (built at knowledge.go:631-644) -- ``kind`` is set
alongside the content, never instead of it, and Go never emits a top-level
``entries`` key. The loader used to let the ``kind`` branch unconditionally
overwrite the already-correct content with ``package.get("entries")`` (always
None on a real package), so every learned package failed
``_validate_runtime_failure_modes`` and ``KnowledgeRegistry._snapshot`` was
never assigned -- 100% of approved knowledge was silently rejected.
"""

from __future__ import annotations

import logging

import pytest

from app.knowledge import KnowledgeRegistry, _bundled_probe_template_ids
from tests.test_runtime_knowledge import _Client, _Response


def _go_emitted_package() -> dict[str, object]:
    """One KnowledgePackage exactly as knowledge.go serializes it.

    Mirrors the field set relevant to the agent-side loader: the top-level
    ``kind``/``runtime_status`` written by hydrateKnowledgePackage
    (knowledge.go:897-921) and the ``compiled`` object built for a learned
    failure mode (knowledge.go:623-645).
    """
    known_probe_id = sorted(_bundled_probe_template_ids())[0]
    return {
        "package_id": "KPK-CASE-42",
        "candidate_id": "KNC-CASE-42",
        "case_id": "CASE-42",
        "status": "active",
        "runtime_status": "active",
        "kind": "failure_mode",  # compiledKnowledgeKind(): singular, never "failure_modes"
        "compiled": {
            "failure_modes": [
                {
                    "family": "workload_runtime_error",
                    "symptoms": [
                        {
                            "name": "container runtime restarted after CUDA driver mismatch",
                            "keywords": [
                                "cuda driver mismatch",
                                "container runtime restarted",
                            ],
                            "actions": [
                                "roll back the CUDA driver to the supported version",
                            ],
                        }
                    ],
                }
            ],
            "probe_template_ids": {"workload_runtime_error": [known_probe_id]},
        },
    }


@pytest.mark.asyncio
async def test_registry_loads_learned_package_in_go_wire_shape(monkeypatch) -> None:
    monkeypatch.setattr("app.knowledge.httpx.AsyncClient", _Client)
    _Client.responses = [
        _Response(200, {"revision": "go-shape-1", "packages": [_go_emitted_package()]})
    ]
    _Client.headers = []
    registry = KnowledgeRegistry(mode="assist", snapshot_url="http://backend/snapshot")

    assert await registry.refresh() is True
    assert registry.health()["loaded_revision"] == "go-shape-1"

    catalogs = registry.provisional_catalogs()
    symptom = catalogs["failure_modes"]["workload_runtime_error"][0]
    assert symptom["symptom"] == "container runtime restarted after CUDA driver mismatch"
    assert symptom["keywords"] == ["cuda driver mismatch", "container runtime restarted"]
    assert registry.probe_template_ids_for_family("workload_runtime_error") == [
        sorted(_bundled_probe_template_ids())[0]
    ]

    # This fixture omits name_ko/reason/reason_ko/actions_ko/component/
    # exclusive_actions on purpose: it pins the legacy wire shape (and any
    # future producer that still omits them) so the loader keeps degrading
    # safely -- no crash, and no field silently duplicates the English text
    # under a "_ko" key (that would misreport as a real translation). As of
    # the knowledge.go fix for the missing-localization lead, a *current*
    # Go-compiled learned package DOES populate name_ko/reason/reason_ko
    # (from the analysis_summary headline) and actions_ko (mirrors actions);
    # see TestLearnedPackageCarriesLocalizedNameAndReason in
    # backend/internal/server/knowledge_test.go for that positive case.
    assert symptom["actions_ko"] == []
    assert symptom["symptom_ko"] == ""
    assert symptom["reason"] == ""
    assert symptom["reason_ko"] == ""
    assert symptom["component"] == ""
    assert symptom["exclusive_actions"] is False
    assert catalogs["known_issues"] == []


@pytest.mark.asyncio
async def test_registry_rejects_malformed_package_and_warns_with_id(
    monkeypatch, caplog
) -> None:
    """Validation must stay strict: a genuinely broken package is still
    rejected, and the rejection is logged (not silent) with the package id
    and the reason -- not just accepted because ``kind`` looks plausible.
    """
    monkeypatch.setattr("app.knowledge.httpx.AsyncClient", _Client)
    package = _go_emitted_package()
    package["compiled"]["failure_modes"] = "not-a-list"  # genuinely malformed
    _Client.responses = [_Response(200, {"revision": "bad", "packages": [package]})]
    _Client.headers = []
    registry = KnowledgeRegistry(mode="assist", snapshot_url="http://backend/snapshot")

    with caplog.at_level(logging.WARNING):
        assert await registry.refresh() is False

    assert registry.health()["loaded_revision"] is None
    error = str(registry.health()["last_sync_error"])
    assert "KPK-CASE-42" in error
    assert "failure_modes must be an array or object" in error
    assert "KPK-CASE-42" in caplog.text
    assert "failure_modes must be an array or object" in caplog.text
