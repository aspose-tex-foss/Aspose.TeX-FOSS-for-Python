"""Tests for the dimension/glue parser.

Tests parse_integer, parse_dimen, parse_glue, and _scan_keyword in isolation
by building a real Expander from a string and driving the parser functions
directly.
"""

from __future__ import annotations

import pytest

from aspose_tex._engine.dimparser import (
 _scan_keyword,
 parse_dimen,
 parse_glue,
 parse_integer,
)
from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.registers import GlueOrder, RegisterSet
from aspose_tex._input import (
 CatcodeTable,
 CharToken,
 InputReader,
 StringInputSource,
 Tokenizer,
)
from aspose_tex.exceptions import EngineError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_expander(text: str, regs: RegisterSet | None = None) -> Expander:
 src = StringInputSource(text)
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 exp = Expander(reader, tok, catcodes, register_provider=regs)
 if regs is not None:
 exp._register_set = regs
 return exp


# ---------------------------------------------------------------------------
# parse_integer
# ---------------------------------------------------------------------------

def test_parse_integer_decimal():
 exp = make_expander("42 ")
 assert parse_integer(exp) == 42


def test_parse_integer_negative():
 exp = make_expander("-17 ")
 assert parse_integer(exp) == -17


def test_parse_integer_plus_sign():
 exp = make_expander("+5 ")
 assert parse_integer(exp) == 5


def test_parse_integer_double_negative():
 exp = make_expander("--3 ")
 assert parse_integer(exp) == 3


def test_parse_integer_octal():
 # '77 octal = 63
 exp = make_expander("'77 ")
 assert parse_integer(exp) == 63


def test_parse_integer_hex_upper():
 # "FF hex = 255
 exp = make_expander('"FF ')
 assert parse_integer(exp) == 255


def test_parse_integer_hex_lower():
 exp = make_expander('"ff ')
 assert parse_integer(exp) == 255


def test_parse_integer_charcode():
 # `A = 65
 exp = make_expander("`A ")
 assert parse_integer(exp) == 65


def test_parse_integer_no_digits_raises():
 exp = make_expander("pt")
 with pytest.raises(EngineError):
 parse_integer(exp)


def test_parse_integer_allow_negative_false_raises():
 exp = make_expander("-5 ")
 with pytest.raises(EngineError):
 parse_integer(exp, allow_negative=False)


# ---------------------------------------------------------------------------
# parse_dimen
# ---------------------------------------------------------------------------

def test_parse_dimen_pt():
 exp = make_expander("1pt")
 assert parse_dimen(exp) == 65536


def test_parse_dimen_fraction():
 # 1.5pt = 65536 + 32768 = 98304
 exp = make_expander("1.5pt")
 assert parse_dimen(exp) == 98304


def test_parse_dimen_72_27pt():
 # AC-2: 72.27pt = 4736286sp
 exp = make_expander("72.27pt")
 assert parse_dimen(exp) == 4736286


def test_parse_dimen_in():
 exp = make_expander("1in")
 assert parse_dimen(exp) == 4736286


def test_parse_dimen_pc():
 exp = make_expander("1pc")
 assert parse_dimen(exp) == 786432


def test_parse_dimen_bp():
 exp = make_expander("1bp")
 assert parse_dimen(exp) == 65781


def test_parse_dimen_cm():
 exp = make_expander("1cm")
 assert parse_dimen(exp) == 1864680


def test_parse_dimen_mm():
 exp = make_expander("1mm")
 assert parse_dimen(exp) == 186468


def test_parse_dimen_dd():
 exp = make_expander("1dd")
 assert parse_dimen(exp) == 70124


def test_parse_dimen_cc():
 exp = make_expander("1cc")
 assert parse_dimen(exp) == 841489


def test_parse_dimen_sp():
 exp = make_expander("65536sp")
 assert parse_dimen(exp) == 65536


def test_parse_dimen_negative():
 exp = make_expander("-2pt")
 assert parse_dimen(exp) == -131072


def test_parse_dimen_overflow_raises():
 # MAX_DIMEN + 1 should raise
 # 16384pt = 16384 * 65536 = 1073741824 > MAX_DIMEN (1073741823)
 exp = make_expander("16384pt")
 with pytest.raises(EngineError, match="exceeds TeX maximum"):
 parse_dimen(exp)


