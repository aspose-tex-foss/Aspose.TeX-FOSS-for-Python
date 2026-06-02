"""Dimension and glue parsing from the TeX token stream.

Implements: conversion of textual dimension
and glue specifications into internal scaled-point values.

See the project documentation for design rationale.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
 from aspose_tex._engine.expansion import Expander
 from aspose_tex._engine.registers import Glue, GlueOrder


# ---------------------------------------------------------------------------
# Unit conversion table (1 unit → scaled points)
# Exact TeX values: 1pt = 65536sp, 1in = 72.27pt.
# ---------------------------------------------------------------------------

_UNIT_SP: Final[dict[str, int]] = {
 "sp": 1,
 "pt": 65536,
 "pc": 786432, # 12pt
 "in": 4736286, # floor(72.27 * 65536)
 "bp": 65781, # floor(65536 * 7227 / 7200) per TeX xn_over_d
 "cm": 1864680, # floor(4736286 / 2.54)
 "mm": 186468, # floor(1864680 / 10)
 "dd": 70124, # floor(65536 * 1157 / 1238) — Didot point
 "cc": 841489, # 12 * 70124 + 1 (nearest-integer 12dd)
 # §4d / — math unit, accepted in muglue specs (\thinmuskip
 # etc.). Value is 1pt (65536 sp); math-mode consumption lands in M4.
 "mu": 65536,
}

_DEC_DIGITS: Final[frozenset[str]] = frozenset("0123456789")
_OCT_DIGITS: Final[frozenset[str]] = frozenset("01234567")
_HEX_DIGITS: Final[frozenset[str]] = frozenset("0123456789ABCDEFabcdef")


# ---------------------------------------------------------------------------
# Internal helpers — thin wrappers around private Expander state
# ---------------------------------------------------------------------------

def _next_raw(expander: Expander):
 """Pull the next raw token from the expander."""
 return expander._next_raw()


def _push_back(expander: Expander, tok) -> None:
 """Push a single token back onto the expander stack."""
 if tok is not None:
 expander._stack.append(tok)


def _eat_spaces(expander: Expander):
 """Consume leading space tokens; return first non-space token (or None)."""
 tok = _next_raw(expander)
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = _next_raw(expander)
 return tok


def _char_matches(tok, ch: str) -> bool:
 """Return True if tok is a LETTER or OTHER CharToken with char == ch (case-insensitive)."""
 return (
 isinstance(tok, CharToken)
 and tok.catcode in (Catcode.LETTER, Catcode.OTHER)
 and tok.char.lower() == ch.lower()
 )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_integer(expander: Expander, *, allow_negative: bool = True) -> int:
 """Read a TeX integer constant from the expander token stream.

 Handles optional signs, decimal/octal/hex literals, character codes,
 and count/dimen register references used as integers.
 Absorbs one optional trailing space.

 Args:
 expander: The active expander to read tokens from.
 allow_negative: If ``False``, a leading ``-`` raises ``EngineError``.

 Returns:
 The parsed integer value.

 Raises:
 EngineError: on malformed input or missing digits.
 """
 tok = _eat_spaces(expander)

 sign = 1
 while isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER and tok.char in "+-":
 if tok.char == "-":
 if not allow_negative:
 raise EngineError("Negative integer not allowed here")
 sign = -sign
 tok = _eat_spaces(expander)

 if tok is None:
 raise EngineError("Number expected")

 # CS token → register lookup
 if isinstance(tok, ControlSequenceToken):
 regs = getattr(expander, "_register_set", None)
 if regs is not None:
 alias = regs.resolve_alias(tok.name)
 if alias is not None and alias[0] == "count":
 return sign * regs.get_count(alias[1])
 if alias is not None and alias[0] == "dimen":
 return sign * regs.get_dimen(alias[1])
 if tok.name == "count":
 idx = parse_integer(expander, allow_negative=False)
 return sign * regs.get_count(idx)
 if tok.name == "dimen":
 idx = parse_integer(expander, allow_negative=False)
 return sign * regs.get_dimen(idx)
 # \chardef / \mathchardef constants are integer-readable
 # (§3c). Used by patterns like
 # ``\catcode`\~=\active`` (plain.tex line 19).
 const = regs.resolve_constant(tok.name)
 if const is not None:
 return sign * const[1]
 internal = _lookup_internal_quantity(expander, tok.name)
 if internal is not None and internal[0] in ("int", "dimen"):
 return sign * int(internal[1])
 named = _lookup_named_parameter(expander, tok.name)
 if named is not None and named[0] in ("int", "dimen"):
 return sign * int(named[1])
 _push_back(expander, tok)
 raise EngineError("Number expected")

 if not (isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER):
 _push_back(expander, tok)
 raise EngineError("Number expected")

 char = tok.char

 if char in _DEC_DIGITS:
 digits = [char]
 while True:
 nxt = _next_raw(expander)
 if isinstance(nxt, CharToken) and nxt.catcode == Catcode.OTHER and nxt.char in _DEC_DIGITS:
 digits.append(nxt.char)
 elif isinstance(nxt, CharToken) and nxt.catcode == Catcode.SPACE:
 break
 else:
 _push_back(expander, nxt)
 break
 return sign * int("".join(digits))

 if char == "'":
 digits = []
 while True:
 nxt = _next_raw(expander)
 if isinstance(nxt, CharToken) and nxt.catcode == Catcode.OTHER and nxt.char in _OCT_DIGITS:
 digits.append(nxt.char)
 elif isinstance(nxt, CharToken) and nxt.catcode == Catcode.SPACE:
 break
 else:
 _push_back(expander, nxt)
 break
 if not digits:
 raise EngineError("Number expected after '")
 return sign * int("".join(digits), 8)

 if char == '"':
 digits = []
 while True:
 nxt = _next_raw(expander)
 if (
 isinstance(nxt, CharToken)
 and nxt.catcode in (Catcode.OTHER, Catcode.LETTER)
 and nxt.char in _HEX_DIGITS
 ):
 digits.append(nxt.char)
 elif isinstance(nxt, CharToken) and nxt.catcode == Catcode.SPACE:
 break
 else:
 _push_back(expander, nxt)
 break
 if not digits:
 raise EngineError('Number expected after "')
 return sign * int("".join(digits), 16)

 if char == "`":
 nxt = _next_raw(expander)
 if nxt is None:
 raise EngineError("Number expected after `")
 if isinstance(nxt, CharToken):
 val = ord(nxt.char)
 elif isinstance(nxt, ControlSequenceToken):
 if len(nxt.name) == 1:
 val = ord(nxt.name)
 elif nxt.name == "":
 val = 13
 elif nxt.name == "\\":
 val = ord("\\")
 else:
 raise EngineError(f"Number expected after `, got \\{nxt.name}")
 else:
 raise EngineError("Number expected after `")
 sp = _next_raw(expander)
 if not (isinstance(sp, CharToken) and sp.catcode == Catcode.SPACE):
 _push_back(expander, sp)
 return sign * val

 _push_back(expander, tok)
 raise EngineError("Number expected")


def parse_dimen(
 expander: Expander,
 *,
 em_sp: int = 655360,
 ex_sp: int = 282169,
 allow_negative: bool = True,
) -> int:
 """Read a TeX dimension from the expander token stream.

 Parses: ``[sign] <number>[.<frac>] <unit>``

 Conversion: ``sp = int_part * unit_sp + floor(frac_val * unit_sp / 10^frac_len)``

 Args:
 expander: The active expander to read tokens from.
 em_sp: Value of 1em in sp (default 10pt = 655360sp, placeholder for ).
 ex_sp: Value of 1ex in sp (default ~4.3pt = 282169sp, placeholder for ).
 allow_negative: If ``False``, a leading ``-`` raises ``EngineError``.

 Returns:
 The dimension in scaled points.

 Raises:
 EngineError: on overflow, unknown unit, or malformed input.
 """
 from aspose_tex._engine.registers import MAX_DIMEN

 tok = _eat_spaces(expander)

 sign = 1
 while isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER and tok.char in "+-":
 if tok.char == "-":
 if not allow_negative:
 raise EngineError("Negative dimension not allowed here")
 sign = -sign
 tok = _eat_spaces(expander)

 if tok is None:
 raise EngineError("Dimension expected")

 # \dimen N or alias as a dimension source
 if isinstance(tok, ControlSequenceToken):
 regs = getattr(expander, "_register_set", None)
 if regs is not None:
 if tok.name == "dimen":
 idx = parse_integer(expander, allow_negative=False)
 return sign * regs.get_dimen(idx)
 alias = regs.resolve_alias(tok.name)
 if alias is not None and alias[0] == "dimen":
 return sign * regs.get_dimen(alias[1])
 box_dim = _lookup_box_dimension(expander, tok.name)
 if box_dim is not None:
 return sign * box_dim
 internal = _lookup_internal_quantity(expander, tok.name)
 if internal is not None:
 kind, value = internal
 if kind == "dimen":
 return sign * int(value)
 if kind == "skip":
 return sign * value.width
 named = _lookup_named_parameter(expander, tok.name)
 if named is not None:
 kind, value = named
 if kind == "dimen":
 return sign * int(value)
 if kind == "skip":
 return sign * value.width
 _push_back(expander, tok)
 raise EngineError("Dimension expected")

 int_part = 0
 frac_digits: list[str] = []

 if isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER and tok.char in _DEC_DIGITS:
 int_digits = [tok.char]
 while True:
 nxt = _next_raw(expander)
 if isinstance(nxt, CharToken) and nxt.catcode == Catcode.OTHER and nxt.char in _DEC_DIGITS:
 int_digits.append(nxt.char)
 else:
 tok = nxt
 break
 int_part = int("".join(int_digits))
 elif isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER and tok.char == ".":
 # Leading decimal point — consume frac digits immediately
 int_part = 0
 while True:
 nxt = _next_raw(expander)
 if isinstance(nxt, CharToken) and nxt.catcode == Catcode.OTHER and nxt.char in _DEC_DIGITS:
 frac_digits.append(nxt.char)
 else:
 tok = nxt
 break
 # tok is now the first char of the unit
 return _finish_dimen(expander, sign, int_part, frac_digits, tok, em_sp, ex_sp, MAX_DIMEN)
 else:
 _push_back(expander, tok)
 raise EngineError("Dimension expected")

 # tok is first token after integer digits: may be '.'
 if isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER and tok.char == ".":
 while True:
 nxt = _next_raw(expander)
 if isinstance(nxt, CharToken) and nxt.catcode == Catcode.OTHER and nxt.char in _DEC_DIGITS:
 frac_digits.append(nxt.char)
 else:
 tok = nxt
 break

 return _finish_dimen(expander, sign, int_part, frac_digits, tok, em_sp, ex_sp, MAX_DIMEN)


def _finish_dimen(expander, sign, int_part, frac_digits, unit_first_tok, em_sp, ex_sp, max_dimen):
 """Convert integer+fraction+unit into scaled points and apply sign.

 ``true*`` units (FR-16 / §4a) are recognised here: the result is
 additionally scaled by ``1000 / mag`` after the base dimension is computed,
 so that subsequent ``mag/1000`` document-magnification cancels back out.
 ``mag`` is read live from ``NamedParameterRegistry`` via the expander's
 ``_named_params`` / ``_register_set`` attributes; absent the registry
 (e.g. unit-test pipelines) it defaults to 1000 (true* == plain).
 """
 dimen_unit_sp = _lookup_dimension_unit(expander, unit_first_tok)
 if dimen_unit_sp is not None:
 unit_sp = dimen_unit_sp
 is_true = False
 else:
 unit = _read_unit(expander, unit_first_tok)

 is_true = unit.startswith("true") and len(unit) >= 6
 base_unit = unit[4:] if is_true else unit

 if base_unit == "em":
 unit_sp = em_sp
 elif base_unit == "ex":
 unit_sp = ex_sp
 elif base_unit in _UNIT_SP:
 unit_sp = _UNIT_SP[base_unit]
 else:
 raise EngineError(f"unknown dimension unit '{unit}'")

 sp = int_part * unit_sp
 if frac_digits:
 frac_len = len(frac_digits)
 frac_val = int("".join(frac_digits))
 sp += frac_val * unit_sp // (10 ** frac_len)

 if is_true:
 mag = _lookup_mag(expander)
 sp = sp * 1000 // mag

 if sp > max_dimen:
 raise EngineError(f"dimension {sp}sp exceeds TeX maximum")

 return sign * sp


def _lookup_dimension_unit(expander: Expander, tok) -> int | None:
 """Return the scaled-point unit for ``<number><dimen-register>`` forms."""
 if not isinstance(tok, ControlSequenceToken):
 return None
 regs = getattr(expander, "_register_set", None)
 if regs is not None:
 unit: int | None = None
 if tok.name == "dimen":
 idx = parse_integer(expander, allow_negative=False)
 unit = regs.get_dimen(idx)
 else:
 alias = regs.resolve_alias(tok.name)
 if alias is not None and alias[0] == "dimen":
 unit = regs.get_dimen(alias[1])
 if unit is not None:
 sp = _next_raw(expander)
 if not (isinstance(sp, CharToken) and sp.catcode == Catcode.SPACE):
 _push_back(expander, sp)
 return unit
 internal = _lookup_internal_quantity(expander, tok.name)
 if internal is not None:
 kind, value = internal
 if kind == "dimen":
 return int(value)
 if kind == "skip":
 return value.width
 named = _lookup_named_parameter(expander, tok.name)
 if named is not None:
 kind, value = named
 if kind == "dimen":
 return int(value)
 if kind == "skip":
 return value.width
 return None


def _lookup_mag(expander: Expander) -> int:
 """Read live ``\\mag`` from the NamedParameterRegistry.

 Returns 1000 (the IniTeX default) when the registry isn't wired — keeps
 isolated parser tests that build a bare ``Expander`` working.
 """
 named = getattr(expander, "_named_params", None)
 regs = getattr(expander, "_register_set", None)
 if named is None or regs is None:
 return 1000
 entry = named.lookup("mag")
 if entry is None:
 return 1000
 return regs.get_count(entry.slot, _internal=True)


def parse_glue(
 expander: Expander,
 *,
 em_sp: int = 655360,
 ex_sp: int = 282169,
) -> Glue:
 """Read a TeX glue specification from the expander token stream.

 Grammar::

 <glue> ::= <dimen> [plus <dimen_or_fill> [minus <dimen_or_fill>]]

 <dimen_or_fill> ::= <dimen> | <integer> fil[l[l]]

 Args:
 expander: The active expander to read tokens from.
 em_sp: Value of 1em in scaled points.
 ex_sp: Value of 1ex in scaled points.

 Returns:
 A ``Glue`` value.

 Raises:
 EngineError: on malformed input or dimension overflow.
 """
 from aspose_tex._engine.registers import Glue, GlueOrder

 tok = _eat_spaces(expander)
 direct = _lookup_glue_value(expander, tok)
 if direct is not None:
 sp = _next_raw(expander)
 if not (isinstance(sp, CharToken) and sp.catcode == Catcode.SPACE):
 _push_back(expander, sp)
 return direct
 _push_back(expander, tok)

 width = parse_dimen(expander, em_sp=em_sp, ex_sp=ex_sp)

 stretch = 0
 stretch_order: GlueOrder = GlueOrder.NORMAL
 shrink = 0
 shrink_order: GlueOrder = GlueOrder.NORMAL

 if _scan_keyword(expander, "plus"):
 stretch, stretch_order = _parse_dimen_or_fill(expander, em_sp=em_sp, ex_sp=ex_sp)

 if _scan_keyword(expander, "minus"):
 shrink, shrink_order = _parse_dimen_or_fill(expander, em_sp=em_sp, ex_sp=ex_sp)

 return Glue(
 width=width,
 stretch=stretch,
 stretch_order=stretch_order,
 shrink=shrink,
 shrink_order=shrink_order,
 )


def _lookup_glue_value(expander: Expander, tok) -> Glue | None:
 """Return a skip/muskip value referenced directly as glue."""
 from aspose_tex._engine.internal_quantities import QuantityKind
 from aspose_tex._engine.named_parameters import ParamKind

 if not isinstance(tok, ControlSequenceToken):
 return None
 regs = getattr(expander, "_register_set", None)
 if regs is not None:
 if tok.name == "skip":
 idx = parse_integer(expander, allow_negative=False)
 return regs.get_skip(idx)
 alias = regs.resolve_alias(tok.name)
 if alias is not None and alias[0] == "skip":
 return regs.get_skip(alias[1])
 named = getattr(expander, "_named_params", None)
 if named is not None and regs is not None:
 entry = named.lookup(tok.name)
 if entry is not None and entry.kind == ParamKind.SKIP:
 return regs.get_skip(entry.slot, _internal=True)
 if entry is not None and entry.kind == ParamKind.MUSKIP:
 return regs.get_muskip(entry.slot, _internal=True)
 interp = getattr(expander, "_interpreter", None)
 internal = getattr(interp, "_internal_quantities", None)
 if internal is not None:
 entry = internal.lookup(tok.name)
 if entry is not None and entry.kind in (QuantityKind.SKIP, QuantityKind.MUSKIP):
 return internal.read_value(entry)
 return None


def _parse_dimen_or_fill(
 expander: Expander,
 *,
 em_sp: int,
 ex_sp: int,
) -> tuple[int, GlueOrder]:
 """Parse a dimen or an integer followed by fil/fill/filll.

 Collects all consumed tokens so it can push them back on mismatch,
 then delegates to ``parse_dimen`` for the normal case.

 Returns ``(value, GlueOrder)``.
 """
 from aspose_tex._engine.registers import GlueOrder

 consumed: list = []

 # Collect sign(s) into consumed so we can push back on fallback
 tok = _eat_spaces(expander)
 if tok is None:
 raise EngineError("Dimension or fill expected")

 sign = 1
 while isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER and tok.char in "+-":
 if tok.char == "-":
 sign = -sign
 consumed.append(tok)
 tok = _eat_spaces(expander)

 if tok is None:
 for t in reversed(consumed):
 _push_back(expander, t)
 raise EngineError("Dimension or fill expected")

 # If leading digit: try fil* detection
 if isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER and tok.char in _DEC_DIGITS:
 consumed.append(tok)
 int_digits = [tok.char]
 while True:
 nxt = _next_raw(expander)
 if isinstance(nxt, CharToken) and nxt.catcode == Catcode.OTHER and nxt.char in _DEC_DIGITS:
 int_digits.append(nxt.char)
 consumed.append(nxt)
 else:
 _push_back(expander, nxt)
 break
 integer_val = int("".join(int_digits))

 # Longest-match first
 if _scan_keyword(expander, "filll"):
 return sign * integer_val, GlueOrder.FILLL
 if _scan_keyword(expander, "fill"):
 return sign * integer_val, GlueOrder.FILL
 if _scan_keyword(expander, "fil"):
 return sign * integer_val, GlueOrder.FIL

 # Not fil* — push back everything and let parse_dimen handle it
 for t in reversed(consumed):
 _push_back(expander, t)
 val = parse_dimen(expander, em_sp=em_sp, ex_sp=ex_sp)
 return val, GlueOrder.NORMAL

 # Non-digit first token — push back sign tokens and the current token,
 # then call parse_dimen which handles signs internally
 _push_back(expander, tok)
 for t in reversed(consumed):
 _push_back(expander, t)
 val = parse_dimen(expander, em_sp=em_sp, ex_sp=ex_sp)
 return val, GlueOrder.NORMAL


def _lookup_internal_quantity(expander: Expander, name: str):
 """Return ``(kind, value)`` for an internal quantity visible to parsers."""
 from aspose_tex._engine.internal_quantities import QuantityKind

 interp = getattr(expander, "_interpreter", None)
 internal = getattr(interp, "_internal_quantities", None)
 if internal is None:
 return None
 entry = internal.lookup(name)
 if entry is None:
 return None
 value = internal.read_value(entry)
 if entry.kind == QuantityKind.INT:
 return "int", int(value)
 if entry.kind == QuantityKind.DIMEN:
 return "dimen", int(value)
 if entry.kind in (QuantityKind.SKIP, QuantityKind.MUSKIP):
 return "skip", value
 return None


def _lookup_box_dimension(expander: Expander, name: str) -> int | None:
 r"""Return a ``\wd`` / ``\ht`` / ``\dp`` dimension read when available."""
 if name not in {"wd", "ht", "dp"}:
 return None
 interp = getattr(expander, "_interpreter", None)
 box_regs = getattr(interp, "_box_regs", None)
 if box_regs is None:
 return None
 idx = parse_integer(expander, allow_negative=False)
 if name == "wd":
 return box_regs.get_wd(idx)
 if name == "ht":
 return box_regs.get_ht(idx)
 return box_regs.get_dp(idx)


def _lookup_named_parameter(expander: Expander, name: str):
 """Return ``(kind, value)`` for an integer-readable named parameter."""
 from aspose_tex._engine.named_parameters import ParamKind

 named = getattr(expander, "_named_params", None)
 regs = getattr(expander, "_register_set", None)
 if named is None or regs is None:
 return None
 entry = named.lookup(name)
 if entry is None:
 return None
 if entry.kind == ParamKind.INT:
 return "int", regs.get_count(entry.slot, _internal=True)
 if entry.kind == ParamKind.DIMEN:
 return "dimen", regs.get_dimen(entry.slot, _internal=True)
 if entry.kind == ParamKind.SKIP:
 return "skip", regs.get_skip(entry.slot, _internal=True)
 if entry.kind == ParamKind.MUSKIP:
 return "skip", regs.get_muskip(entry.slot, _internal=True)
 return None


def _is_known_unit(unit: str) -> bool:
 """Return True if ``unit`` is a known 2-letter unit or ``true<2-letter>``."""
 if unit in _UNIT_SP or unit in ("em", "ex"):
 return True
 if unit.startswith("true") and len(unit) >= 6:
 base = unit[4:]
 return base in _UNIT_SP or base in ("em", "ex")
 return False


def _read_unit(expander: Expander, first_tok) -> str:
 """Read a unit keyword from the expander (2..6 letters; §4b).

 ``first_tok`` is the already-consumed first token (may be ``None``). The
 scanner reads up to 6 LETTER/OTHER chars, then resolves to the longest
 matching unit name from the union of ``_UNIT_SP`` keys, ``{"em","ex"}``,
 and the ``true<unit>`` family. Any unconsumed characters are pushed back
 in original order. One optional trailing space is absorbed only when the
 full read matches as the unit (no leftover chars).

 Returns the lowercase unit string. Raises ``EngineError`` if no match.
 """
 tok = first_tok
 if tok is None:
 tok = _next_raw(expander)

 # Skip leading spaces
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = _next_raw(expander)

 chars: list[str] = []
 char_toks: list = []
 while (
 len(chars) < 6
 and isinstance(tok, CharToken)
 and tok.catcode in (Catcode.LETTER, Catcode.OTHER)
 ):
 chars.append(tok.char.lower())
 char_toks.append(tok)
 tok = _next_raw(expander)

 boundary = tok # may be None / SPACE / non-letter token

 if len(chars) < 2:
 if boundary is not None:
 _push_back(expander, boundary)
 for t in reversed(char_toks):
 _push_back(expander, t)
 raise EngineError("Dimension unit expected")

 # Longest-match: try lengths len(chars), len(chars)-1, ..., 2.
 for n in range(len(chars), 1, -1):
 candidate = "".join(chars[:n])
 if not _is_known_unit(candidate):
 continue
 if n < len(chars):
 # Push back boundary first (so it ends up below the leftover char
 # tokens on the stack), then leftover chars in reverse order.
 if boundary is not None:
 _push_back(expander, boundary)
 for t in reversed(char_toks[n:]):
 _push_back(expander, t)
 else:
 # Full read matched the unit — absorb one optional trailing space.
 if boundary is not None and not (
 isinstance(boundary, CharToken)
 and boundary.catcode == Catcode.SPACE
 ):
 _push_back(expander, boundary)
 return candidate

 # No prefix matched — restore stream and report.
 if boundary is not None:
 _push_back(expander, boundary)
 for t in reversed(char_toks):
 _push_back(expander, t)
 raise EngineError(f"unknown dimension unit '{''.join(chars)}'")


def _scan_keyword(expander: Expander, keyword: str) -> bool:
 """Try to consume an exact keyword (case-insensitive), eating leading spaces.

 Returns ``True`` if the keyword was fully matched and consumed (plus one
 optional trailing space). Returns ``False`` and restores the full stream
 state (all consumed tokens pushed back in original order).
 """
 consumed: list = []

 # Eat leading spaces; the first non-space is the first candidate
 tok = _eat_spaces(expander)
 if tok is None:
 return False

 current = tok

 for i, expected_char in enumerate(keyword):
 if not _char_matches(current, expected_char):
 # Mismatch: push back current and all previously consumed
 _push_back(expander, current)
 for t in reversed(consumed):
 _push_back(expander, t)
 return False

 consumed.append(current)

 # Read next character unless this was the last
 if i < len(keyword) - 1:
 current = _next_raw(expander)
 if current is None:
 for t in reversed(consumed):
 _push_back(expander, t)
 return False

 # Full keyword matched — absorb one optional trailing space
 sp = _next_raw(expander)
 if not (isinstance(sp, CharToken) and sp.catcode == Catcode.SPACE):
 _push_back(expander, sp)

 return True
