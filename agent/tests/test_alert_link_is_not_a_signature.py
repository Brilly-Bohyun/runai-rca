"""A runbook link is where to READ about an alert, not an observation of it."""

from app.schemas import Alert, AlertAnalysisRequest
from app.services.pipeline import _alert_text

RUNBOOK = "https://runbooks.prometheus-operator.dev/runbooks/kubernetes/kubepodnotready"


def _request(annotations: dict[str, str], labels: dict[str, str] | None = None):
    return AlertAnalysisRequest(
        alert=Alert(
            status="firing",
            labels=labels or {"alertname": "KubePodNotReady", "namespace": "runai-test1"},
            annotations=annotations,
            startsAt="2026-07-31T04:30:37Z",
        )
    )


def test_the_standard_runbook_url_carries_no_matchable_keyword() -> None:
    """INC-…-000001: this URL alone promoted observability_accuracy to 7.0."""
    text = _alert_text(
        _request(
            {
                "summary": "Pod has been in a non-ready state for more than 15 minutes.",
                "runbook_url": RUNBOOK,
            }
        )
    )

    assert "prometheus-operator" not in text
    assert "non-ready state" in text


def test_a_link_embedded_in_prose_is_stripped_but_the_prose_survives() -> None:
    text = _alert_text(
        _request({"description": f"Pod runai-test1/frac-test2-0-0 is pending, see {RUNBOOK}"})
    )

    assert "prometheus-operator" not in text
    assert "frac-test2-0-0 is pending" in text


def test_a_real_signature_in_the_alert_still_reaches_the_matcher() -> None:
    """The whole point of reading alert text: XID lives there and nowhere else."""
    text = _alert_text(
        _request(
            {
                "description": "NVIDIA XID 79: GPU has fallen off the bus",
                "runbook_url": RUNBOOK,
            }
        )
    )

    assert "xid 79" in text.casefold()
    assert "fallen off the bus" in text


def test_labels_are_untouched() -> None:
    text = _alert_text(
        _request({"summary": "s"}, {"alertname": "KubePodNotReady", "pod": "frac-test2-0-0"})
    )

    assert "frac-test2-0-0" in text
    assert "KubePodNotReady" in text


def test_operator_prompt_is_not_a_signature() -> None:
    """S1: the operator's own chat speculation must steer investigation ORDER,
    never PROMOTE a cause -- it must not reach the signature-matching text at
    all, same as a runbook_url."""
    text = _alert_text(
        _request(
            {
                "summary": "Pod has been in a non-ready state for more than 15 minutes.",
                "operator_prompt": "혹시 CoreDNS 문제일까요?",
            }
        )
    )

    assert "CoreDNS" not in text
    assert "non-ready state" in text


def test_operator_prompt_label_is_also_excluded() -> None:
    # The field filter applies to labels too, not just annotations -- the
    # non-evidence field can arrive on either side of the alert payload.
    text = _alert_text(
        _request(
            {"summary": "s"},
            {"alertname": "KubePodNotReady", "operator_prompt": "CoreDNS 문제일까요?"},
        )
    )

    assert "CoreDNS" not in text
    assert "KubePodNotReady" in text
