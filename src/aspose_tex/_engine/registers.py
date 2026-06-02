"""TeX register system: storage, assignment, arithmetic, and \\the expansion.

Implements: count, dimen, skip, muskip, and toks
registers; \\advance/\\multiply/\\divide arithmetic; \\countdef/\\dimendef/\\skipdef/
\\toksdef aliases; and \\the expansion for registers.

See the project documentation for design rationale.
"""

from __future__ import annotations

import dataclasses
import datetime
from enum import IntEnum
from typing import TYPE_CHECKING, Final

from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
 from aspose_tex._engine.expansion import Expander
 from aspose_tex._engine.group import GroupStack
 from aspose_tex._input.token import Token


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------

class GlueOrder(IntEnum):
 """Stretch/shrink order for TeX glue.

 NORMAL means finite (ordinary scaled-point units).
 FIL / FILL / FILLL are infinite orders in ascending strength.
 """
 NORMAL = 0
 FIL = 1
 FILL = 2
 FILLL = 3


@dataclasses.dataclass(slots=True, frozen=True)
class Glue:
 """Immutable TeX glue value (skip register content).

 All integer fields are in scaled points (sp), except when stretch_order /
 shrink_order is FIL/FILL/FILLL — then the coefficient is in fil-units.

 Example — ``3pt plus 2fil minus 1pt``::

 Glue(width=196608, stretch=2, stretch_order=GlueOrder.FIL,
 shrink=65536, shrink_order=GlueOrder.NORMAL)
 """
 width: int
 stretch: int
 stretch_order: GlueOrder
 shrink: int
 shrink_order: GlueOrder


MAX_DIMEN: Final[int] = 0x3FFFFFFF # 2^30 - 1 sp ~= 16383.99999pt


# ---------------------------------------------------------------------------
# Raw storage
# ---------------------------------------------------------------------------

# User-facing register slots: 0..255 (TeX contract).
# Internal pool 256..319 reserved for NamedParameterRegistry-driven writes
# (§3a). See _check_index / _check_internal_slot.
_NUM_REGISTERS: Final[int] = 320


class RegisterBank:
 """320-slot arrays for all five TeX register families.

 Array-based for O(1) access ( NFR-1). No logic lives here.

 User-facing API exposes slots 0..255 (TeX contract). Slots 256..319 are
 reserved for ``NamedParameterRegistry`` (§3a) and only reachable
 through the internal-slot code path on ``RegisterSet.set_*`` /
 ``get_*`` (``_internal=True``).
 """

 __slots__ = ("count", "dimen", "muskip", "skip", "toks")

 def __init__(self) -> None:
 _zero = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
 self.count: list[int] = [0] * _NUM_REGISTERS
 self.dimen: list[int] = [0] * _NUM_REGISTERS
 self.skip: list[Glue] = [_zero] * _NUM_REGISTERS
 self.muskip: list[Glue] = [_zero] * _NUM_REGISTERS
 self.toks: list[list[Token]] = [[] for _ in range(_NUM_REGISTERS)]


# ---------------------------------------------------------------------------
# Register set
# ---------------------------------------------------------------------------

_COUNT_MAX: Final[int] = 2**31 - 1 # max signed 32-bit integer
_COUNT_MIN: Final[int] = -(2**31) # min signed 32-bit integer

# Register family names that map to direct array access
_DIRECT_FAMILIES: Final[frozenset[str]] = frozenset({"count", "dimen", "skip", "muskip", "toks"})


