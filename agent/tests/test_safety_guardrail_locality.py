"""Locality regression tests for the safety guardrail gate (harness.py).

Bug: ``_unsafe_action_without_guardrail`` scanned *all* text preceding a
dangerous command for a guardrail token. The report builder's own fixed
scaffolding -- the Section-1 "Impact"/"영향" heading, "## 추가 확인 요청",
"- **다음 확인**:", "## 일반 점검 가이드" -- contains generic words that used
to be in the guardrail token set (``impact``, ``확인``, ``영향``, ``점검``),
so the very first heading in any report satisfied the search and the gate
never fired again for the rest of the document. Confirmed on a real
production report: first guardrail-token offset 620 of 4673 chars, gate=False
on 3/3 injected dangerous commands (``kubectl cordon`` / ``kubectl uncordon``).

The fix narrows ``_GUARDRAIL`` to drop those four structural-heading tokens
while keeping genuine safety language (confirm/approval/backup/etc, and the
Korean 승인/백업/유지보수). It deliberately does NOT shrink the search window
to a small local slice: ``apply_safety_guardrail`` prepends one banner at the
very top of the whole report, and ``test_safety_guardrail_covers_a_long_report``
in test_harness.py already relies on that banner covering an action far below
it -- a small window would break that existing, intentional design (see the
"short character window caused repeated repair attempts" comment in
_unsafe_action_without_guardrail, present since the gate's original commit).
"""

from __future__ import annotations

import logging

from app.services.harness import _trace_item, _unsafe_action_without_guardrail


def test_a_far_away_section1_heading_does_not_clear_a_bare_dangerous_action() -> None:
    """Real report shape: a Section-1 Impact heading near the top must not
    retroactively clear a dangerous action far below with no guard of its own."""
    detail = (
        "# Incident Analysis Report — KubeNodeNotReady\n\n"
        "Fired: 2026-07-31T00:00:00Z · Severity: critical · Target: node-7\n\n"
        "## 1. Problem\n\n"
        "- What: node-7 stopped reporting status.\n"
        "- Where: node-7\n"
        "- Impact: recurred 3 times on the same workload\n\n"
        "## 2. Root Cause\n\n"
        + ("Kubelet lost contact with the control plane. " * 40)
        + "\n\n"
        "## 3. Recommended Actions\n\n"
        "1. Cordon the node, then restart the runtime and kubelet: `kubectl cordon node-7`.\n"
    )
    assert _unsafe_action_without_guardrail(detail) is True


def test_b_guardrail_immediately_beside_the_command_clears_the_gate() -> None:
    """A genuinely guarded action must still pass -- narrowing the token set
    must not make the gate fire on every report."""
    detail = (
        "## 3. Recommended Actions\n\n"
        "1. First confirm impact with the on-call team and take a backup, "
        "then run `kubectl cordon node-7`; this has team approval.\n"
    )
    assert _unsafe_action_without_guardrail(detail) is False


def test_c_korean_far_away_heading_does_not_clear_a_bare_dangerous_action() -> None:
    """Korean variant of Test A -- the chart's default language, and the
    widest token set before the fix."""
    detail = (
        "# 장애 분석 보고서 — KubeNodeNotReady\n\n"
        "발생: 2026-07-31T00:00:00Z · 심각도: critical · 대상: node-7\n\n"
        "## 1. 문제 (Problem)\n\n"
        "- 증상: node-7 이 상태 보고를 멈췄습니다.\n"
        "- 위치: node-7\n"
        "- 영향: 같은 워크로드에서 3회 반복 발생\n\n"
        "## 2. 원인 (Root Cause)\n\n"
        + ("커널 로그를 점검하고 상태를 확인했습니다. " * 40)
        + "\n\n"
        "## 추가 확인 요청\n\n- 노드가 언제부터 응답하지 않았는지 확인해 주세요.\n\n"
        "## 3. 권장 조치 (Recommended Actions)\n\n"
        "1. 노드를 격리하려면 다음을 실행하세요: `kubectl cordon node-7`.\n"
    )
    assert _unsafe_action_without_guardrail(detail) is True


def test_c_korean_guardrail_immediately_beside_the_command_clears_the_gate() -> None:
    """Korean variant of Test B."""
    detail = (
        "## 3. 권장 조치 (Recommended Actions)\n\n"
        "1. 먼저 백업을 확인하고 팀의 승인을 받은 뒤 `kubectl cordon node-7` 을 실행하세요.\n"
    )
    assert _unsafe_action_without_guardrail(detail) is False


class _MalformedArtifact:
    """Not an ``AlertAnalysisArtifact`` and not a Mapping: normalize_artifact()
    cannot build a raw dict view of it and raises ``AttributeError`` on ``.get``."""

    evidence_id = "E99"
    source = "loki"
    summary = "malformed artifact"


def test_d_trace_item_warns_on_malformed_artifact(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        trace = _trace_item(_MalformedArtifact())

    # Defaults are unchanged -- silent swallow must stay non-fatal.
    assert trace["polarity"] == "unknown"
    assert trace["coverage"] == "partial"
    # But it must no longer be silent: name the artifact and that it failed.
    assert "E99" in caplog.text
    assert "normaliz" in caplog.text.lower()
    assert any(record.levelno == logging.WARNING for record in caplog.records)
