"""Unit tests for the TFM extensible-recipe parser extension ( / §A).

Covers the read-only ``tag == 3`` extensible-recipe surface that ``var_delimiter``
(cascade #2) consumes: ``parse_tfm`` reading the ``exten`` table into
``TfmData.exten`` and ``FontMetrics.extensible_recipe``.  Synthetic in-memory
TFMs exercise the bit layout and bounds check; the bundled ``cmex10.tfm``
exercises the real extension/chain data.
"""
from __future__ import annotations

import importlib.resources
import struct

import pytest

from aspose_tex._fonts.font_metrics import FontMetrics
from aspose_tex._fonts.tfm_parser import parse_tfm
from aspose_tex.exceptions import FontError

# ---------------------------------------------------------------------------
# Synthetic TFM builder with per-char tags + an exten table (test helper)
# ---------------------------------------------------------------------------

# char_info tags (char_info bits 9-8).
_TAG_NORMAL = 0
_TAG_CHAIN = 2       # list/chain head — remainder = next-larger char
_TAG_EXTENSIBLE = 3  # extensible — remainder indexes the exten table


def _char_info(width_index: int, tag: int, rem: int) -> int:
    """Pack a char_info word with the given width_index, tag, and remainder."""
    return (width_index << 24) | ((tag & 0x03) << 8) | (rem & 0xFF)


def _exten_word(top: int, mid: int, bot: int, rep: int) -> int:
    """Pack an exten recipe word (TeX §546: top/mid/bot/rep, one byte each)."""
    return (top << 24) | (mid << 16) | (bot << 8) | rep


def _build_tfm_with_exten(
    chars: dict[int, int],
    exten: tuple[int, ...],
    *,
    bc: int = 0,
    ec: int = 4,
) -> bytes:
    """Build a syntactically valid TFM with explicit char_info words + exten table.

    Args:
        chars: Map of char code → packed char_info word for codes in bc..ec.
               Codes absent from the map get a plain width_index=1 normal glyph.
        exten: The exten recipe words (ne == len(exten)).
        bc, ec: Char range.
    """
    lh = 2
    n_chars = ec - bc + 1 if ec >= bc else 0
    nw, nh, nd, ni = 2, 1, 1, 1
    nl, nk = 0, 0
    ne = len(exten)
    params_fw = (0, 0x280000, 0x80000, 0x40000, 0x6EB85, 0x100000, 0)
    np_ = len(params_fw)
    lf = 6 + lh + n_chars + nw + nh + nd + ni + nl + nk + ne + np_
    buf = bytearray()
    buf += struct.pack(">12H", lf, lh, bc, ec, nw, nh, nd, ni, nl, nk, ne, np_)
    buf += struct.pack(">Ii", 0, 0xA00000)  # checksum=0, design=10pt
    for code in range(bc, ec + 1):
        buf += struct.pack(">I", chars.get(code, 1 << 24))  # default: width_index=1
    buf += struct.pack(">ii", 0, 0x80000)  # widths [0, w]
    buf += struct.pack(">i", 0)             # heights [0]
    buf += struct.pack(">i", 0)             # depths [0]
    buf += struct.pack(">i", 0)             # italics [0]
    for word in exten:
        buf += struct.pack(">I", word)
    for p in params_fw:
        buf += struct.pack(">i", p)
    assert len(buf) == lf * 4, f"builder bug: {len(buf)} != {lf * 4}"
    return bytes(buf)


# ---------------------------------------------------------------------------
# parse_tfm — exten table
# ---------------------------------------------------------------------------

def test_parse_reads_exten_table() -> None:
    """parse_tfm populates TfmData.exten with ne words."""
    recipe = _exten_word(0x12, 0x34, 0x56, 0x78)
    data = _build_tfm_with_exten(
        chars={2: _char_info(1, _TAG_EXTENSIBLE, 0)},
        exten=(recipe,),
    )
    tfm = parse_tfm(data)
    assert len(tfm.exten) == 1
    assert tfm.exten[0] == recipe


def test_parse_empty_exten_when_ne_zero() -> None:
    """A font with no extensible chars (ne=0) parses with an empty exten tuple."""
    data = _build_tfm_with_exten(chars={}, exten=())
    tfm = parse_tfm(data)
    assert tfm.exten == ()


def test_parse_extensible_remainder_out_of_range_raises() -> None:
    """An extensible char whose remainder >= ne raises FontError (bounds check)."""
    # Char 2 is extensible with remainder 5, but only 1 exten word exists.
    data = _build_tfm_with_exten(
        chars={2: _char_info(1, _TAG_EXTENSIBLE, 5)},
        exten=(_exten_word(1, 0, 2, 3),),
    )
    with pytest.raises(FontError, match="extensible char remainder"):
        parse_tfm(data)


# ---------------------------------------------------------------------------
# FontMetrics.extensible_recipe
# ---------------------------------------------------------------------------

def _metrics(data: bytes) -> FontMetrics:
    return FontMetrics(parse_tfm(data), at_sp=10 * 65536, tfm_name="synthetic")


