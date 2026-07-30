"""_replace_attr must emit TypeQL literals, not Python repr.

An unquoted bool used to render as `True`, which the TypeDB parser rejects — so
every knowledge package carrying a compiled probe template failed to mirror.
"""

from __future__ import annotations

from typing import Any

import ontology.ingest as ingest


class _Rows:
    def as_concept_rows(self) -> list[Any]:
        return []


class _Result:
    def resolve(self) -> _Rows:
        return _Rows()


class _Tx:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def query(self, q: str) -> _Result:
        self.queries.append(q)
        return _Result()


def _inserted(value: Any) -> str:
    tx = _Tx()
    ingest._replace_attr(tx, "package_template_binding", "package_template_binding_id",
                         "pkg:v1:p01", "template_active", value, quoted=False)
    return next(q for q in tx.queries if "insert" in q)


def test_unquoted_bool_uses_lowercase_typeql_literals() -> None:
    assert "has template_active true;" in _inserted(True)
    assert "has template_active false;" in _inserted(False)
    assert "True" not in _inserted(True)


def test_unquoted_int_is_unchanged() -> None:
    assert "has template_active 42;" in _inserted(42)


if __name__ == "__main__":
    test_unquoted_bool_uses_lowercase_typeql_literals()
    test_unquoted_int_is_unchanged()
    print("ok")
