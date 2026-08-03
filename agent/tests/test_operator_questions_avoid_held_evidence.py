"""R4: the operator must never be asked for something an eligible artifact
already answers.

Real run: the operator was asked for kube-scheduler logs (already held as
E113) and per-node GPU usage (already held as E01: "gpu_capacity 8 /
gpu_requested 8"), because ``_operator_questions`` saw only the executed
QUERY strings, never what they returned.
"""

from __future__ import annotations

import pytest

from app.collectors.base import AnalysisTarget, artifact
from app.services.pipeline import (
    _already_answered,
    _held_evidence_summaries,
    _operator_questions,
)
from tests.test_orchestrator import make_settings


def _target() -> AnalysisTarget:
    return AnalysisTarget(
        cluster="", project="", queue="", namespace="runai-test1", workload_name="trainer",
        workload_type="Training", runai_workload_id="", node="", pod="trainer-0",
        severity="warning", alert_name="X",
    )


# --- _already_answered: the matching heuristic --------------------------------


def test_kube_scheduler_logs_ask_is_recognized_as_already_held() -> None:
    held = "E113: kube-scheduler logs show 3 preemption events for pod trainer-0"
    question = "Check the kube-scheduler logs for preemption events."

    assert _already_answered(question, held) is True


def test_unrelated_generic_question_is_not_flagged() -> None:
    """Guard against over-correction: a generic connectivity question must
    survive even with unrelated held evidence present."""
    held = "E113: kube-scheduler logs show 3 preemption events for pod trainer-0"
    question = "Is the agent's Kubernetes service-account token valid?"

    assert _already_answered(question, held) is False


def test_empty_held_text_never_flags_anything() -> None:
    assert _already_answered("Check the kube-scheduler logs.", "") is False


# --- _held_evidence_summaries: only ELIGIBLE artifacts count ------------------


def test_held_evidence_summaries_include_only_eligible_artifacts() -> None:
    scoped_present = {"observation": {"polarity": "present", "coverage": "scoped"}}
    eligible = artifact(
        agent="prometheus", source="prometheus", type="metric", status="ok",
        confidence="high", summary="gpu_capacity 8 / gpu_requested 8", result=scoped_present,
    )
    eligible.evidence_id = "E01"
    ineligible = artifact(
        agent="prometheus", source="prometheus", type="metric", status="ok",
        confidence="low", summary="unrelated out-of-window reading", result=scoped_present,
    )
    ineligible.evidence_id = "E02"

    summaries = _held_evidence_summaries([eligible, ineligible], {"E01"})

    assert summaries == ["E01: gpu_capacity 8 / gpu_requested 8"]


# --- _operator_questions: the end-to-end filter --------------------------------


@pytest.mark.asyncio
async def test_operator_questions_drops_a_next_check_the_board_already_answers() -> None:
    settings = make_settings()  # no LLM configured -> deterministic path only
    questions = await _operator_questions(
        settings,
        [],
        None,
        _target(),
        "Check the kube-scheduler logs for preemption events.",
        [],
        ["E113: kube-scheduler logs show 3 preemption events for pod trainer-0"],
    )

    assert not any("kube-scheduler logs" in q for q in questions)


@pytest.mark.asyncio
async def test_operator_questions_keeps_a_next_check_nothing_answers() -> None:
    """Guard against over-correction: with no held evidence, the next_check
    still surfaces as before."""
    settings = make_settings()
    questions = await _operator_questions(
        settings, [], None, _target(), "Check the kube-scheduler logs for preemption events.", [], []
    )

    assert any("kube-scheduler logs" in q for q in questions)
