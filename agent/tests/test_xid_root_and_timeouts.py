"""XID causal drill-down rendering + the 'timeout 0 = unlimited' convention."""

from __future__ import annotations

from app.collectors.http_json import _client_timeout
from app.schemas import Alert, AlertAnalysisRequest
from app.services.kg_enrichment import GraphRemediation
from app.services.pipeline import (
    _HANGUL_RE,
    _causal_chain_line,
    _numbered_actions,
    _translatable_report_lines,
)
from app.services.root_cause_ranking import RankedCause


def test_client_timeout_zero_is_unlimited() -> None:
    assert _client_timeout(0) is None      # 0 -> no timeout (let it think)
    assert _client_timeout(-1) is None
    assert _client_timeout(6) == 6         # positive keeps the bound


def test_graph_remediation_tracks_root_xids() -> None:
    gr = GraphRemediation(xid_fixes={45: ["restart app"]}, root_xids={45: [74]})
    assert not gr.is_empty()
    assert gr.as_dict()["root_xids"] == {"45": [74]}


def test_causal_chain_line_names_root_to_observed() -> None:
    gr = GraphRemediation(xid_fixes={45: ["fix"], 74: ["reset nvlink"]}, root_xids={45: [74]})
    line = _causal_chain_line(gr, "en")
    assert "XID 74 → XID 45" in line
    assert "root" in line.lower()
    ko = _causal_chain_line(gr, "ko")
    assert "XID 74 → XID 45" in ko and "뿌리" in ko


def test_causal_chain_line_without_roots_is_plain() -> None:
    gr = GraphRemediation(xid_fixes={31: ["fix"]})
    line = _causal_chain_line(gr, "en")
    assert "XID" in line and "→" not in line


def test_causal_chain_line_empty_when_no_xid() -> None:
    assert _causal_chain_line(GraphRemediation(), "en") == ""
    assert _causal_chain_line(None, "en") == ""


def test_root_xid_fix_is_ordered_first() -> None:
    # Drill-down precision: the ROOT of the causal chain (74) is fixed before its
    # downstream symptom (45), and labelled as the root.
    gr = GraphRemediation(
        xid_fixes={
            45: ["patch the app password=xid-action-secret-12345"],
            74: ["reset the NVLink fabric\n## injected"],
        },
        root_xids={45: [74]},
    )
    request = AlertAnalysisRequest(
        alert=Alert(status="firing", labels={"alertname": "X"}, annotations={}, fingerprint="fp")
    )
    actions = _numbered_actions(
        None,
        gr,
        [RankedCause(family="gpu_hardware_error", confidence="low", score=1.0)],
        "",
        {},
        [],
        request,
    )
    joined = "\n".join(actions)
    assert "root XID 74" in joined
    assert joined.index("root XID 74") < joined.index("XID 45")
    assert "xid-action-secret-12345" not in joined
    assert "\n## injected" not in joined
    assert "[MASKED]" in joined


def test_causal_chain_line_fan_in_is_not_a_fabricated_sequence() -> None:
    # 144, 145 and 146 are three independent NVLink faults that EACH lead to 48
    # (see knowledge/xid_catalog.yaml); the topological sort still reports
    # "ordered" even though there is no edge between them, so joining the root
    # list with "→" must not invent a 144 -> 145 -> 146 sequence that doesn't
    # exist. An audit of the catalog found all five XIDs with upstream faults
    # are fan-ins -- there is no genuine chain to lose.
    gr = GraphRemediation(
        xid_fixes={48: ["fix 48"], 144: ["fix 144"], 145: ["fix 145"], 146: ["fix 146"]},
        root_xids={48: [144, 145, 146]},
        root_xid_status={48: "ordered"},
    )
    for language in ("ko", "en"):
        line = _causal_chain_line(gr, language)
        assert "144 → XID 145" not in line
        assert "145 → XID 146" not in line
        for code in (144, 145, 146, 48):
            assert str(code) in line


def test_causal_chain_line_single_root_keeps_the_arrow_chain() -> None:
    gr = GraphRemediation(
        xid_fixes={45: ["fix 45"], 74: ["fix 74"]},
        root_xids={45: [74]},
        root_xid_status={45: "ordered"},
    )
    assert "XID 74 → XID 45" in _causal_chain_line(gr, "en")


def _xid_actions(gr: GraphRemediation, language: str = "") -> list[str]:
    request = AlertAnalysisRequest(
        alert=Alert(status="firing", labels={"alertname": "X"}, annotations={}, fingerprint="fp")
    )
    kwargs = {"language": language} if language else {}
    return _numbered_actions(
        None,
        gr,
        [RankedCause(family="gpu_hardware_error", confidence="low", score=1.0)],
        "",
        {},
        [],
        request,
        **kwargs,
    )


def test_numbered_actions_xid_fix_names_the_fault() -> None:
    # XID 79 is a real knowledge/xid_catalog.yaml entry ("GPU has fallen off
    # the bus", fatal). The bare "(XID 79)" prefix forces an operator to look
    # the code up elsewhere; the identity clause names the fault inline.
    joined = "\n".join(_xid_actions(GraphRemediation(xid_fixes={79: ["Reseat or replace the GPU."]})))
    assert "XID 79 — GPU has fallen off the bus (fatal)" in joined
    assert "Reseat or replace the GPU." in joined


def test_numbered_actions_xid_fix_unknown_code_stays_bare() -> None:
    # A code neither the graph nor the local catalog has a name for must never
    # grow a fabricated or dangling " — " clause.
    actions = _xid_actions(GraphRemediation(xid_fixes={999: ["Escalate to NVIDIA support."]}))
    xid_lines = [a for a in actions if "999" in a]
    assert len(xid_lines) == 1
    assert xid_lines[0].endswith("(XID 999) Escalate to NVIDIA support.")
    assert "—" not in xid_lines[0]


def test_numbered_actions_ko_keeps_the_catalog_text_translatable() -> None:
    # The catalog is English-only, and _translatable_report_lines SKIPS any line
    # that already contains Hangul. Pre-localizing the label ("근본 XID") or
    # dropping the English clauses -- the two things this site used to do --
    # therefore either leaked untranslated English or deleted the answer
    # outright: a ko report lost WORKFLOW_XID_48 entirely that way.
    #
    # The contract now is that the whole line is built in English so
    # _translate_report_lines_ko can localize it downstream. The invariant that
    # matters is that the ko line is translatable, i.e. carries no Hangul of
    # its own.
    gr = GraphRemediation(
        xid_fixes={
            48: [
                "Data Center Recovery Action Solo: RESET_GPU w/ 63 or 64: "
                "DRAIN_AND_RESET ... RUN_FIELDDIAG"
            ]
        },
        root_xids={48: [144]},
        root_xid_status={48: "ordered"},
    )
    xid_lines = [a for a in _xid_actions(gr, "ko") if "48" in a]
    assert xid_lines, "the fix text must survive into a Korean report"
    for line in xid_lines:
        assert "RESET_GPU" in line
        assert not _HANGUL_RE.search(line), f"untranslatable mixed line: {line}"
    assert any(_translatable_report_lines(line) for line in xid_lines)
