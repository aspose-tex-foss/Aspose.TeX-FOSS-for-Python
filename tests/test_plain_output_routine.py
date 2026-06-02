"""Unit tests for plain-TeX output-routine helpers.

Focused on the output-routine-only surface: ``_format_folio`` and
``_to_roman_lowercase``. See ``tests/test_page_builder.py`` for
full-routine integration tests.
"""
from __future__ import annotations

from aspose_tex._engine.page_builder import _format_folio, _to_roman_lowercase


def test_format_folio_positive():
 assert _format_folio(1) == "1"
 assert _format_folio(2026) == "2026"


def test_format_folio_zero():
 assert _format_folio(0) == "0"


def test_format_folio_negative_roman():
 assert _format_folio(-1) == "i"
 assert _format_folio(-4) == "iv"
 assert _format_folio(-1994) == "mcmxciv"


def test_to_roman_boundary():
 assert _to_roman_lowercase(3999) == "mmmcmxcix"
 assert _to_roman_lowercase(1) == "i"
 assert _to_roman_lowercase(0) == ""
 assert _to_roman_lowercase(-5) == ""
