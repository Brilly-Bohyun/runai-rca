"""R2: our own tooling failure must not become the operator's recommended
incident remediation.

Real run: ``missing_data`` carried "runai.query" because OUR transport failed
(MCP unavailable: self-signed certificate, HTTP 404) -- not a cluster fact --
and "Restore Run:ai API authentication..." was the ONLY action on a
GPU-exhaustion incident. Agent-operability gaps stay visible via
``response.missing_data`` (unchanged: _recommended_action_lines does not
mutate its ``missing`` input) and ``response.warnings`` (populated straight
from each collector's own ``result.warnings`` in enrich_stage, independent of
this function) -- they are just no longer ALSO promoted into "Recommended
Actions", which stays reserved for fixing the cluster problem.
"""

from __future__ import annotations

from app.services.pipeline import _recommended_action_lines


def test_runai_transport_gap_is_not_a_recommended_action() -> None:
    lines = _recommended_action_lines(["runai.query"], None)

    assert lines == []
    assert "Restore Run:ai API authentication" not in " ".join(lines)


def test_runai_auth_gap_is_not_a_recommended_action() -> None:
    assert _recommended_action_lines(["runai.auth"], None) == []


def test_loki_gap_is_not_a_recommended_action() -> None:
    lines = _recommended_action_lines(["loki.query", "loki.auth"], None)

    assert lines == []
    assert "Fix Loki reachability" not in " ".join(lines)


def test_postgres_gap_is_not_a_recommended_action() -> None:
    lines = _recommended_action_lines(["postgres.query", "postgres.connection"], None)

    assert lines == []
    assert "Restore Postgres connectivity" not in " ".join(lines)


def test_missing_data_list_itself_is_untouched() -> None:
    """The gap is not silently dropped -- it stays exactly where it already
    lived (response.missing_data); this function just stops duplicating it."""
    missing = ["runai.query", "loki.auth"]

    _recommended_action_lines(missing, None)

    assert missing == ["runai.query", "loki.auth"]


def test_similar_incident_action_is_unaffected() -> None:
    """Guard against over-correction: a genuine, unrelated action source
    (a proven fix from a similar past incident) still surfaces."""
    from app.schemas import Alert, AlertAnalysisRequest, SimilarIncidentContext

    request = AlertAnalysisRequest(
        alert=Alert(labels={"alertname": "X"}, annotations={}, fingerprint="fp-1"),
        similar_incidents=[
            SimilarIncidentContext(
                incident_id="INC-1",
                similarity=0.99,
                title="prior incident",
                analysis_summary="Raised the queue quota to clear the backlog.",
            )
        ],
    )

    lines = _recommended_action_lines(["runai.query"], request)

    assert any("INC-1" in line for line in lines)
    assert not any("Restore Run:ai API authentication" in line for line in lines)
