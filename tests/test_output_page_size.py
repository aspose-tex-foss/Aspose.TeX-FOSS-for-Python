"""Unit tests for the shared page-size resolver.

Covers ``resolve_page_size`` preset lookup, the explicit-tuple form, and the
``ValueError`` contract (AC-4, AC-5 at the resolver boundary).
"""
from __future__ import annotations

import pytest

from aspose_tex._output.page_size import PAGE_SIZE_PRESETS, resolve_page_size

# ---------------------------------------------------------------------------
# Default / None
# ---------------------------------------------------------------------------

def test_none_resolves_to_letter() -> None:
    assert resolve_page_size(None) == (612.0, 792.0)


def test_default_matches_letter_preset() -> None:
    # The None default and the "letter" preset must never drift apart.
    assert resolve_page_size(None) == resolve_page_size("letter")


# ---------------------------------------------------------------------------
# Named presets (FR-4)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("letter", (612.0, 792.0)),
        ("legal", (612.0, 1008.0)),
        ("a3", (841.89, 1190.55)),
        ("a4", (595.276, 841.89)),
        ("a5", (419.528, 595.276)),
    ],
)
def test_preset_dimensions(name: str, expected: tuple[float, float]) -> None:
    assert resolve_page_size(name) == expected


def test_all_presets_return_float_pairs() -> None:
    for name in PAGE_SIZE_PRESETS:
        w, h = resolve_page_size(name)
        assert isinstance(w, float) and isinstance(h, float)
        assert w > 0 and h > 0


# ---------------------------------------------------------------------------
# Case-insensitivity + whitespace (AC-4)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("variant", ["A4", " a4 ", "A4 ", "\ta4"])
def test_preset_lookup_is_case_insensitive_and_stripped(variant: str) -> None:
    assert resolve_page_size(variant) == resolve_page_size("a4")


# ---------------------------------------------------------------------------
# Explicit tuple / list form (FR-3)
# ---------------------------------------------------------------------------

def test_explicit_tuple() -> None:
    assert resolve_page_size((612, 1008)) == (612.0, 1008.0)


def test_explicit_list_resolves_identically() -> None:
    assert resolve_page_size([612, 1008]) == resolve_page_size((612, 1008))


def test_explicit_float_tuple_preserved() -> None:
    assert resolve_page_size((595.276, 841.89)) == (595.276, 841.89)


# ---------------------------------------------------------------------------
# Error contract (FR-7 / AC-5)
# ---------------------------------------------------------------------------

def test_unknown_preset_raises_with_value_and_presets() -> None:
    with pytest.raises(ValueError) as exc:
        resolve_page_size("foolscap")
    msg = str(exc.value)
    assert "foolscap" in msg
    for name in PAGE_SIZE_PRESETS:
        assert name in msg


@pytest.mark.parametrize(
    "bad",
    [
        (0, 100),        # non-positive width
        (100, 0),        # non-positive height
        (-1, 100),       # negative
        (100,),          # wrong arity (too few)
        (1, 2, 3),       # wrong arity (too many)
        ("x", "y"),      # non-numeric
        (True, 100),     # bool is not a dimension
    ],
)
def test_malformed_explicit_size_raises(bad) -> None:
    with pytest.raises(ValueError) as exc:
        resolve_page_size(bad)
    # Message must name the offending value.
    assert repr(bad) in str(exc.value)


def test_bare_int_raises() -> None:
    with pytest.raises(ValueError):
        resolve_page_size(612)  # type: ignore[arg-type]
