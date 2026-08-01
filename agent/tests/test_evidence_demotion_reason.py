"""C10: the collector's own demotion diagnosis must survive into the fact.

Every collector already decides WHY a result cannot be trusted as
present+scoped and records one of a known set of verification flags on its
own ``observation`` dict (app/collectors/*.py) -- ``target_scope_verified``,
``source_verified``, ``time_scope_verified``/``log_window_verified``/
``sample_window_verified``, ``current_state_only``, etc. Before this change
``EvidenceFact.prompt_dict`` projected only predicate/polarity/coverage/
entity/window/summary/highlights, so that diagnosis died at the blackboard:
a run with 121 artifacts and 2 eligible could only say "insufficient
evidence", never "prometheus returned N series but the sample window was
never verified".

These tests pin ``EvidenceFact.demotion_reason`` -- a compact,
machine-readable label derived from that dying diagnosis -- against the real
observation shapes each collector produces (confirmed by reading
app/collectors/{loki,prometheus,kubernetes,runai,system,postgres}.py), plus
the blackboard's own normalization gates (untyped artifact, malformed window,
unnamed/malformed entity).
"""

from __future__ import annotations

from app.collectors.base import artifact
from app.services.evidence_blackboard import normalize_artifact


def _typed(observation: dict, **kwargs) -> dict:
    """An artifact shaped like a collector's own typed-observation result."""
    return artifact(
        agent=kwargs.pop("agent", "loki"),
        source=kwargs.pop("source", "loki"),
        type=kwargs.pop("type", "loki_query"),
        status=kwargs.pop("status", "ok"),
        confidence=kwargs.pop("confidence", "low"),
        summary=kwargs.pop("summary", "x"),
        result={"observation": observation},
        **kwargs,
    ).model_dump()


def test_present_scoped_fact_carries_no_demotion_reason() -> None:
    fact = normalize_artifact(
        _typed(
            {
                "polarity": "present",
                "coverage": "scoped",
                "observed_entity": "pod:trainer-0",
                "line_count": 5,
                "affirmative_line_count": 5,
            }
        ),
        require_typed_observation=True,
    )
    assert fact.polarity == "present" and fact.coverage == "scoped"
    assert fact.demotion_reason == ""


