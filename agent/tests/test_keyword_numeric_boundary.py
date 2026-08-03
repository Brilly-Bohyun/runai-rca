"""S6: a bare numeric keyword must not match INSIDE an unrelated larger
number. failure_modes.yaml ships ~90 five-digit NVSwitch SXid codes as plain
numeric keywords (10001, 12001, 23001, ...). _keyword_hits enforces a strict
word boundary on the right of a match but was lenient on the left (by design
— see test_left_leniency_still_matches_concatenated_alert_names below), so a
resourceVersion or port number that merely ENDS in the same five digits as an
SXid code selected the "NVSwitch SXid — Always Fatal" playbook."""

from __future__ import annotations

from app.knowledge import _keyword_hits


def test_numeric_keyword_does_not_match_inside_a_resourceversion_or_port() -> None:
    # Exact text from a real collector dump: a resourceVersion and a
    # nodePort each coincidentally end in a 5-digit SXid code.
    text = (
        "restartcount 3 resourceversion 8823001 ... nodeport 30012001 hostport 11004"
    ).lower()
    hits, _negated = _keyword_hits(text, ["23001", "12001"])
    assert hits == []


def test_numeric_keyword_does_not_match_inside_a_duration_or_byte_count() -> None:
    text = "duration=10005ms bytes=1123001".lower()
    hits, _negated = _keyword_hits(text, ["23001", "10005"])
    assert hits == []


def test_genuine_sxid_code_in_real_log_text_still_matches() -> None:
    """Over-correction guard: the fix must only close the left boundary for
    numeric keywords, not blind the matcher to a real, delimited SXid code."""
    text = "nvswitch: SXid 23001 egress DST-VC credit overflow".lower()
    hits, _negated = _keyword_hits(text, ["23001", "sxid"])
    assert set(hits) == {"23001", "sxid"}

    text2 = "NVSwitch SXid 20034 LTSSM Fault Up; GPU reported Xid 74".lower()
    hits2, _negated2 = _keyword_hits(text2, ["20034"])
    assert hits2 == ["20034"]


def test_left_leniency_still_matches_concatenated_alert_names() -> None:
    """The left boundary stays lenient for NON-numeric keywords: a Kubernetes
    alert name collapses to one lowercase run (KubePodImagePullBackOff ->
    "kubepodimagepullbackoff"), so a suffix keyword must still match with
    nothing but letters to its left. Only digit-run keywords get the new,
    stricter left boundary."""
    hits, _negated = _keyword_hits("kubepodimagepullbackoff", ["imagepullbackoff"])
    assert hits == ["imagepullbackoff"]