def test_parse_dimen_unknown_unit_raises():
 exp = make_expander("1xy")
 with pytest.raises(EngineError, match="unknown dimension unit"):
 parse_dimen(exp)


def test_parse_dimen_mu_unit():
 """§4d — ``mu`` parses as 1pt-equivalent (math unit)."""
 exp = make_expander("3mu")
 assert parse_dimen(exp) == 3 * 65536


# ---------------------------------------------------------------------------
# parse_dimen — true* units (FR-16 / AC-6)
# ---------------------------------------------------------------------------

class _RegistryStub:
 """Stand-in for NamedParameterRegistry exposing only ``mag`` lookup."""

 def __init__(self, mag_slot: int) -> None:
 self._mag_slot = mag_slot

 def lookup(self, name: str):
 if name == "mag":
 class _Entry:
 slot = self._mag_slot
 return _Entry()
 return None


def _make_expander_with_mag(text: str, mag: int) -> Expander:
 """Build an expander whose ``\\mag`` slot is populated to ``mag``."""
 src = StringInputSource(text)
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 regs = RegisterSet()
 # Slot 297 is the catalog slot for \mag. Use _internal=True
 # so we can write the named-param slot directly.
 regs.set_count(297, mag, _internal=True)
 exp = Expander(reader, tok, catcodes, register_provider=regs)
 exp._register_set = regs
 exp._named_params = _RegistryStub(mag_slot=297)
 return exp


def test_truept_default_mag():
 """With \\mag=1000, ``10truept`` == ``10pt`` == 655_360sp."""
 exp = _make_expander_with_mag("10truept", mag=1000)
 assert parse_dimen(exp) == 10 * 65536


def test_truept_mag_1200():
 """With \\mag=1200, ``10truept`` == floor(10 * 65536 * 1000 / 1200)."""
 exp = _make_expander_with_mag("10truept", mag=1200)
 assert parse_dimen(exp) == (10 * 65536 * 1000) // 1200


def test_truept_mag_500():
 """With \\mag=500, ``10truept`` is *larger* (the document is shrunk)."""
 exp = _make_expander_with_mag("10truept", mag=500)
 assert parse_dimen(exp) == (10 * 65536 * 1000) // 500


@pytest.mark.parametrize(
 "unit,unit_sp",
 [
 ("truept", 65536),
 ("truein", 4736286),
 ("truecm", 1864680),
 ("truemm", 186468),
 ("truebp", 65781),
 ("truepc", 786432),
 ("truedd", 70124),
 ("truecc", 841489),
 ("truesp", 1),
 ],
)
def test_true_units_apply_mag_correction(unit: str, unit_sp: int) -> None:
 """Every ``true<unit>`` applies the ``1000/mag`` correction (AC-6)."""
 exp = _make_expander_with_mag(f"5{unit}", mag=2000)
 assert parse_dimen(exp) == (5 * unit_sp * 1000) // 2000


def test_unknown_truepx_raises():
 """``10truepx`` — ``px`` is not a known unit, registry should reject."""
 exp = _make_expander_with_mag("10truepx", mag=1000)
 with pytest.raises(EngineError, match="unknown dimension unit"):
 parse_dimen(exp)


def test_no_named_params_falls_back_to_mag_1000():
 """When ``_named_params`` is absent, ``true*`` defaults to mag=1000."""
 exp = make_expander("10truept")
 # Bare expander has no _named_params attribute → no scaling.
 assert parse_dimen(exp) == 10 * 65536


# ---------------------------------------------------------------------------
# parse_integer — count1<digit> concatenation regression (FR-17 / AC-5)
# ---------------------------------------------------------------------------

def test_parse_integer_two_digits():
 """parse_integer is greedy on contiguous digits — ``10`` yields 10."""
 exp = make_expander("10 ")
 assert parse_integer(exp) == 10


def test_parse_integer_count_index_two_digits():
 """``\\count`` then digits ``10`` reads slot 10 — primitive composition path."""
 src = StringInputSource(r"\count10 ")
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 regs = RegisterSet()
 regs.set_count(10, 7)
 exp = Expander(reader, tok, catcodes, register_provider=regs)
 exp._register_set = regs
 # parse_integer treats \count as register family then reads index 10
 assert parse_integer(exp) == 7


