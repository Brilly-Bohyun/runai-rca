"""A runbook link is where to READ about an alert, not an observation of it --
and neither is an operator's own chat speculation.

The boundary: ``_alert_text`` is deliberately permissive (it feeds
investigation ORDER -- component identification, fuzzy recall, the
non-diagnostic general-guidance block). ``_alert_signature_text`` is the
narrower sibling that feeds anything able to PROMOTE a cause (state.observed
via ``_observed_text``, XID extraction, self-check's declared-alert, and the
actions/playbook/knowledge-base fuzzy recall that can render a matched
symptom's actions straight into the report). A fix once collapsed that
boundary by filtering non-evidence fields out of ``_alert_text`` itself,
which also blinded every guidance consumer to the operator's own words --
see both functions' docstrings in app/services/pipeline.py.
"""

from app.schemas import Alert, AlertAnalysisRequest
from app.services.pipeline import _alert_signature_text, _alert_text, _observed_text

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
    """INC-…-000001: this URL alone promoted observability_accuracy to 7.0.

    A bare link is not a signal on either path -- guidance has no more use for
    a doc host name than the matcher does -- so both drop it and keep the
    surrounding prose.
    """
    request = _request(
        {
            "summary": "Pod has been in a non-ready state for more than 15 minutes.",
            "runbook_url": RUNBOOK,
        }
    )

    for text in (_alert_text(request), _alert_signature_text(request)):
        assert "prometheus-operator" not in text
        assert "non-ready state" in text


def test_a_link_embedded_in_prose_is_stripped_but_the_prose_survives() -> None:
    request = _request(
        {"description": f"Pod runai-test1/frac-test2-0-0 is pending, see {RUNBOOK}"}
    )

    for text in (_alert_text(request), _alert_signature_text(request)):
        assert "prometheus-operator" not in text
        assert "frac-test2-0-0 is pending" in text


def test_a_real_signature_in_the_alert_still_reaches_the_matcher() -> None:
    """The whole point of reading alert text: XID lives there and nowhere else."""
    request = _request(
        {
            "description": "NVIDIA XID 79: GPU has fallen off the bus",
            "runbook_url": RUNBOOK,
        }
    )

    for text in (_alert_text(request), _alert_signature_text(request)):
        assert "xid 79" in text.casefold()
        assert "fallen off the bus" in text
    # This is the actual haystack match_failure_mode_symptoms /
    # match_runai_known_issues / _promote_signature_cause read from.
    assert "xid 79" in _observed_text([], request)


def test_labels_are_untouched_by_the_permissive_path() -> None:
    text = _alert_text(
        _request({"summary": "s"}, {"alertname": "KubePodNotReady", "pod": "frac-test2-0-0"})
    )

    assert "frac-test2-0-0" in text
    assert "KubePodNotReady" in text


def test_operator_prompt_reaches_guidance_but_not_the_signature_haystack() -> None:
    """The regression this test guards against: a fix once made ``_alert_text``
    itself drop operator_prompt/runbook_url, which also blinded component
    identification, fuzzy recall, and general guidance -- the operator saying
    "check CoreDNS" must be free to steer investigation ORDER even though it
    must never promote a cause on its own word (조사 순서를 바꾸는 건 괜찮지만
    원인 승격은 안된다).
    """
    request = _request(
        {
            "summary": "Pod has been in a non-ready state for more than 15 minutes.",
            "operator_prompt": "혹시 CoreDNS 문제일까요?",
        }
    )

    guidance_text = _alert_text(request)
    assert "CoreDNS" in guidance_text
    assert "non-ready state" in guidance_text

    signature_text = _alert_signature_text(request)
    assert "CoreDNS" not in signature_text
    assert "non-ready state" in signature_text

    # _observed_text's alert branch is the real integration point state.observed
    # is built from -- prove the exclusion holds there too, not just the helper.
    assert "coredns" not in _observed_text([], request)
    assert "non-ready state" in _observed_text([], request)


def test_operator_prompt_label_is_also_excluded_from_the_signature_text() -> None:
    # The field filter applies to labels too, not just annotations -- the
    # non-evidence field can arrive on either side of the alert payload.
    request = _request(
        {"summary": "s"},
        {"alertname": "KubePodNotReady", "operator_prompt": "CoreDNS 문제일까요?"},
    )

    assert "CoreDNS" in _alert_text(request)
    assert "CoreDNS" not in _alert_signature_text(request)
    assert "KubePodNotReady" in _alert_signature_text(request)


def test_ordinary_alert_is_byte_identical_on_both_paths() -> None:
    """Guard: without any non-evidence field, the permissive and filtered
    paths must not silently diverge for the common case."""
    request = _request(
        {"summary": "Pod has been in a non-ready state for more than 15 minutes."}
    )

    assert _alert_text(request) == _alert_signature_text(request)
