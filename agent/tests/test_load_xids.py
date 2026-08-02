"""ontology/load_xids.py — linkage_note wiring (2026-08 audit item #3).

xid_catalog.yaml's `linkage_note` (27 entries) was authored and asserted by a
test, but never reached TypeDB: no schema attribute, no loader write, no reader.
This pins the write side; kg_enrichment reads it back via linkage_note_for_xid.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ontology.load_xids import _ensure_xid_linkage_note


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def resolve(self) -> "_Result":
        return self

    def as_concept_rows(self) -> list[object]:
        return self._rows


class _Tx:
    def __init__(self, existing: bool = False) -> None:
        self.queries: list[str] = []
        self._existing = existing

    def query(self, query: str) -> _Result:
        self.queries.append(query)
        if query.startswith("match ") and self._existing:
            return _Result([object()])
        return _Result([])


def test_ensure_xid_linkage_note_writes_when_absent() -> None:
    tx = _Tx(existing=False)

    _ensure_xid_linkage_note(tx, 48, "CUDA 12.7; GPU driver R565")

    assert any(
        q.startswith("match $x isa xid_error, has xid_code 48; ")
        and 'insert $x has linkage_note "CUDA 12.7; GPU driver R565";' in q
        for q in tx.queries
    )


def test_ensure_xid_linkage_note_skips_when_already_present() -> None:
    tx = _Tx(existing=True)

    _ensure_xid_linkage_note(tx, 48, "CUDA 12.7; GPU driver R565")

    assert not any(q.startswith("insert") or "insert $x has linkage_note" in q for q in tx.queries)


def test_ensure_xid_linkage_note_noop_for_blank_note() -> None:
    tx = _Tx()

    _ensure_xid_linkage_note(tx, 48, "")

    assert tx.queries == []


def test_main_wires_linkage_note_into_the_ensure_call() -> None:
    """Static pin: main()'s per-entry loop actually reads the YAML field and
    calls the write helper (a helper nobody calls is exactly last audit's bug)."""
    source = Path("ontology/load_xids.py").read_text(encoding="utf-8")
    assert '_ensure_xid_linkage_note(tx, code, str(entry.get("linkage_note"' in source


def test_catalog_linkage_notes_are_all_non_empty_strings() -> None:
    """Sanity check on the authored data this loader now consumes."""
    data = yaml.safe_load(Path("knowledge/xid_catalog.yaml").read_text(encoding="utf-8"))
    notes = [e["linkage_note"] for e in data["xids"] if e.get("linkage_note")]
    assert len(notes) == 26
    assert all(isinstance(n, str) and n.strip() for n in notes)
