"""XID causal drill-down rendering + the 'timeout 0 = unlimited' convention."""

from __future__ import annotations

from app.collectors.http_json import _client_timeout
from app.schemas import Alert, AlertAnalysisRequest
from app.services.kg_enrichment import GraphRemediation
from app.services.pipeline import _causal_chain_line, _numbered_actions
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
    # exist.
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


def test_numbered_actions_keeps_english_xid_fix_in_korean_report() -> None:
    # Bug: a Korean-only filter dropped every XID fix because TypeDB's
    # graph-remediation text has no locale field and is always English. Report-
    # line translation (_translate_report_lines_ko) runs downstream over the
    # whole assembled report, so _numbered_actions must not filter these out by
    # language -- doing so silently deleted the answer to the operator's
    # question.
    gr = GraphRemediation(
        xid_fixes={
            48: [
                "Data Center Recovery Action Solo: RESET_GPU w/ 63 or 64: "
                "DRAIN_AND_RESET ... RUN_FIELDDIAG"
            ]
        }
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
        language="ko",
    )
    joined = "\n".join(actions)
    assert "RESET_GPU" in joined