def test_count1_digit_concatenation_via_interpreter() -> None:
 """FR-17: ``\\count1#1`` from a macro reads as \\count<10..19> after expansion.

 Uses the full interpreter so macro expansion happens before the integer
 scanner sees the digits — the bug guarded against would split the leading
 ``1`` from the expanded ``#1`` and write \\count1 instead of \\count10.
 """
 from aspose_tex._engine.interpreter import TeXInterpreter
 from aspose_tex.presentation import DviDevice

 interp = TeXInterpreter()
 device = DviDevice()
 src = StringInputSource(
 r"\def\setn#1{\count1#1=#1 }"
 r"\setn 0\setn 5\bye"
 )
 interp.run_with_device(src, device)
 assert interp._register_set.get_count(10) == 0
 assert interp._register_set.get_count(15) == 5


# ---------------------------------------------------------------------------
# _scan_keyword
# ---------------------------------------------------------------------------

def test_scan_keyword_hit():
 exp = make_expander("plus ")
 assert _scan_keyword(exp, "plus") is True


def test_scan_keyword_miss():
 exp = make_expander("minus ")
 assert _scan_keyword(exp, "plus") is False
 # Tokens should be pushed back — stream still has "minus"
 assert _scan_keyword(exp, "minus") is True


def test_scan_keyword_case_insensitive():
 exp = make_expander("BY ")
 assert _scan_keyword(exp, "by") is True


def test_scan_keyword_partial_miss():
 exp = make_expander("plx ")
 assert _scan_keyword(exp, "plus") is False
 # Stream should be restored: can still read 'p'
 from aspose_tex._engine.dimparser import _next_raw
 tok = _next_raw(exp)
 assert isinstance(tok, CharToken) and tok.char == "p"


def test_scan_keyword_fil():
 exp = make_expander("fil ")
 assert _scan_keyword(exp, "filll") is False
 assert _scan_keyword(exp, "fill") is False
 assert _scan_keyword(exp, "fil") is True


def test_scan_keyword_fill():
 exp = make_expander("fill ")
 assert _scan_keyword(exp, "filll") is False
 assert _scan_keyword(exp, "fill") is True


def test_scan_keyword_filll():
 exp = make_expander("filll ")
 assert _scan_keyword(exp, "filll") is True


# ---------------------------------------------------------------------------
# parse_glue
# ---------------------------------------------------------------------------

def test_parse_glue_width_only():
 exp = make_expander("3pt")
 g = parse_glue(exp)
 assert g.width == 3 * 65536
 assert g.stretch == 0
 assert g.stretch_order == GlueOrder.NORMAL
 assert g.shrink == 0
 assert g.shrink_order == GlueOrder.NORMAL


def test_parse_glue_full():
 # 3pt plus 2pt minus 1pt (AC-5)
 exp = make_expander("3pt plus 2pt minus 1pt")
 g = parse_glue(exp)
 assert g.width == 3 * 65536
 assert g.stretch == 2 * 65536
 assert g.stretch_order == GlueOrder.NORMAL
 assert g.shrink == 1 * 65536
 assert g.shrink_order == GlueOrder.NORMAL


def test_parse_glue_no_shrink():
 exp = make_expander("3pt plus 1pt")
 g = parse_glue(exp)
 assert g.width == 3 * 65536
 assert g.stretch == 1 * 65536
 assert g.shrink == 0


def test_parse_glue_fil():
 # 0pt plus 1fil (AC-6)
 exp = make_expander("0pt plus 1fil")
 g = parse_glue(exp)
 assert g.stretch == 1
 assert g.stretch_order == GlueOrder.FIL


def test_parse_glue_fill():
 exp = make_expander("0pt plus 1fill")
 g = parse_glue(exp)
 assert g.stretch == 1
 assert g.stretch_order == GlueOrder.FILL


def test_parse_glue_filll():
 exp = make_expander("0pt plus 1filll")
 g = parse_glue(exp)
 assert g.stretch == 1
 assert g.stretch_order == GlueOrder.FILLL


def test_parse_glue_fil_shrink():
 exp = make_expander("0pt plus 0pt minus 2fil")
 g = parse_glue(exp)
 assert g.shrink == 2
 assert g.shrink_order == GlueOrder.FIL