def test_loki_unproven_target_scope_is_named() -> None:
    """The task's own example: 'loki had 20 lines but could not prove which pod'."""
    fact = normalize_artifact(
        _typed({"polarity": "unknown", "coverage": "partial", "line_count": 20, "target_scope_verified": False}),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "target_scope_unverified"


def test_loki_matched_lines_that_never_affirm_a_failure_is_named() -> None:
    """loki.py: the broad token matcher also returns 'no OOM' / 'OOMKilled=false'."""
    fact = normalize_artifact(
        _typed({"polarity": "unknown", "coverage": "partial", "line_count": 5, "affirmative_line_count": 0}),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "matched_lines_not_affirmative"


def test_prometheus_unverified_sample_window_is_named() -> None:
    """The task's own example: 'prometheus returned 75 series but the first sample was early'."""
    fact = normalize_artifact(
        _typed(
            {"polarity": "unknown", "coverage": "partial", "series_count": 75, "sample_window_verified": False},
            agent="prometheus",
            source="prometheus",
            type="prometheus_query",
        ),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "window_unverified"


def test_kubernetes_log_unverified_source_is_named() -> None:
    fact = normalize_artifact(
        _typed(
            {
                "polarity": "unknown",
                "coverage": "partial",
                "source_verified": False,
                "time_scope_verified": True,
            },
            agent="kubernetes",
            source="kubernetes",
            type="kubernetes_pod_log",
        ),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "source_unverified"


def test_kubernetes_log_unverified_time_scope_is_named() -> None:
    fact = normalize_artifact(
        _typed(
            {
                "polarity": "unknown",
                "coverage": "partial",
                "source_verified": True,
                "time_scope_verified": False,
            },
            agent="kubernetes",
            source="kubernetes",
            type="kubernetes_pod_log",
        ),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "window_unverified"


def test_kubernetes_ambiguous_pod_identity_is_named() -> None:
    fact = normalize_artifact(
        _typed(
            {"polarity": "unknown", "coverage": "partial", "target_identity_ambiguous": True},
            agent="kubernetes",
            source="kubernetes",
            type="kubernetes_warning_events",
        ),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "target_identity_ambiguous"


def test_kubernetes_incomplete_event_queries_is_named() -> None:
    fact = normalize_artifact(
        _typed(
            {"polarity": "unknown", "coverage": "partial", "queries_complete": False},
            agent="kubernetes",
            source="kubernetes",
            type="kubernetes_warning_events",
        ),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "queries_incomplete"


def test_kubernetes_snapshot_role_current_context_is_named() -> None:
    """kubernetes.py node condition / cordon / PVC observations: a live
    snapshot taken while replaying a resolved incident is current state, not
    the historical incident state."""
    fact = normalize_artifact(
        _typed(
            {"polarity": "unknown", "coverage": "partial", "snapshot_role": "current_context"},
            agent="kubernetes",
            source="kubernetes",
            type="kubernetes_node_condition",
        ),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "current_state_only"


def test_runai_current_state_only_is_named() -> None:
    fact = normalize_artifact(
        _typed(
            {"polarity": "unknown", "coverage": "partial", "current_state_only": True},
            agent="runai",
            source="runai",
            type="runai_api_query",
        ),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "current_state_only"


def test_runai_current_state_absent_is_named() -> None:
    """A direct 404 for an already-resolved alert: current absence, not proof
    the resource was absent at incident time (app.collectors.runai)."""
    fact = normalize_artifact(
        _typed(
            {"polarity": "unknown", "coverage": "partial", "current_state_absent": True},
            agent="runai",
            source="runai",
            type="runai_api_query",
        ),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "current_state_only"


def test_system_log_not_historical_scope_is_named() -> None:
    fact = normalize_artifact(
        _typed(
            {"polarity": "present", "coverage": "partial", "historical_scope": False},
            agent="system",
            source="system",
            type="system_log_query",
        ),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "not_historical_scope"


def test_postgres_naive_timestamp_caveat_is_named_when_nothing_else_explains_it() -> None:
    fact = normalize_artifact(
        _typed(
            {"polarity": "unknown", "coverage": "partial", "naive_timestamps_assumed_utc": True},
            agent="postgres",
            source="postgres",
            type="postgres_incident_history",
        ),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "naive_timestamp_assumed_utc"


def test_a_more_specific_collector_flag_outranks_the_naive_timestamp_caveat() -> None:
    """naive_timestamps_assumed_utc is a co-occurring caveat, not a hard
    rejection by itself (a row can still verify with an assumed-UTC time) --
    it must not shadow a real, more specific rejection reason."""
    fact = normalize_artifact(
        _typed(
            {
                "polarity": "unknown",
                "coverage": "partial",
                "naive_timestamps_assumed_utc": True,
                "target_scope_verified": False,
            }
        ),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "target_scope_unverified"


def test_untyped_legacy_artifact_is_named_instead_of_guessing_a_collector_flag() -> None:
    """No adapter opted into a typed observation contract at all: sql_select,
    k8s_read/describe/exec, and all 14 runai_* generic tools stay this way
    (see app.services.drilldown._typed_artifact_result)."""
    raw = artifact(
        agent="runai",
        source="runai",
        type="runai_api_query",
        status="ok",
        confidence="low",
        summary="some free-text summary that happens to mention a failure",
        result={"raw_body": {"foo": "bar"}},
    ).model_dump()

    fact = normalize_artifact(raw, require_typed_observation=True)

    assert fact.demotion_reason == "untyped_observation"


def test_malformed_declared_window_is_named_not_confused_with_a_collector_flag() -> None:
    raw = artifact(
        agent="loki",
        source="loki",
        type="loki_query",
        status="ok",
        confidence="low",
        summary="x",
        result={
            "observation": {
                "polarity": "present",
                "coverage": "scoped",
                "observed_window_start": "not-a-timestamp",
                "observed_window_end": "also-not-a-timestamp",
            }
        },
    ).model_dump()

    fact = normalize_artifact(raw, require_typed_observation=True)

    assert fact.demotion_reason == "malformed_scope"


def test_malformed_entity_is_named() -> None:
    raw = artifact(
        agent="loki",
        source="loki",
        type="loki_query",
        status="ok",
        confidence="low",
        summary="x",
        result={
            "observation": {
                "polarity": "present",
                "coverage": "scoped",
                # A Mapping entity with neither kind nor name cannot resolve.
                "observed_entity": {"namespace": "runai-test1"},
            }
        },
    ).model_dump()

    fact = normalize_artifact(raw, require_typed_observation=True)

    assert fact.demotion_reason == "malformed_entity"


def test_typed_present_scoped_verdict_that_never_names_an_entity_is_named() -> None:
    """The blackboard's own gate (evidence_blackboard.py): a collector proved
    present+scoped but never said WHAT it observed."""
    raw = artifact(
        agent="loki",
        source="loki",
        type="loki_query",
        status="ok",
        confidence="low",
        summary="x",
        result={"observation": {"polarity": "present", "coverage": "scoped"}},
    ).model_dump()

    fact = normalize_artifact(raw, require_typed_observation=True)

    assert fact.demotion_reason == "entity_not_named"


def test_unavailable_source_falls_back_to_a_generic_reason() -> None:
    raw = artifact(
        agent="loki",
        source="loki",
        type="loki_query",
        status="unavailable",
        confidence="low",
        summary="Loki transport failed",
        result=None,
    ).model_dump()

    fact = normalize_artifact(raw, require_typed_observation=True)

    assert fact.polarity == "unavailable"
    assert fact.demotion_reason == "source_unavailable"


def test_demotion_reason_is_bounded_and_excluded_from_the_prompt_projection() -> None:
    """C10 is explicit: the LLM projection must stay query-free and small.
    ``demotion_reason`` is for the harness/pipeline layer (see the
    ``normalize_artifact`` docstring reference), never the prompt."""
    fact = normalize_artifact(
        _typed({"polarity": "unknown", "coverage": "partial", "target_scope_verified": False}),
        require_typed_observation=True,
    )
    assert fact.demotion_reason == "target_scope_unverified"
    assert "demotion_reason" not in fact.prompt_dict()


def test_demotion_reason_is_not_part_of_fact_identity() -> None:
    """Two artifacts whose only difference is which flag the collector used
    to explain an identical unknown/partial verdict must still collapse to
    the same fact -- the reason is a label, not an observation."""
    first = normalize_artifact(
        _typed({"polarity": "unknown", "coverage": "partial", "target_scope_verified": False}),
        require_typed_observation=True,
    )
    second = normalize_artifact(
        _typed({"polarity": "unknown", "coverage": "partial", "source_verified": False}),
        require_typed_observation=True,
    )
    assert first.fact_id == second.fact_id
    assert first.demotion_reason != second.demotion_reason