def test_extensible_recipe_decodes_pieces() -> None:
    """extensible_recipe returns the (top, mid, bot, rep) byte tuple."""
    data = _build_tfm_with_exten(
        chars={2: _char_info(1, _TAG_EXTENSIBLE, 0)},
        exten=(_exten_word(0x12, 0x34, 0x56, 0x78),),
    )
    assert _metrics(data).extensible_recipe(2) == (0x12, 0x34, 0x56, 0x78)


def test_extensible_recipe_absent_piece_is_zero() -> None:
    """A 0 piece code (e.g. no middle piece) is reported as 0."""
    data = _build_tfm_with_exten(
        chars={2: _char_info(1, _TAG_EXTENSIBLE, 0)},
        exten=(_exten_word(0x10, 0x00, 0x12, 0x11),),  # no mid
    )
    assert _metrics(data).extensible_recipe(2) == (0x10, 0x00, 0x12, 0x11)


def test_extensible_recipe_none_for_normal_char() -> None:
    """A normal (tag==0) glyph has no recipe."""
    data = _build_tfm_with_exten(
        chars={2: _char_info(1, _TAG_NORMAL, 0)},
        exten=(),
    )
    assert _metrics(data).extensible_recipe(2) is None


def test_extensible_recipe_none_for_absent_char() -> None:
    """A char outside bc..ec (and an in-range width_index-0 char) returns None."""
    data = _build_tfm_with_exten(chars={}, exten=())
    m = _metrics(data)
    assert m.extensible_recipe(99) is None  # out of bc..ec range


def test_extensible_recipe_none_for_width_zero_char() -> None:
    """An in-range char with width_index 0 (absent glyph) returns None."""
    data = _build_tfm_with_exten(
        chars={2: _char_info(0, _TAG_EXTENSIBLE, 0)},  # width_index 0 → absent
        exten=(_exten_word(1, 2, 3, 4),),
    )
    assert _metrics(data).extensible_recipe(2) is None


# ---------------------------------------------------------------------------
# Mutual exclusivity of next_larger (tag==2) and extensible_recipe (tag==3)
# ---------------------------------------------------------------------------

def test_chain_and_extensible_are_mutually_exclusive() -> None:
    """A glyph is at most one of chain-head (tag==2) or extensible (tag==3)."""
    data = _build_tfm_with_exten(
        chars={
            1: _char_info(1, _TAG_CHAIN, 2),       # chain head → successor is char 2
            3: _char_info(1, _TAG_EXTENSIBLE, 0),  # extensible
        },
        exten=(_exten_word(0x10, 0, 0x12, 0x11),),
    )
    m = _metrics(data)
    # Chain char: has a successor, no recipe.
    assert m.next_larger(1) == 2
    assert m.extensible_recipe(1) is None
    # Extensible char: has a recipe, no successor.
    assert m.extensible_recipe(3) == (0x10, 0, 0x12, 0x11)
    assert m.next_larger(3) is None


# ---------------------------------------------------------------------------
# Real bundled cmex10.tfm (the math extension font reads)
# ---------------------------------------------------------------------------

def _cmex10() -> FontMetrics:
    pkg = importlib.resources.files("aspose_tex") / "data" / "fonts"
    raw = (pkg / "cmex10.tfm").read_bytes()
    return FontMetrics(parse_tfm(raw), at_sp=10 * 65536, tfm_name="cmex10")


def test_cmex10_has_extensible_recipes() -> None:
    """cmex10 (the math extension font) parses with a non-empty exten table and
    exposes at least one extensible delimiter recipe."""
    pkg = importlib.resources.files("aspose_tex") / "data" / "fonts"
    raw = (pkg / "cmex10.tfm").read_bytes()
    tfm = parse_tfm(raw)
    assert len(tfm.exten) > 0
    m = FontMetrics(tfm, at_sp=10 * 65536, tfm_name="cmex10")
    # cmex10 has extensible delimiters (braces, parens, brackets, vertical bars);
    # at least one char in bc..ec must report a recipe, and every recipe must
    # name a non-zero top OR bottom piece (a degenerate all-zero recipe is invalid).
    recipes = [
        m.extensible_recipe(c)
        for c in range(tfm.bc, tfm.ec + 1)
        if m.extensible_recipe(c) is not None
    ]
    assert recipes, "cmex10 must expose at least one extensible recipe"
    for top, _mid, bot, rep in recipes:
        assert (top or bot or rep), "an extensible recipe must name at least one piece"


def test_cmex10_chain_and_extensible_disjoint() -> None:
    """No cmex10 glyph is simultaneously a chain head and extensible."""
    pkg = importlib.resources.files("aspose_tex") / "data" / "fonts"
    raw = (pkg / "cmex10.tfm").read_bytes()
    tfm = parse_tfm(raw)
    m = FontMetrics(tfm, at_sp=10 * 65536, tfm_name="cmex10")
    for c in range(tfm.bc, tfm.ec + 1):
        if m.extensible_recipe(c) is not None:
            assert m.next_larger(c) is None