class RegisterSet:
 """TeX register set: implements ``RegisterProvider`` and the execution interface.

 Implements the ``RegisterProvider`` protocol (defined in ``expansion.py``)
 so it can be passed as ``register_provider`` to ``Expander``.

 Also exposes ``execute(cs_name, expander)`` for the execution layer to call
 when it encounters unexpandable register commands.

 The ``_aliases`` dict maps CS names to ``(family, index)`` tuples for
 ``\\countdef`` et al. Special counters ``\\year``, ``\\month``, ``\\day``,
 ``\\time`` are initialised from the system clock.

 Args:
 year_reg: Count register index for ``\\year`` (default 0).
 month_reg: Count register index for ``\\month`` (default 1).
 day_reg: Count register index for ``\\day`` (default 2).
 time_reg: Count register index for ``\\time`` (default 3).

 Example::

 from aspose_tex._input import StringInputSource, InputReader, CatcodeTable
 from aspose_tex._input.tokenizer import Tokenizer
 from aspose_tex._engine.expansion import Expander
 from aspose_tex._engine.registers import RegisterSet

 src = StringInputSource(r'\\count0=42 \\the\\count0')
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 regs = RegisterSet()
 expander = Expander(reader, tok, catcodes, register_provider=regs)
 expander._register_set = regs # allow dimparser to resolve register values

 tokens = []
 for t in expander:
 if isinstance(t, ControlSequenceToken) and regs.execute(t.name, expander):
 continue
 tokens.append(t)
 # tokens contains CharToken('4'), CharToken('2')
 """

 def __init__(
 self,
 year_reg: int = 0,
 month_reg: int = 1,
 day_reg: int = 2,
 time_reg: int = 3,
 group_stack: GroupStack | None = None,
 ) -> None:
 self._bank = RegisterBank()
 self._aliases: dict[str, tuple[str, int]] = {}
 # \chardef / \mathchardef constants (§3c). Distinct from
 # _aliases because the second tuple field is a frozen integer value,
 # not a register slot.
 self._constants: dict[str, tuple[str, int]] = {}
 self._group_stack = group_stack
 # Optional post-construction wiring (§5d). Set by the
 # interpreter so that \the\catcode<n> / \the\<codename><n> can read
 # live tokenizer-domain and engine-domain code arrays, and so that
 # \the\<named-param> falls through to NamedParameterRegistry.
 self._catcodes = None
 self._code_arrays = None
 self._named_params = None
 self._init_clock_registers(year_reg, month_reg, day_reg, time_reg)

 def _init_clock_registers(
 self, year_reg: int, month_reg: int, day_reg: int, time_reg: int
 ) -> None:
 now = datetime.datetime.now()
 self._bank.count[year_reg] = now.year
 self._bank.count[month_reg] = now.month
 self._bank.count[day_reg] = now.day
 self._bank.count[time_reg] = now.hour * 60 + now.minute
 self._aliases["year"] = ("count", year_reg)
 self._aliases["month"] = ("count", month_reg)
 self._aliases["day"] = ("count", day_reg)
 self._aliases["time"] = ("count", time_reg)

 # ------------------------------------------------------------------
 # RegisterProvider protocol
 # ------------------------------------------------------------------

 def get_tokens_for_the(self, token: Token, expander: Expander) -> list[Token]:
 """Expand ``\\the <token>`` into a list of character tokens.

 Reads additional tokens from ``expander`` when the token names a
 register family (``\\count``, ``\\dimen``, etc.) to get the index.

 Args:
 token: The CS token immediately following ``\\the``.
 expander: The active expander (for reading register index).

 Returns:
 A list of ``CharToken`` instances with ``Catcode.OTHER`` representing
 the value as a string.

 Raises:
 EngineError: if the token does not name a readable register.
 """
 from aspose_tex._engine.dimparser import parse_integer

 if not isinstance(token, ControlSequenceToken):
 raise EngineError("\\the: cannot take the value of a character token")

 name = token.name

 if name == "fontdimen":
 interp = getattr(expander, "_interpreter", None)
 if interp is None:
 raise EngineError("\\the\\fontdimen: interpreter not wired")
 return interp._fontdimen_tokens(expander)

 # Code-array reads (§5d). \the\catcode<ch> returns the live
 # CatcodeTable value at the current group level (TeXbook Chapter 7).
 if name == "catcode":
 cc = parse_integer(expander, allow_negative=False)
 _check_char_code_byte(cc, name)
 if self._catcodes is None:
 raise EngineError("\\the\\catcode: catcode table not wired")
 return _int_to_tokens(int(self._catcodes.get(chr(cc))))

 if name in ("mathcode", "delcode", "sfcode", "lccode", "uccode"):
 cc = parse_integer(expander, allow_negative=False)
 _check_char_code_byte(cc, name)
 if self._code_arrays is None:
 raise EngineError(f"\\the\\{name}: code-array storage not wired")
 getter = getattr(self._code_arrays, f"get_{name}")
 return _int_to_tokens(getter(cc))

 # Direct register family names
 if name == "count":
 idx = parse_integer(expander, allow_negative=False)
 _check_index(idx)
 return _int_to_tokens(self._bank.count[idx])

 if name == "dimen":
 idx = parse_integer(expander, allow_negative=False)
 _check_index(idx)
 return _sp_to_tokens(self._bank.dimen[idx])

 if name == "skip":
 idx = parse_integer(expander, allow_negative=False)
 _check_index(idx)
 return _glue_to_tokens(self._bank.skip[idx])

 if name == "muskip":
 idx = parse_integer(expander, allow_negative=False)
 _check_index(idx)
 return _glue_to_tokens(self._bank.muskip[idx])

 if name == "toks":
 idx = parse_integer(expander, allow_negative=False)
 _check_index(idx)
 return list(self._bank.toks[idx])

 # Alias lookup
 alias = self._aliases.get(name)
 if alias is not None:
 family, idx = alias
 if family == "count":
 return _int_to_tokens(self._bank.count[idx])
 if family == "dimen":
 return _sp_to_tokens(self._bank.dimen[idx])
 if family == "skip":
 return _glue_to_tokens(self._bank.skip[idx])
 if family == "muskip":
 return _glue_to_tokens(self._bank.muskip[idx])
 if family == "toks":
 return list(self._bank.toks[idx])

 # \chardef / \mathchardef constants (§3c)
 const = self._constants.get(name)
 if const is not None:
 return _int_to_tokens(const[1])

 # InternalQuantityRegistry fallback. This must
 # precede the historical Appendix A named-parameter placeholders for
 # page-state names such as \pagegoal and \prevdepth.
 interp = getattr(expander, "_interpreter", None)
 internal = getattr(interp, "_internal_quantities", None)
 if internal is not None:
 entry = internal.lookup(name)
 if entry is not None:
 return internal.dispatch_the(entry, expander)

 # NamedParameterRegistry fallback (§5d / ).
 if self._named_params is not None:
 entry = self._named_params.lookup(name)
 if entry is not None:
 return self._named_params.dispatch_the(entry, expander)

 raise EngineError(f"\\the: cannot take the value of \\{name}")

 # ------------------------------------------------------------------
 # Execution interface
 # ------------------------------------------------------------------

 def execute(self, cs_name: str, expander: Expander) -> bool:
 """Process a register command consumed from the expander stream.

 Recognised commands: ``count``, ``dimen``, ``skip``, ``muskip``, ``toks``
 (assignment); ``advance``, ``multiply``, ``divide`` (arithmetic);
 ``countdef``, ``dimendef``, ``skipdef``, ``toksdef`` (alias definition).
 Also handles assignment to previously defined aliases.

 Returns:
 ``True`` if the command was consumed; ``False`` if not a register command.

 Raises:
 EngineError: on overflow, invalid index, or malformed syntax.
 """
 from aspose_tex._engine.dimparser import (
 parse_dimen,
 parse_glue,
 parse_integer,
 )

 # Direct family assignment: \count0=42
 if cs_name in _DIRECT_FAMILIES:
 idx = parse_integer(expander, allow_negative=False)
 _check_index(idx)
 _eat_optional_equals(expander)
 if cs_name == "count":
 val = parse_integer(expander)
 self.set_count(idx, val)
 elif cs_name == "dimen":
 val = parse_dimen(expander)
 self.set_dimen(idx, val)
 elif cs_name in ("skip", "muskip"):
 glue = parse_glue(expander)
 if cs_name == "skip":
 self.set_skip(idx, glue)
 else:
 self.set_muskip(idx, glue)
 elif cs_name == "toks":
 tokens = _read_toks_value(expander)
 self.set_toks(idx, tokens)
 expander.fire_after_assignment()
 return True

 # Alias assignment: \pageno=42 (where \pageno was defined by \countdef)
 alias = self._aliases.get(cs_name)
 if alias is not None:
 family, idx = alias
 _eat_optional_equals(expander)
 if family == "count":
 val = parse_integer(expander)
 self.set_count(idx, val)
 elif family == "dimen":
 val = parse_dimen(expander)
 self.set_dimen(idx, val)
 elif family == "skip":
 glue = parse_glue(expander)
 self.set_skip(idx, glue)
 elif family == "muskip":
 glue = parse_glue(expander)
 self.set_muskip(idx, glue)
 elif family == "toks":
 tokens = _read_toks_value(expander)
 self.set_toks(idx, tokens)
 expander.fire_after_assignment()
 return True

 # Arithmetic: \advance, \multiply, \divide
 if cs_name == "advance":
 done = self._exec_advance(expander)
 if done:
 expander.fire_after_assignment()
 return done
 if cs_name == "multiply":
 done = self._exec_multiply(expander)
 if done:
 expander.fire_after_assignment()
 return done
 if cs_name == "divide":
 done = self._exec_divide(expander)
 if done:
 expander.fire_after_assignment()
 return done

 # Def commands: \countdef, \dimendef, \skipdef, \toksdef
 if cs_name in ("countdef", "dimendef", "skipdef", "toksdef"):
 family = cs_name[:-3] # strip "def"
 target = _read_cs_name(expander)
 _eat_optional_equals(expander)
 idx = parse_integer(expander, allow_negative=False)
 _check_index(idx)
 self.define_alias(target, family, idx)
 expander.fire_after_assignment()
 return True

 # \muskipdef — completes the alias family (§3b / FR-9)
 if cs_name == "muskipdef":
 target = _read_cs_name(expander)
 _eat_optional_equals(expander)
 idx = parse_integer(expander, allow_negative=False)
 _check_index(idx)
 self.define_alias(target, "muskip", idx)
 expander.fire_after_assignment()
 return True

 # \chardef — define CS as a frozen 8-bit char-code constant (§3b)
 if cs_name == "chardef":
 target = _read_cs_name(expander)
 _eat_optional_equals(expander)
 val = parse_integer(expander, allow_negative=False)
 if not (0 <= val <= 255):
 raise EngineError(f"\\chardef value {val} out of range 0-255")
 self.define_constant(target, "chardef", val)
 expander.fire_after_assignment()
 return True

 # \mathchardef — define CS as a frozen 24-bit math-char constant
 if cs_name == "mathchardef":
 target = _read_cs_name(expander)
 _eat_optional_equals(expander)
 val = parse_integer(expander, allow_negative=False)
 if not (0 <= val <= 0x8000):
 raise EngineError(
 f"\\mathchardef value {val} out of range 0-32768"
 )
 self.define_constant(target, "mathchardef", val)
 expander.fire_after_assignment()
 return True

 return False

 def _exec_advance(self, expander: Expander) -> bool:
 """Execute \\advance\\count N by V."""
 from aspose_tex._engine.dimparser import (
 _scan_keyword,
 parse_dimen,
 parse_glue,
 parse_integer,
 )
 family, idx = self._read_operand(expander)
 _scan_keyword(expander, "by")
 if family == "count":
 delta = parse_integer(expander)
 result = self._bank.count[idx] + delta
 if not (_COUNT_MIN <= result <= _COUNT_MAX):
 raise EngineError("arithmetic overflow in \\advance")
 self.set_count(idx, result)
 elif family == "dimen":
 delta = parse_dimen(expander)
 result = self._bank.dimen[idx] + delta
 if abs(result) > MAX_DIMEN:
 raise EngineError("arithmetic overflow in \\advance")
 self.set_dimen(idx, result)
 elif family in ("skip", "muskip"):
 cur = self._bank.skip[idx] if family == "skip" else self._bank.muskip[idx]
 delta_glue = parse_glue(expander)
 new_width = cur.width + delta_glue.width
 if abs(new_width) > MAX_DIMEN:
 raise EngineError("arithmetic overflow in \\advance")
 new_glue = Glue(
 width=new_width,
 stretch=cur.stretch + delta_glue.stretch,
 stretch_order=cur.stretch_order,
 shrink=cur.shrink + delta_glue.shrink,
 shrink_order=cur.shrink_order,
 )
 if family == "skip":
 self.set_skip(idx, new_glue)
 else:
 self.set_muskip(idx, new_glue)
 return True

 def _exec_multiply(self, expander: Expander) -> bool:
 """Execute \\multiply\\count N by V."""
 from aspose_tex._engine.dimparser import _scan_keyword, parse_integer
 family, idx = self._read_operand(expander)
 _scan_keyword(expander, "by")
 factor = parse_integer(expander)
 if family == "count":
 result = self._bank.count[idx] * factor
 if not (_COUNT_MIN <= result <= _COUNT_MAX):
 raise EngineError("arithmetic overflow in \\multiply")
 self.set_count(idx, result)
 elif family == "dimen":
 result = self._bank.dimen[idx] * factor
 if abs(result) > MAX_DIMEN:
 raise EngineError("arithmetic overflow in \\multiply")
 self.set_dimen(idx, result)
 elif family in ("skip", "muskip"):
 cur = self._bank.skip[idx] if family == "skip" else self._bank.muskip[idx]
 new_width = cur.width * factor
 if abs(new_width) > MAX_DIMEN:
 raise EngineError("arithmetic overflow in \\multiply")
 new_glue = Glue(
 width=new_width,
 stretch=cur.stretch * factor,
 stretch_order=cur.stretch_order,
 shrink=cur.shrink * factor,
 shrink_order=cur.shrink_order,
 )
 if family == "skip":
 self.set_skip(idx, new_glue)
 else:
 self.set_muskip(idx, new_glue)
 return True

 def _exec_divide(self, expander: Expander) -> bool:
 """Execute \\divide\\count N by V (truncation toward zero)."""
 from aspose_tex._engine.dimparser import _scan_keyword, parse_integer
 family, idx = self._read_operand(expander)
 _scan_keyword(expander, "by")
 divisor = parse_integer(expander)
 if divisor == 0:
 raise EngineError("division by zero in \\divide")
 if family == "count":
 # Python truncation toward zero: int(a / b)
 self.set_count(idx, int(self._bank.count[idx] / divisor))
 elif family == "dimen":
 self.set_dimen(idx, int(self._bank.dimen[idx] / divisor))
 elif family in ("skip", "muskip"):
 cur = self._bank.skip[idx] if family == "skip" else self._bank.muskip[idx]
 new_glue = Glue(
 width=int(cur.width / divisor),
 stretch=int(cur.stretch / divisor),
 stretch_order=cur.stretch_order,
 shrink=int(cur.shrink / divisor),
 shrink_order=cur.shrink_order,
 )
 if family == "skip":
 self.set_skip(idx, new_glue)
 else:
 self.set_muskip(idx, new_glue)
 return True

 def _read_operand(self, expander: Expander) -> tuple[str, int]:
 """Read \\family N or alias after \\advance/\\multiply/\\divide.

 Returns ``(family, index)``.
 """
 from aspose_tex._engine.dimparser import parse_integer
 tok = expander._next_raw()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = expander._next_raw()
 if not isinstance(tok, ControlSequenceToken):
 raise EngineError("\\advance/\\multiply/\\divide: register expected")
 name = tok.name
 if name in _DIRECT_FAMILIES and name != "toks":
 idx = parse_integer(expander, allow_negative=False)
 _check_index(idx)
 return name, idx
 alias = self._aliases.get(name)
 if alias is not None and alias[0] != "toks":
 return alias
 raise EngineError(f"\\advance/\\multiply/\\divide: \\{name} is not an arithmetic register")

 # ------------------------------------------------------------------
 # Direct accessors
 # ------------------------------------------------------------------

 def get_count(self, index: int, *, _internal: bool = False) -> int:
 """Return the value of count register ``index``.

 Args:
 index: Register index. User-facing range is 0-255; named
 parameters may use 256-319 via ``_internal=True``.
 _internal: If True, accept slots 0-319 (NamedParameterRegistry path).

 Returns:
 The integer value.

 Raises:
 EngineError: if index is out of range.
 """
 if _internal:
 _check_internal_slot(index)
 else:
 _check_index(index)
 return self._bank.count[index]

 def set_count(self, index: int, value: int, *, _internal: bool = False) -> None:
 """Set count register ``index`` to ``value``.

 Saves the old value to the group stack unless the assignment is global.
 See for save-on-write design.

 Args:
 index: Register index. User-facing range is 0-255; named
 parameters may use 256-319 via ``_internal=True``.
 value: New value; must be in [-2^31, 2^31-1].
 _internal: If True, accept slots 0-319 (NamedParameterRegistry path).

 Raises:
 EngineError: on range violation.
 """
 if _internal:
 _check_internal_slot(index)
 else:
 _check_index(index)
 if not (_COUNT_MIN <= value <= _COUNT_MAX):
 raise EngineError(
 f"count register value {value} out of range [-2^31, 2^31-1]"
 )
 if self._group_stack is not None:
 if not self._group_stack.is_global_pending:
 old = self._bank.count[index]
 bank = self._bank
 _idx = index
 self._group_stack.save(
 ("count", _idx),
 lambda: bank.count.__setitem__(_idx, old),
 )
 else:
 self._group_stack.consume_global()
 self._bank.count[index] = value

 def get_dimen(self, index: int, *, _internal: bool = False) -> int:
 """Return the value of dimen register ``index`` in scaled points."""
 if _internal:
 _check_internal_slot(index)
 else:
 _check_index(index)
 return self._bank.dimen[index]

 def set_dimen(self, index: int, value: int, *, _internal: bool = False) -> None:
 """Set dimen register ``index`` to ``value`` scaled points.

 Saves the old value to the group stack unless the assignment is global.

 Args:
 index: Register index. See ``get_count`` for slot ranges.
 value: New value; ``abs(value)`` must be ≤ MAX_DIMEN.
 _internal: If True, accept slots 0-319 (NamedParameterRegistry path).

 Raises:
 EngineError: on range violation.
 """
 if _internal:
 _check_internal_slot(index)
 else:
 _check_index(index)
 if abs(value) > MAX_DIMEN:
 raise EngineError(f"dimension {value}sp exceeds TeX maximum")
 if self._group_stack is not None:
 if not self._group_stack.is_global_pending:
 old = self._bank.dimen[index]
 bank = self._bank
 _idx = index
 self._group_stack.save(
 ("dimen", _idx),
 lambda: bank.dimen.__setitem__(_idx, old),
 )
 else:
 self._group_stack.consume_global()
 self._bank.dimen[index] = value

 def get_skip(self, index: int, *, _internal: bool = False) -> Glue:
 """Return the glue value of skip register ``index``."""
 if _internal:
 _check_internal_slot(index)
 else:
 _check_index(index)
 return self._bank.skip[index]

 def set_skip(self, index: int, value: Glue, *, _internal: bool = False) -> None:
 """Set skip register ``index`` to ``value``.

 Saves the old value to the group stack unless the assignment is global.
 """
 if _internal:
 _check_internal_slot(index)
 else:
 _check_index(index)
 if self._group_stack is not None:
 if not self._group_stack.is_global_pending:
 old = self._bank.skip[index]
 bank = self._bank
 _idx = index
 self._group_stack.save(
 ("skip", _idx),
 lambda: bank.skip.__setitem__(_idx, old),
 )
 else:
 self._group_stack.consume_global()
 self._bank.skip[index] = value

 def get_muskip(self, index: int, *, _internal: bool = False) -> Glue:
 """Return the glue value of muskip register ``index``."""
 if _internal:
 _check_internal_slot(index)
 else:
 _check_index(index)
 return self._bank.muskip[index]

 def set_muskip(self, index: int, value: Glue, *, _internal: bool = False) -> None:
 """Set muskip register ``index`` to ``value``.

 Saves the old value to the group stack unless the assignment is global.
 """
 if _internal:
 _check_internal_slot(index)
 else:
 _check_index(index)
 if self._group_stack is not None:
 if not self._group_stack.is_global_pending:
 old = self._bank.muskip[index]
 bank = self._bank
 _idx = index
 self._group_stack.save(
 ("muskip", _idx),
 lambda: bank.muskip.__setitem__(_idx, old),
 )
 else:
 self._group_stack.consume_global()
 self._bank.muskip[index] = value

 def get_toks(self, index: int, *, _internal: bool = False) -> list[Token]:
 """Return a copy of the token list in toks register ``index``."""
 if _internal:
 _check_internal_slot(index)
 else:
 _check_index(index)
 return list(self._bank.toks[index])

 def set_toks(
 self, index: int, value: list[Token], *, _internal: bool = False
 ) -> None:
 """Set toks register ``index`` to ``value`` (stores a copy).

 Saves the old token list to the group stack unless the assignment is global.
 """
 if _internal:
 _check_internal_slot(index)
 else:
 _check_index(index)
 if self._group_stack is not None:
 if not self._group_stack.is_global_pending:
 old = list(self._bank.toks[index])
 bank = self._bank
 _idx = index
 self._group_stack.save(
 ("toks", _idx),
 lambda: bank.toks.__setitem__(_idx, old),
 )
 else:
 self._group_stack.consume_global()
 self._bank.toks[index] = list(value)

 def define_alias(self, cs_name: str, family: str, index: int) -> None:
 """Register a CS name as an alias for a specific register slot.

 Saves the old alias to the group stack unless the assignment is global.

 Args:
 cs_name: CS name without backslash.
 family: One of ``"count"``, ``"dimen"``, ``"skip"``, ``"toks"``.
 index: Register index 0-255.
 """
 _check_index(index)
 if self._group_stack is not None:
 if not self._group_stack.is_global_pending:
 old_alias = self._aliases.get(cs_name)
 aliases = self._aliases
 _cs = cs_name
 if old_alias is None:
 self._group_stack.save(
 ("alias", _cs),
 lambda: aliases.pop(_cs, None),
 )
 else:
 self._group_stack.save(
 ("alias", _cs),
 lambda: aliases.__setitem__(_cs, old_alias),
 )
 else:
 self._group_stack.consume_global()
 self._aliases[cs_name] = (family, index)

 def resolve_alias(self, cs_name: str) -> tuple[str, int] | None:
 """Return ``(family, index)`` if ``cs_name`` is a known alias, else ``None``."""
 return self._aliases.get(cs_name)

 def define_constant(self, cs_name: str, kind: str, value: int) -> None:
 """Define ``cs_name`` as a frozen integer constant.

 ``kind`` is one of ``"chardef"`` (0..255) or ``"mathchardef"``
 (0..0x8000). The mapping is group-scoped — saved on first write per
 with namespace key ``("const", cs_name)``.

 Args:
 cs_name: Control sequence name without backslash.
 kind: ``"chardef"`` or ``"mathchardef"``.
 value: The frozen integer value.
 """
 if self._group_stack is not None:
 if not self._group_stack.is_global_pending:
 old = self._constants.get(cs_name)
 consts = self._constants
 _name = cs_name
 if old is None:
 self._group_stack.save(
 ("const", _name),
 lambda: consts.pop(_name, None),
 )
 else:
 self._group_stack.save(
 ("const", _name),
 lambda: consts.__setitem__(_name, old),
 )
 else:
 self._group_stack.consume_global()
 self._constants[cs_name] = (kind, value)

 def resolve_constant(self, cs_name: str) -> tuple[str, int] | None:
 """Return ``(kind, value)`` if ``cs_name`` is a \\chardef/\\mathchardef
 constant, else ``None``.
 """
 return self._constants.get(cs_name)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _check_index(idx: int) -> None:
 """User-facing register index check (TeX contract: 0..255)."""
 if not (0 <= idx <= 255):
 raise EngineError(f"register index {idx} out of range 0-255")


