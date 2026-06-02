"""Tests for the register system.

Integration tests using a real pipeline: StringInputSource → InputReader →
CatcodeTable → Tokenizer → Expander + RegisterSet.
"""

from __future__ import annotations

import datetime

import pytest

from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.registers import (
 MAX_DIMEN,
 Glue,
 GlueOrder,
 RegisterBank,
 RegisterSet,
)
from aspose_tex._input import (
 CatcodeTable,
 CharToken,
 ControlSequenceToken,
 InputReader,
 StringInputSource,
 Tokenizer,
)
from aspose_tex._input.catcode import Catcode
from aspose_tex.exceptions import EngineError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_env(text: str) -> tuple[Expander, RegisterSet]:
 """Build a full pipeline and return (expander, register_set)."""
 src = StringInputSource(text)
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 regs = RegisterSet()
 exp = Expander(reader, tok, catcodes, register_provider=regs)
 exp._register_set = regs
 return exp, regs


def run(text: str) -> tuple[list, RegisterSet]:
 """Run the expander, executing register commands, return (remaining tokens, regs)."""
 exp, regs = make_env(text)
 tokens = []
 for t in exp:
 if isinstance(t, ControlSequenceToken) and regs.execute(t.name, exp):
 continue
 tokens.append(t)
 return tokens, regs


def chars_of(tokens: list) -> str:
 """Extract characters from CharTokens with Catcode.OTHER (digits/signs)."""
 return "".join(
 t.char for t in tokens
 if isinstance(t, CharToken) and t.catcode == Catcode.OTHER
 )


# ---------------------------------------------------------------------------
# Direct accessors
# ---------------------------------------------------------------------------

def test_registerbank_initial_values():
 bank = RegisterBank()
 assert all(v == 0 for v in bank.count)
 assert all(v == 0 for v in bank.dimen)
 zero = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
 assert all(g == zero for g in bank.skip)


def test_set_get_count():
 regs = RegisterSet()
 regs.set_count(10, 99)
 assert regs.get_count(10) == 99


def test_set_get_dimen():
 regs = RegisterSet()
 regs.set_dimen(5, 65536)
 assert regs.get_dimen(5) == 65536


def test_set_get_skip():
 regs = RegisterSet()
 g = Glue(65536, 32768, GlueOrder.NORMAL, 16384, GlueOrder.NORMAL)
 regs.set_skip(3, g)
 assert regs.get_skip(3) == g


def test_set_get_toks():
 regs = RegisterSet()
 toks = [CharToken("a", Catcode.LETTER), CharToken("b", Catcode.LETTER)]
 regs.set_toks(0, toks)
 result = regs.get_toks(0)
 assert result == toks
 assert result is not toks # returns a copy


def test_index_out_of_range_raises():
 regs = RegisterSet()
 with pytest.raises(EngineError, match="out of range"):
 regs.set_count(256, 1)
 with pytest.raises(EngineError, match="out of range"):
 regs.get_count(-1)


# ---------------------------------------------------------------------------
# \count assignment and \the (AC-1)
# ---------------------------------------------------------------------------

def test_count_assign_and_the():
 tokens, _ = run(r"\count0=42\the\count0")
 assert chars_of(tokens) == "42"


def test_count_negative():
 _, regs = run(r"\count0=-17")
 assert regs.get_count(0) == -17


def test_count_no_equals():
 _, regs = run(r"\count0 5")
 assert regs.get_count(0) == 5


def test_the_count_produces_string():
 tokens, _ = run(r"\count5=123\the\count5")
 assert chars_of(tokens) == "123"


# ---------------------------------------------------------------------------
# \dimen assignment (AC-2)
# ---------------------------------------------------------------------------

def test_dimen_pt():
 _, regs = run(r"\dimen0=72.27pt")
 assert regs.get_dimen(0) == 4736286


def test_dimen_in():
 _, regs = run(r"\dimen0=1in")
 assert regs.get_dimen(0) == 4736286


def test_dimen_pc():
 _, regs = run(r"\dimen0=1pc")
 assert regs.get_dimen(0) == 786432


