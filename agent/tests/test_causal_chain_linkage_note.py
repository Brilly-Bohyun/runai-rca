"""pipeline._causal_chain_line surfaces GraphRemediation.xid_linkage_notes (the
driver/CUDA version an escalating XID's leads_to edge was actually CONFIRMED
under, xid_catalog.yaml's `linkage_note`) -- scoped to at most one short clause
per resolved chain, keyed to that chain's causal root. The line's arrow chain
can carry up to 21 codes across unrelated chains (see the commit that added
_xid_identity_clause), so a parenthetical per code was deliberately rejected."""

from __future__ import annotations

from app.services.kg_enrichment import GraphRemediation
from app.services.pipeline import _causal_chain_line


def test_causal_chain_line_names_the_root_escalation_confirmation() -> None:
    gr = GraphRemediation(
        xid_fixes={45: ["fix"], 74: ["reset nvlink"]},
        root_xids={45: [74]},
        xid_linkage_notes={74: "CUDA 12.7; GPU driver R565"},
    )
    line = _causal_chain_line(gr, "en")
    assert "CUDA 12.7; GPU driver R565" in line


def test_causal_chain_line_has_no_note_when_linkage_notes_are_absent() -> None:
    gr = GraphRemediation(xid_fixes={45: ["fix"], 74: ["reset nvlink"]}, root_xids={45: [74]})
    line = _causal_chain_line(gr, "en")
    assert "Escalation confirmed" not in line
    assert "()" not in line
    assert not line.rstrip().endswith(("—", ":"))


def test_causal_chain_line_dedupes_an_identical_note_across_chains() -> None:
    gr = GraphRemediation(
        xid_fixes={45: ["a"], 74: ["b"], 46: ["c"], 75: ["d"]},
        root_xids={45: [74], 46: [75]},
        xid_linkage_notes={74: "CUDA 12.7; GPU driver R565", 75: "CUDA 12.7; GPU driver R565"},
    )
    line = _causal_chain_line(gr, "en")
    assert line.count("CUDA 12.7; GPU driver R565") == 1


def test_causal_chain_line_skips_the_note_for_an_unordered_chain() -> None:
    # No confirmed topological root to key the note to -- must not guess one.
    gr = GraphRemediation(
        xid_fixes={45: ["fix"], 74: ["reset nvlink"]},
        root_xids={45: [74]},
        root_xid_status={45: "complete-but-unordered"},
        xid_linkage_notes={74: "CUDA 12.7; GPU driver R565"},
    )
    line = _causal_chain_line(gr, "en")
    assert "CUDA 12.7" not in line


def test_causal_chain_line_ko_does_not_leak_the_english_linkage_note() -> None:
    # knowledge/xid_catalog.yaml carries no Korean linkage_note: same no-leak
    # guard as the sibling _xid_identity_clause/_numbered_actions sites.
    gr = GraphRemediation(
        xid_fixes={45: ["fix"], 74: ["reset nvlink"]},
        root_xids={45: [74]},
        xid_linkage_notes={74: "CUDA 12.7; GPU driver R565"},
    )
    ko = _causal_chain_line(gr, "ko")
    assert "CUDA 12.7" not in ko
    assert "승격 확인" not in ko  # the label is only emitted alongside content


def test_causal_chain_line_ko_keeps_a_note_that_is_already_korean() -> None:
    gr = GraphRemediation(
        xid_fixes={45: ["fix"], 74: ["reset nvlink"]},
        root_xids={45: [74]},
        xid_linkage_notes={74: "CUDA 12.7; 드라이버 R565에서 확인됨"},
    )
    ko = _causal_chain_line(gr, "ko")
    assert "드라이버 R565에서 확인됨" in ko
