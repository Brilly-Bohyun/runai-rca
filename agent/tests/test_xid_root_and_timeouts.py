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


def test_numbered_actions_xid_fix_names_the_fault() -> None:
    # XID 79 is a real knowledge/xid_catalog.yaml entry ("GPU has fallen off
    # the bus", fatal). The bare "(XID 79)" prefix forces an operator to look
    # the code up elsewhere; the identity clause names the fault inline.
    gr = GraphRemediation(xid_fixes={79: ["Reseat or replace the GPU."]})
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
    assert "XID 79 — GPU has fallen off the bus (fatal)" in joined
    assert "Reseat or replace the GPU." in joined


def test_numbered_actions_xid_fix_unknown_code_stays_bare() -> None:
    # A code neither the graph nor the local catalog has a name for must never
    # grow a fabricated or dangling " — " clause.
    gr = GraphRemediation(xid_fixes={999: ["Escalate to NVIDIA support."]})
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
    xid_lines = [a for a in actions if "999" in a]
    assert len(xid_lines) == 1
    assert xid_lines[0].endswith("(XID 999) Escalate to NVIDIA support.")
    assert "—" not in xid_lines[0]


def test_numbered_actions_xid_fix_ko_does_not_leak_english_identity() -> None:
    # knowledge/xid_catalog.yaml carries no Korean mnemonic/description for any
    # code (verified directly against the file): the ko-leak guard must keep
    # the deterministic Korean report free of an English identity clause,
    # exactly like the sibling _xid_diagnostic_guidance_lines site does.
    gr = GraphRemediation(xid_fixes={79: ["GPU를 재장착하거나 교체하세요."]})
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
    xid_lines = [a for a in actions if "79" in a]
    assert len(xid_lines) == 1
    assert xid_lines[0].endswith("(XID 79) GPU를 재장착하거나 교체하세요.")
    assert "GPU has fallen off the bus" not in xid_lines[0]
    assert "—" not in xid_lines[0]