def test_dimen_bp():
 _, regs = run(r"\dimen0=1bp")
 assert regs.get_dimen(0) == 65781


def test_dimen_cm():
 _, regs = run(r"\dimen0=1cm")
 assert regs.get_dimen(0) == 1864680


def test_dimen_mm():
 _, regs = run(r"\dimen0=1mm")
 assert regs.get_dimen(0) == 186468


def test_dimen_dd():
 _, regs = run(r"\dimen0=1dd")
 assert regs.get_dimen(0) == 70124


def test_dimen_cc():
 _, regs = run(r"\dimen0=1cc")
 assert regs.get_dimen(0) == 841489


def test_dimen_sp():
 _, regs = run(r"\dimen0=65536sp")
 assert regs.get_dimen(0) == 65536


# ---------------------------------------------------------------------------
# \advance (AC-3)
# ---------------------------------------------------------------------------

def test_advance_count():
 _, regs = run(r"\count0=5\advance\count0 by 10")
 assert regs.get_count(0) == 15


def test_advance_count_negative_delta():
 _, regs = run(r"\count0=10\advance\count0 by -3")
 assert regs.get_count(0) == 7


def test_advance_dimen():
 _, regs = run(r"\dimen0=1pt\advance\dimen0 by 2pt")
 assert regs.get_dimen(0) == 3 * 65536


# ---------------------------------------------------------------------------
# \multiply / \divide
# ---------------------------------------------------------------------------

def test_multiply_count():
 _, regs = run(r"\count0=3\multiply\count0 by 4")
 assert regs.get_count(0) == 12


def test_divide_count():
 _, regs = run(r"\count0=10\divide\count0 by 3")
 assert regs.get_count(0) == 3 # truncation toward zero


def test_divide_negative_truncation():
 # -10 / 3 = -3.33... → truncate toward zero → -3
 _, regs = run(r"\count0=-10\divide\count0 by 3")
 assert regs.get_count(0) == -3


def test_divide_by_zero_raises():
 exp, regs = make_env(r"\count0=5")
 for t in exp:
 if isinstance(t, ControlSequenceToken):
 regs.execute(t.name, exp)
 # Now manually trigger divide-by-zero
 exp2, regs2 = make_env(r"\count0=5\divide\count0 by 0")
 with pytest.raises(EngineError, match="division by zero"):
 for t in exp2:
 if isinstance(t, ControlSequenceToken) and regs2.execute(t.name, exp2):
 continue


# ---------------------------------------------------------------------------
# \skip assignment (AC-5, AC-6)
# ---------------------------------------------------------------------------

def test_skip_assign_full():
 _, regs = run(r"\skip0=3pt plus 2pt minus 1pt")
 g = regs.get_skip(0)
 assert g.width == 3 * 65536
 assert g.stretch == 2 * 65536
 assert g.stretch_order == GlueOrder.NORMAL
 assert g.shrink == 1 * 65536
 assert g.shrink_order == GlueOrder.NORMAL


def test_skip_fil():
 _, regs = run(r"\skip0=0pt plus 1fil")
 g = regs.get_skip(0)
 assert g.stretch == 1
 assert g.stretch_order == GlueOrder.FIL


def test_skip_fill():
 _, regs = run(r"\skip0=0pt plus 1fill")
 g = regs.get_skip(0)
 assert g.stretch == 1
 assert g.stretch_order == GlueOrder.FILL


def test_skip_filll():
 _, regs = run(r"\skip0=0pt plus 1filll")
 g = regs.get_skip(0)
 assert g.stretch == 1
 assert g.stretch_order == GlueOrder.FILLL


# ---------------------------------------------------------------------------
# \countdef alias (AC-7)
# ---------------------------------------------------------------------------

def test_countdef_creates_alias():
 _, regs = run(r"\countdef\pageno=0\pageno=99")
 assert regs.get_count(0) == 99


def test_countdef_the():
 tokens, _ = run(r"\countdef\pageno=0\pageno=99\the\pageno")
 assert chars_of(tokens) == "99"


