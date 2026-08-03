from __future__ import annotations

from pathlib import Path

import yaml

from app.knowledge import (
    DEFAULT_FAMILIES,
    DEFAULT_FAMILY_HINTS,
    DEFAULT_FAMILY_REASONS,
    DEFAULT_FAMILY_RULES,
    FamilyCatalog,
    _load_failure_modes,
    default_family_catalog,
    family_catalog_from_entries,
    load_family_catalog,
)

FAMILIES = Path(__file__).parents[1] / "knowledge" / "families.yaml"


def _family_catalog_drift(catalog: FamilyCatalog, builtin: FamilyCatalog) -> list[str]:
    """One diagnostic line per ``(structure, family)`` where ``catalog``
    (parsed live from families.yaml) disagrees with ``builtin`` (the
    hand-maintained DEFAULT_* fallback in app/knowledge.py). That fallback
    exists FOR the case where the YAML can't be parsed, so it cannot read the
    YAML to build itself -- nothing but this comparison catches it drifting.

    Named per family (not just "rules differ") so a maintainer never has to
    diff two 100+ line constants by hand to find which one entry moved.
    """
    drift: list[str] = []
    names, builtin_names = set(catalog.families), set(builtin.families)
    for family in sorted(names - builtin_names):
        drift.append(f"families: {family!r} in families.yaml but missing from DEFAULT_FAMILIES")
    for family in sorted(builtin_names - names):
        drift.append(f"families: {family!r} in DEFAULT_FAMILIES but missing from families.yaml")
    if names == builtin_names and catalog.families != builtin.families:
        drift.append(
            "families: same names, different order -- "
            f"families.yaml={catalog.families} DEFAULT_FAMILIES={builtin.families}"
        )

    shared = sorted(names & builtin_names)
    for family in shared:
        if catalog.rules.get(family) != builtin.rules.get(family):
            drift.append(
                f"rules[{family!r}] drifted -- families.yaml={catalog.rules.get(family)!r} "
                f"DEFAULT_FAMILY_RULES={builtin.rules.get(family)!r}"
            )
        if catalog.reasons.get(family) != builtin.reasons.get(family):
            drift.append(
                f"reasons[{family!r}] drifted -- families.yaml={catalog.reasons.get(family)!r} "
                f"DEFAULT_FAMILY_REASONS={builtin.reasons.get(family)!r}"
            )

    catalog_hints = dict(catalog.hints)
    builtin_hints = dict(builtin.hints)
    for family in shared:
        if catalog_hints.get(family) != builtin_hints.get(family):
            drift.append(
                f"hints[{family!r}] drifted -- families.yaml={catalog_hints.get(family)!r} "
                f"DEFAULT_FAMILY_HINTS={builtin_hints.get(family)!r}"
            )
    # Hint order is a real tiebreak (planner._ordered_hypotheses keeps
    # declaration order deterministic on a 0-0 keyword tie), not cosmetic, so
    # a same-content reorder must be its own, separately named drift.
    catalog_order = [family for family, _ in catalog.hints]
    builtin_order = [family for family, _ in builtin.hints]
    if catalog_order != builtin_order and set(catalog_order) == set(builtin_order):
        drift.append(
            "hints: same families, different order -- "
            f"families.yaml={catalog_order} DEFAULT_FAMILY_HINTS={builtin_order}"
        )
    return drift


def test_families_yaml_matches_builtin_catalog() -> None:
    raw = yaml.safe_load(FAMILIES.read_text(encoding="utf-8"))
    catalog = family_catalog_from_entries(raw)

    assert catalog is not None
    builtin = default_family_catalog()
    drift = _family_catalog_drift(catalog, builtin)
    assert not drift, "families.yaml vs DEFAULT_* builtin fallback drifted:\n" + "\n".join(drift)

    # Belt-and-suspenders direct equality: also pins the exact FamilyCatalog
    # shape the drift helper above assumes, independent of that helper's logic.
    assert catalog.families == DEFAULT_FAMILIES
    assert catalog.rules == DEFAULT_FAMILY_RULES
    assert catalog.hints == DEFAULT_FAMILY_HINTS
    assert catalog.reasons == DEFAULT_FAMILY_REASONS
    assert load_family_catalog(str(FAMILIES)) == catalog


def test_family_catalog_drift_names_the_structure_and_family() -> None:
    """Teeth for _family_catalog_drift: a keyword/hint/reason edited on only
    one side (name set unchanged) must be caught and named -- this is exactly
    what a bare ``catalog.rules == DEFAULT_FAMILY_RULES`` assert does not say
    plainly, and it is the drift the family-name-only check would miss."""
    builtin = default_family_catalog()
    family = "gpu_hardware_error"
    canonical, agents, keywords = builtin.rules[family]

    drifted = FamilyCatalog(
        families=(*builtin.families, "brand_new_family"),
        rules={**builtin.rules, family: (canonical, agents, (*keywords, "extra_keyword"))},
        hints=tuple(
            (fam, (*kw, "extra_hint")) if fam == family else (fam, kw) for fam, kw in builtin.hints
        ),
        reasons={**builtin.reasons, family: builtin.reasons[family] + " (edited)"},
    )

    drift = _family_catalog_drift(drifted, builtin)

    assert any("families" in line and "brand_new_family" in line for line in drift)
    assert any(line.startswith(f"rules[{family!r}]") for line in drift)
    assert any(line.startswith(f"hints[{family!r}]") for line in drift)
    assert any(line.startswith(f"reasons[{family!r}]") for line in drift)
    # A family untouched by the drift above must not be reported.
    assert not any("runai_scheduling_quota" in line for line in drift)


def test_family_catalog_drift_detects_hint_order_change() -> None:
    """Hint order is a real planner tiebreak, not cosmetic -- a reorder must
    be caught even when every family's own content still matches byte for
    byte (so the per-family content check above would see no difference)."""
    builtin = default_family_catalog()
    reordered = FamilyCatalog(
        families=builtin.families,
        rules=builtin.rules,
        hints=(builtin.hints[1], builtin.hints[0], *builtin.hints[2:]),
        reasons=builtin.reasons,
    )

    drift = _family_catalog_drift(reordered, builtin)

    assert any("hints" in line and "order" in line for line in drift)


def test_family_catalog_drift_empty_when_identical() -> None:
    builtin = default_family_catalog()
    assert _family_catalog_drift(builtin, builtin) == []


def test_oomkilled_is_runtime_not_startup_keyword() -> None:
    catalog = load_family_catalog(str(FAMILIES))

    assert "oomkilled" not in catalog.rules["workload_startup_error"][2]
    assert "oomkilled" in catalog.rules["workload_runtime_error"][2]
    modes = _load_failure_modes("knowledge/failure_modes.yaml")
    assert any(item["symptom"] == "OOMKilled" for item in modes["workload_runtime_error"])
    assert not any(item["symptom"] == "OOMKilled" for item in modes["workload_startup_error"])


def test_non_catalog_candidate_counts_dropped_and_recorded() -> None:
    from app.services.pipeline import _catalog_only_candidate_counts
    from app.services.root_cause_ranking import FAMILIES

    catalog_family = next(iter(FAMILIES))
    reasoning: dict[str, object] = {}
    counts = {catalog_family: 3, "workload_startup_image_failure": 2}

    filtered = _catalog_only_candidate_counts(counts, reasoning)

    assert filtered == {catalog_family: 3}
    assert reasoning["dropped_candidate_families"] == ["workload_startup_image_failure"]

    clean = _catalog_only_candidate_counts({catalog_family: 1}, reasoning={})
    assert clean == {catalog_family: 1}