def _check_internal_slot(idx: int) -> None:
 """Internal slot check for NamedParameterRegistry-driven writes (0..319)."""
 if not (0 <= idx <= _NUM_REGISTERS - 1):
 raise EngineError(
 f"named-parameter slot {idx} out of range 0-{_NUM_REGISTERS - 1}"
 )


def _check_char_code_byte(cc: int, code_name: str) -> None:
 """Range-check a character code used as a code-array index."""
 if not (0 <= cc <= 255):
 raise EngineError(f"\\the\\{code_name}: char code {cc} out of range 0-255")


def _eat_optional_equals(expander: Expander) -> None:
 """Skip optional spaces and one optional '=' token."""
 tok = expander._next_raw()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = expander._next_raw()
 if isinstance(tok, CharToken) and tok.char == "=" and tok.catcode == Catcode.OTHER:
 # Skip one optional space after '='
 nxt = expander._next_raw()
 if nxt is not None and not (isinstance(nxt, CharToken) and nxt.catcode == Catcode.SPACE):
 expander._stack.append(nxt)
 elif tok is not None:
 expander._stack.append(tok)


def _read_cs_name(expander: Expander) -> str:
 """Read a control sequence token and return its name."""
 tok = expander._next_raw()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = expander._next_raw()
 if not isinstance(tok, ControlSequenceToken):
 raise EngineError(f"Control sequence expected, got {tok!r}")
 return tok.name


