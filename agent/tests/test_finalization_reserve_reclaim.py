"""The finalization reserve used to pin at a flat 360s (40% of a 900s
deadline) regardless of what finalization actually needed. A real run
measured finalization (rank + self-check + synthesis + harness) at 67.5s
against that 360s floor -- 292.5s reserved but never spent, while evidence
gathering was cut off early with real drill-downs still queued (stop_reason
``analysis_budget_exhausted`` at 605s of a 900s deadline). This proves the
unused reserve was reclaimed for evidence while a genuine floor still holds
finalization's ground.
"""

from dataclasses import replace
from types import SimpleNamespace

from app.services.pipeline import _evidence_deadline_monotonic, _finalization_reserve_seconds
from tests.test_orchestrator import make_settings


def test_the_large_deadline_reserve_no_longer_pins_at_the_old_360s() -> None:
    assert _finalization_reserve_seconds(900) == 150.0
    assert _finalization_reserve_seconds(900) < 360.0


def test_evidence_gets_the_reclaimed_time_on_the_default_900s_deadline() -> None:
    settings = replace(make_settings(), analysis_deadline_seconds=900)
    state = SimpleNamespace(settings=settings, analysis_started_at=100.0)

    # Used to land at 640.0 (100 + 900 - 360); reclaiming the unused reserve
    # pushes evidence's own deadline out by the same 210s finalization gave up.
    assert _evidence_deadline_monotonic(state) == 850.0
    assert _evidence_deadline_monotonic(state) > 640.0


def test_finalization_still_gets_a_genuine_floor_at_a_large_deadline() -> None:
    """Even when evidence gathering is willing to run until the very last
    second, the computed evidence deadline must leave the floor before the
    TRUE analysis deadline -- otherwise a slow-but-legitimate synthesis call
    has no room and gets cut off by the outer orchestrator timeout instead of
    finishing normally."""
    settings = replace(make_settings(), analysis_deadline_seconds=900)
    state = SimpleNamespace(settings=settings, analysis_started_at=0.0)

    evidence_deadline = _evidence_deadline_monotonic(state)

    assert evidence_deadline is not None
    true_deadline = 0.0 + 900
    assert true_deadline - evidence_deadline >= 150.0


def test_short_deadlines_are_unaffected_by_the_reclaim() -> None:
    """Below ~375s, 40% of the deadline was already under the new floor -- the
    short test/operator-deadline behaviour this function documents must not
    move."""
    assert _finalization_reserve_seconds(100) == 40.0
    assert _finalization_reserve_seconds(60) == 30.0
