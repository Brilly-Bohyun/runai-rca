"""A Run:ai known issue surfaced through the graph must carry its version
context, matching ontology/load_known_issues.py's own documented contract
("optional reason / affected_version / fixed_version attributes so the
synthesis step can surface 'known issue, affected vX, fixed in vY'").

ontology/load_known_issues.py already writes ``affected_version``/
``fixed_version`` onto the symptom entity (pinned below, unchanged by this
fix). The broken leg was kg_enrichment.py's ``_KNOWLEDGE_QUERY`` family of
queries, which selected only ``$fam, $sn, $kw, $st`` — a known issue mirrored
into the graph's generic symptom/indicates/resolved_by shape (see
ontology/load_known_issues.py's module docstring: "uniform with the curated
failure modes") reached ``KGContext.knowledge`` with no version fields at all.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from app.collectors.base import AnalysisTarget
from app.knowledge import load_runai_known_issues
from app.services.kg_enrichment import _query_kg
from ontology.load_known_issues import _ensure_symptom as _ensure_known_issue_symptom

_ISSUE = "Scheduler Reclaim Panic On Large GPU Job"


def _target() -> AnalysisTarget:
    return AnalysisTarget(
        cluster="", project="", queue="", namespace="", workload_name="",
        workload_type="", runai_workload_id="", node="", pod="",
        severity="warning", alert_name="",
    )


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


def test_known_issues_loader_already_writes_both_version_attributes() -> None:
    """Pins the write leg (unchanged): a regression here would silently starve
    the read-side fix below of anything to select."""
    issues = load_runai_known_issues("knowledge/runai_known_issues.yaml")
    issue = next(i for i in issues if i["issue"] == _ISSUE)
    tx = _FakeTx()

    _ensure_known_issue_symptom(
        tx, issue["issue"], issue["reason"], issue["affected_version"], issue["fixed_version"]
    )

    written = "\n".join(tx.queries)
    assert f'has affected_version "{issue["affected_version"]}"' in written
    assert f'has fixed_version "{issue["fixed_version"]}"' in written


def test_query_kg_now_selects_the_known_issue_version_context() -> None:
    class FakeClient:
        @contextmanager
        def open_reader(self):
            def run(query: str) -> list[dict]:
                if "not {" in query:
                    return []
                if "has keyword $kw" in query:
                    return [
                        {
                            "fam": "platform_version_bug",
                            "sn": _ISSUE,
                            "kw": "reclaim.go",
                            "st": "Upgrade to 2.23+.",
                        }
                    ]
                if "has affected_version $affected_version" in query:
                    return [{"sn": _ISSUE, "affected_version": "<=2.22.43"}]
                if "has fixed_version $fixed_version" in query:
                    return [{"sn": _ISSUE, "fixed_version": "2.23"}]
                return []

            yield run

    knowledge = _query_kg(FakeClient(), _target())["knowledge"]  # type: ignore[arg-type]
    symptom = knowledge["platform_version_bug"][0]

    assert symptom["affected_version"] == "<=2.22.43"
    assert symptom["fixed_version"] == "2.23"