def _read_toks_value(expander: Expander) -> list[Token]:
 """Read a brace-delimited token list for \\toks assignment."""
 tok = expander._next_raw()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = expander._next_raw()
 if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
 return expander._scan_balanced_group()
 raise EngineError(f"Expected '{{' for \\toks value, got {tok!r}")


def _int_to_tokens(value: int) -> list[Token]:
 """Convert an integer to a list of Catcode.OTHER CharTokens (decimal string)."""
 return [CharToken(c, Catcode.OTHER) for c in str(value)]


def _sp_to_tokens(sp: int) -> list[Token]:
 """Convert a dimension in scaled points to CharTokens in '<N>sp' format."""
 return [CharToken(c, Catcode.OTHER) for c in f"{sp}sp"]


def _glue_to_tokens(glue: Glue) -> list[Token]:
 """Convert a Glue value to CharTokens in TeX canonical string format."""
 parts: list[str] = [f"{glue.width}sp"]
 if glue.stretch != 0 or glue.stretch_order != GlueOrder.NORMAL:
 stretch_str = _fil_str(glue.stretch, glue.stretch_order)
 parts.append(f"plus {stretch_str}")
 if glue.shrink != 0 or glue.shrink_order != GlueOrder.NORMAL:
 shrink_str = _fil_str(glue.shrink, glue.shrink_order)
 parts.append(f"minus {shrink_str}")
 text = " ".join(parts)
 return [CharToken(c, Catcode.SPACE if c == " " else Catcode.OTHER) for c in text]


def _fil_str(value: int, order: GlueOrder) -> str:
 if order == GlueOrder.NORMAL:
 return f"{value}sp"
 suffix = ["", "fil", "fill", "filll"][int(order)]
 return f"{value}{suffix}"