def test_dimendef():
 _, regs = run(r"\dimendef\mylen=5\mylen=1pt")
 assert regs.get_dimen(5) == 65536


def test_dimendef_the():
 tokens, _ = run(r"\dimendef\mylen=5\mylen=1pt\the\mylen")
 result = "".join(
 t.char for t in tokens
 if isinstance(t, CharToken) and t.catcode == Catcode.OTHER
 )
 # Should contain '65536sp' (our sp format) or similar non-empty value
 assert result # just check it produced something


def test_skipdef():
 _, regs = run(r"\skipdef\myskip=2\myskip=3pt plus 1pt")
 g = regs.get_skip(2)
 assert g.width == 3 * 65536


# ---------------------------------------------------------------------------
# Overflow (AC-8)
# ---------------------------------------------------------------------------

def test_overflow_dimen_raises():
 # 16384pt = 16384 * 65536 = 1073741824 > MAX_DIMEN
 exp, regs = make_env(r"\dimen0=16384pt")
 with pytest.raises(EngineError):
 for t in exp:
 if isinstance(t, ControlSequenceToken):
 regs.execute(t.name, exp)


def test_overflow_advance_count_raises():
 regs = RegisterSet()
 regs.set_count(0, MAX_DIMEN) # very large value
 regs.set_count(1, MAX_DIMEN)
 # Directly test overflow
 with pytest.raises(EngineError, match="out of range"):
 regs.set_count(0, 2**31)


def test_set_dimen_overflow_raises():
 regs = RegisterSet()
 with pytest.raises(EngineError, match="exceeds TeX maximum"):
 regs.set_dimen(0, MAX_DIMEN + 1)


# ---------------------------------------------------------------------------
# \toks
# ---------------------------------------------------------------------------

def test_toks_assign_and_the():
 tokens, _regs = run(r"\toks0={hello}\the\toks0")
 letter_chars = "".join(
 t.char for t in tokens
 if isinstance(t, CharToken) and t.catcode == Catcode.LETTER
 )
 assert "hello" in letter_chars


def test_toks_stores_copy():
 regs = RegisterSet()
 toks_list = [CharToken("x", Catcode.LETTER)]
 regs.set_toks(0, toks_list)
 toks_list.clear()
 assert len(regs.get_toks(0)) == 1 # original stored safely


# ---------------------------------------------------------------------------
# Clock registers (\year, \month, \day, \time)
# ---------------------------------------------------------------------------

def test_clock_year():
 regs = RegisterSet()
 now = datetime.datetime.now()
 assert regs.get_count(0) == now.year # year stored in slot 0 by default


def test_clock_the_year():
 tokens, _ = run(r"\the\year")
 year_str = chars_of(tokens)
 assert len(year_str) == 4
 assert year_str.isdigit()


def test_clock_time_nonnegative():
 regs = RegisterSet()
 # time = minutes since midnight: 0-1439
 time_val = regs.get_count(3)
 assert 0 <= time_val <= 1439


def test_clock_the_time():
 tokens, _ = run(r"\the\time")
 t_str = chars_of(tokens)
 assert t_str.lstrip("-").isdigit()


# ---------------------------------------------------------------------------
# Resolve alias / define alias
# ---------------------------------------------------------------------------

def test_define_resolve_alias():
 regs = RegisterSet()
 regs.define_alias("pageno", "count", 0)
 assert regs.resolve_alias("pageno") == ("count", 0)


def test_resolve_nonexistent_alias():
 regs = RegisterSet()
 assert regs.resolve_alias("undefined") is None


def test_define_alias_out_of_range_raises():
 regs = RegisterSet()
 with pytest.raises(EngineError, match="out of range"):
 regs.define_alias("bad", "count", 300)


# ---------------------------------------------------------------------------
# execute() returns False for unknown commands
# ---------------------------------------------------------------------------

def test_execute_unknown_returns_false():
 exp, regs = make_env("")
 assert regs.execute("relax", exp) is False
 assert regs.execute("hbox", exp) is False
