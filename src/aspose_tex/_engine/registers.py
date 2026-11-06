"""TeX register system: storage, assignment, arithmetic, and \\the expansion.

Implements: count, dimen, skip, muskip, and toks
registers; \\advance/\\multiply/\\divide arithmetic; \\countdef/\\dimendef/\\skipdef/
\\toksdef aliases; and \\the expansion for registers.

See the project documentation for design rationale.
"""

from __future__ import annotations

import dataclasses
from enum import IntEnum
from typing import TYPE_CHECKING, Final

from aspose_tex._engine.tex_arith import print_scaled
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken, PrimitiveRefToken
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
    FIL    = 1
    FILL   = 2
    FILLL  = 3


@dataclasses.dataclass(slots=True, frozen=True)
class Glue:
    """Immutable TeX glue value (skip register content).

    All integer fields are 16.16 fixed point: scaled points for a NORMAL
    order, and 2^-16 fil (fill, filll) units for an infinite order, so
    ``1fil`` is 65536 exactly like ``\\hfil``'s built-in glue (§454, §1058).

    Example — ``3pt plus 2fil minus 1pt``::

        Glue(width=196608, stretch=131072, stretch_order=GlueOrder.FIL,
             shrink=65536, shrink_order=GlueOrder.NORMAL)
    """
    width:         int
    stretch:       int
    stretch_order: GlueOrder
    shrink:        int
    shrink_order:  GlueOrder


MAX_DIMEN: Final[int] = 0x3FFFFFFF  # 2^30 - 1 sp ~= 16383.99999pt


# ---------------------------------------------------------------------------
# Arithmetic operand resolution (§Component 2)
# ---------------------------------------------------------------------------

# ParamKind (named_parameters.py) int value -> arithmetic register family.
# Keyed by the IntEnum *value* to avoid a runtime import cycle (TOKS=5 is
# intentionally absent — token registers are not arithmetic targets).
_PARAM_KIND_FAMILY: Final[dict[int, str]] = {
    1: "count",   # ParamKind.INT
    2: "dimen",   # ParamKind.DIMEN
    3: "skip",    # ParamKind.SKIP
    4: "muskip",  # ParamKind.MUSKIP
}


@dataclasses.dataclass(slots=True, frozen=True)
class _Operand:
    """Resolution metadata for an \\advance/\\multiply/\\divide operand.

    ``internal`` selects the 256-319 named-parameter slot path; ``entry`` is the
    resolved ``NamedParameterRegistry`` entry (or None) for the post-write
    ``on_set`` mirror ( Q5-Q7).
    """
    internal: bool
    entry: object | None = None


# Shared singleton for direct-family / alias operands (internal=False).
_DIRECT_OPERAND: Final[_Operand] = _Operand(internal=False, entry=None)


# ---------------------------------------------------------------------------
# Raw storage
# ---------------------------------------------------------------------------

# User-facing register slots: 0..255 (TeX contract).
# Internal pool 256..319 reserved for NamedParameterRegistry-driven writes
# (§3a).  See _check_index / _check_internal_slot.
_NUM_REGISTERS: Final[int] = 320


class RegisterBank:
    """320-slot arrays for all five TeX register families.

    Array-based for O(1) access ( NFR-1).  No logic lives here.

    User-facing API exposes slots 0..255 (TeX contract).  Slots 256..319 are
    reserved for ``NamedParameterRegistry`` (§3a) and only reachable
    through the internal-slot code path on ``RegisterSet.set_*`` /
    ``get_*`` (``_internal=True``).
    """

    __slots__ = ("count", "dimen", "muskip", "skip", "toks")

    def __init__(self) -> None:
        _zero = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
        self.count:  list[int]         = [0] * _NUM_REGISTERS
        self.dimen:  list[int]         = [0] * _NUM_REGISTERS
        self.skip:   list[Glue]        = [_zero] * _NUM_REGISTERS
        self.muskip: list[Glue]        = [_zero] * _NUM_REGISTERS
        self.toks:   list[list[Token]] = [[] for _ in range(_NUM_REGISTERS)]


# ---------------------------------------------------------------------------
# Register set
# ---------------------------------------------------------------------------

_COUNT_MAX: Final[int] = 2**31 - 1   # max signed 32-bit integer
_COUNT_MIN: Final[int] = -(2**31)    # min signed 32-bit integer

# Register family names that map to direct array access
_DIRECT_FAMILIES: Final[frozenset[str]] = frozenset({"count", "dimen", "skip", "muskip", "toks"})
# The other command names :meth:`RegisterSet.execute` consumes.
_REGISTER_COMMANDS: Final[frozenset[str]] = frozenset({
    "advance", "multiply", "divide", "countdef", "dimendef", "skipdef",
    "muskipdef", "toksdef", "chardef", "mathchardef",
})


class RegisterSet:
    """TeX register set: implements ``RegisterProvider`` and the execution interface.

    Implements the ``RegisterProvider`` protocol (defined in ``expansion.py``)
    so it can be passed as ``register_provider`` to ``Expander``.

    Also exposes ``execute(cs_name, expander)`` for the execution layer to call
    when it encounters unexpandable register commands.

    The ``_aliases`` dict maps CS names to ``(family, index)`` tuples for
    ``\\countdef`` et al.  The clock values ``\\year`` … ``\\time`` are
    integer parameters of ``NamedParameterRegistry``, not count registers
    ( D1), so ``\\count0..9`` start at zero as in IniTeX.

    Args:
        group_stack: Shared GroupStack for save/restore, or ``None``.

    Example::

        from aspose_tex._input import StringInputSource, InputReader, CatcodeTable
        from aspose_tex._input.tokenizer import Tokenizer
        from aspose_tex._engine.expansion import Expander
        from aspose_tex._engine.registers import RegisterSet

        src      = StringInputSource(r'\\count0=42 \\the\\count0')
        reader   = InputReader(src)
        catcodes = CatcodeTable()
        tok      = Tokenizer(reader, catcodes)
        regs     = RegisterSet()
        expander = Expander(reader, tok, catcodes, register_provider=regs)
        expander._register_set = regs  # allow dimparser to resolve register values

        tokens = []
        for t in expander:
            if isinstance(t, ControlSequenceToken) and regs.execute(t.name, expander):
                continue
            tokens.append(t)
        # tokens contains CharToken('4'), CharToken('2')
    """

    def __init__(self, group_stack: GroupStack | None = None) -> None:
        self._bank = RegisterBank()
        self._aliases: dict[str, tuple[str, int]] = {}
        # \chardef / \mathchardef constants (§3c).  Distinct from
        # _aliases because the second tuple field is a frozen integer value,
        # not a register slot.
        self._constants: dict[str, tuple[str, int]] = {}
        self._group_stack = group_stack
        # Optional post-construction wiring (§5d).  Set by the
        # interpreter so that \the\catcode<n> / \the\<codename><n> can read
        # live tokenizer-domain and engine-domain code arrays, and so that
        # \the\<named-param> falls through to NamedParameterRegistry.
        self._catcodes = None
        self._code_arrays = None
        self._named_params = None
        # D2: set by the interpreter; None keeps standalone behaviour.
        self._bindings = None

    # ------------------------------------------------------------------
    # RegisterProvider protocol
    # ------------------------------------------------------------------

    def get_tokens_for_the(self, token: Token, expander: Expander) -> list[Token]:
        """Expand ``\\the <token>`` into value tokens.

        Reads additional tokens from ``expander`` when the token names a
        register family (``\\count``, ``\\dimen``, etc.) to get the index.

        Args:
            token:    The CS token immediately following ``\\the``.
            expander: The active expander (for reading register index).

        Returns:
            Character tokens for a numeric value, stored tokens for a token
            register, or the identifier control sequence for a font.

        Raises:
            EngineError: if the token does not name a readable register.
        """
        from aspose_tex._engine.dimparser import _lookup_box_dimension, parse_integer

        if not isinstance(token, ControlSequenceToken):
            raise EngineError("\\the: cannot take the value of a character token")

        name = token.name
        # D2: a register or constant owner outranks the built-in its
        # name spells; a frozen primitive reference (D3) never reaches an owner.
        owned = not isinstance(token, PrimitiveRefToken)
        if owned:
            alias = self._aliases.get(name)
            if alias is not None:
                return self._alias_tokens(*alias)
            const = self._constants.get(name)
            if const is not None:
                return _int_to_tokens(const[1])

        interp = getattr(expander, "_interpreter", None)
        fonts = getattr(interp, "_font_manager", None)
        if fonts is not None and (
            name in ("font", "textfont", "scriptfont", "scriptscriptfont")
            or (owned and fonts.is_font(name)) or name.startswith("\x00font:")
        ):
            from aspose_tex._fonts.font_manager import _resolve_font_operand

            cs_name = _resolve_font_operand(expander, token)
            from aspose_tex._input.token import FontRefToken
            return [FontRefToken(cs_name)]

        if name in ("wd", "ht", "dp"):
            value = _lookup_box_dimension(expander, name)
            if value is not None:
                return _dimen_to_tokens(value)

        if name in ('hyphenchar', 'skewchar'):
            interp = getattr(expander, '_interpreter', None)
            if interp is None:
                raise EngineError('Font integer reader: interpreter not wired')
            from aspose_tex._engine.dimparser import _lookup_font_integer
            return _int_to_tokens(_lookup_font_integer(expander, name))

        if name == "fontdimen":
            interp = getattr(expander, "_interpreter", None)
            if interp is None:
                raise EngineError("\\the\\fontdimen: interpreter not wired")
            return interp._fontdimen_tokens(expander)

        # Code-array reads (§5d).  \the\catcode<ch> returns the live
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
            return _dimen_to_tokens(self._bank.dimen[idx])

        if name == "skip":
            idx = parse_integer(expander, allow_negative=False)
            _check_index(idx)
            return _glue_to_tokens(self._bank.skip[idx])

        if name == "muskip":
            idx = parse_integer(expander, allow_negative=False)
            _check_index(idx)
            return _glue_to_tokens(self._bank.muskip[idx], "mu")

        if name == "toks":
            idx = parse_integer(expander, allow_negative=False)
            _check_index(idx)
            return list(self._bank.toks[idx])

        # InternalQuantityRegistry fallback.  This must
        # precede the historical Appendix A named-parameter placeholders for
        # page-state names such as \pagegoal and \prevdepth.
        interp = getattr(expander, "_interpreter", None)
        internal = getattr(interp, "_internal_quantities", None)
        if internal is not None:
            entry = internal.lookup(name)
            if entry is not None:
                return internal.dispatch_the(entry, expander)

        # NamedParameterRegistry fallback (§5d /).
        if self._named_params is not None:
            entry = self._named_params.lookup(name)
            if entry is not None:
                return self._named_params.dispatch_the(entry, expander)

        raise EngineError(f"\\the: cannot take the value of \\{name}")

    def _alias_tokens(self, family: str, idx: int) -> list[Token]:
        """Return the ``\\the`` tokens of register *idx* in *family*."""
        if family == "count":
            return _int_to_tokens(self._bank.count[idx])
        if family == "dimen":
            return _dimen_to_tokens(self._bank.dimen[idx])
        if family == "skip":
            return _glue_to_tokens(self._bank.skip[idx])
        if family == "muskip":
            return _glue_to_tokens(self._bank.muskip[idx], "mu")
        return list(self._bank.toks[idx])

    # ------------------------------------------------------------------
    # Execution interface
    # ------------------------------------------------------------------

    def execute(self, cs_name: str, expander: Expander, *, primitive: bool = False) -> bool:
        """Process a register command consumed from the expander stream.

        Recognised commands: ``count``, ``dimen``, ``skip``, ``muskip``, ``toks``
        (assignment); ``advance``, ``multiply``, ``divide`` (arithmetic);
        ``countdef``, ``dimendef``, ``skipdef``, ``toksdef`` (alias definition).
        Also handles assignment to previously defined aliases.

        Args:
            cs_name:   Control sequence name without backslash.
            expander:  The active expander.
            primitive: ``True`` when the name comes from a frozen primitive
                reference ( D3), which never resolves to an alias.

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

        # Alias assignment: \pageno=42  (where \pageno was defined by \countdef).
        # Checked first: an owner named \count outranks the family ( D2).
        alias = None if primitive else self._aliases.get(cs_name)
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

        # TeX shorthand_def installs relax before scanning the integer.
        if cs_name in ("countdef", "dimendef", "skipdef", "muskipdef", "toksdef",
                       "chardef", "mathchardef"):
            from contextlib import nullcontext

            from aspose_tex._engine.macro import PrimitiveMeaning
            from aspose_tex._engine.meanings import Binding, BindingKind
            target = _read_cs_name(expander)
            gs = self._group_stack
            is_global = gs is None or gs.is_global_pending
            context = (self._bindings.scanning_binding(
                target, Binding(BindingKind.MACRO, PrimitiveMeaning("relax")),
                is_global=is_global,
            ) if self._bindings is not None else nullcontext())
            try:
                with context:
                    _eat_optional_equals(expander, expanded=True)
                    value = parse_integer(expander, allow_negative=False)
                    if cs_name in ("chardef", "mathchardef"):
                        maximum = 255 if cs_name == "chardef" else 0x8000
                        if not 0 <= value <= maximum:
                            raise EngineError(f"\\{cs_name} value {value} out of range 0-{maximum}")
                        self.define_constant(target, cs_name, value, is_global=is_global)
                    else:
                        _check_index(value)
                        self.define_alias(target, cs_name[:-3], value, is_global=is_global)
            except BaseException:
                if gs is not None:
                    gs.consume_global()
                raise
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
        family, idx, operand = self._read_operand(expander)
        internal = operand.internal
        _scan_keyword(expander, "by")
        if family == "count":
            delta = parse_integer(expander)
            result = self.get_count(idx, _internal=internal) + delta
            if not (_COUNT_MIN <= result <= _COUNT_MAX):
                raise EngineError("arithmetic overflow in \\advance")
            self.set_count(idx, result, _internal=internal)
        elif family == "dimen":
            delta = parse_dimen(expander)
            result = self.get_dimen(idx, _internal=internal) + delta
            if abs(result) > MAX_DIMEN:
                raise EngineError("arithmetic overflow in \\advance")
            self.set_dimen(idx, result, _internal=internal)
        elif family in ("skip", "muskip"):
            cur = (
                self.get_skip(idx, _internal=internal)
                if family == "skip"
                else self.get_muskip(idx, _internal=internal)
            )
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
                self.set_skip(idx, new_glue, _internal=internal)
            else:
                self.set_muskip(idx, new_glue, _internal=internal)
        self._fire_operand_on_set(family, idx, operand)
        return True

    def _exec_multiply(self, expander: Expander) -> bool:
        """Execute \\multiply\\count N by V."""
        from aspose_tex._engine.dimparser import _scan_keyword, parse_integer
        family, idx, operand = self._read_operand(expander)
        internal = operand.internal
        _scan_keyword(expander, "by")
        factor = parse_integer(expander)
        if family == "count":
            result = self.get_count(idx, _internal=internal) * factor
            if not (_COUNT_MIN <= result <= _COUNT_MAX):
                raise EngineError("arithmetic overflow in \\multiply")
            self.set_count(idx, result, _internal=internal)
        elif family == "dimen":
            result = self.get_dimen(idx, _internal=internal) * factor
            if abs(result) > MAX_DIMEN:
                raise EngineError("arithmetic overflow in \\multiply")
            self.set_dimen(idx, result, _internal=internal)
        elif family in ("skip", "muskip"):
            cur = (
                self.get_skip(idx, _internal=internal)
                if family == "skip"
                else self.get_muskip(idx, _internal=internal)
            )
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
                self.set_skip(idx, new_glue, _internal=internal)
            else:
                self.set_muskip(idx, new_glue, _internal=internal)
        self._fire_operand_on_set(family, idx, operand)
        return True

    def _exec_divide(self, expander: Expander) -> bool:
        """Execute \\divide\\count N by V (truncation toward zero)."""
        from aspose_tex._engine.dimparser import _scan_keyword, parse_integer
        family, idx, operand = self._read_operand(expander)
        internal = operand.internal
        _scan_keyword(expander, "by")
        divisor = parse_integer(expander)
        if divisor == 0:
            raise EngineError("division by zero in \\divide")
        if family == "count":
            # Python truncation toward zero: int(a / b)
            self.set_count(
                idx, int(self.get_count(idx, _internal=internal) / divisor),
                _internal=internal,
            )
        elif family == "dimen":
            self.set_dimen(
                idx, int(self.get_dimen(idx, _internal=internal) / divisor),
                _internal=internal,
            )
        elif family in ("skip", "muskip"):
            cur = (
                self.get_skip(idx, _internal=internal)
                if family == "skip"
                else self.get_muskip(idx, _internal=internal)
            )
            new_glue = Glue(
                width=int(cur.width / divisor),
                stretch=int(cur.stretch / divisor),
                stretch_order=cur.stretch_order,
                shrink=int(cur.shrink / divisor),
                shrink_order=cur.shrink_order,
            )
            if family == "skip":
                self.set_skip(idx, new_glue, _internal=internal)
            else:
                self.set_muskip(idx, new_glue, _internal=internal)
        self._fire_operand_on_set(family, idx, operand)
        return True

    def _read_operand(self, expander: Expander) -> tuple[str, int, _Operand]:
        """Read \\family N or alias after \\advance/\\multiply/\\divide.

        Returns ``(family, index, operand)`` where ``operand`` carries the
        ``internal`` flag (True for a named-parameter slot 256-319, so the
        arithmetic arms pass ``_internal=True`` to the backing
        ``get_*``/``set_*``) and the resolved named-param ``entry`` (for the
        post-write ``on_set`` mirror, Q5-Q7).  Direct families /
        aliases carry ``internal=False`` / ``entry=None`` — byte-identical to
        the pre- behaviour.
        """
        from aspose_tex._engine.dimparser import parse_integer
        tok = expander.get_x_token()
        if tok is not None:
            tok = expander.primitive_token(tok)
        if not isinstance(tok, ControlSequenceToken):
            raise EngineError("\\advance/\\multiply/\\divide: register expected")
        name = tok.name
        if not isinstance(tok, PrimitiveRefToken):
            # Copied register owners outrank a primitive spelling.
            alias = self._aliases.get(name)
            if alias is not None and alias[0] != "toks":
                return alias[0], alias[1], _DIRECT_OPERAND
            # A protected macro, constant or font is not the built-in whose
            # spelling it replaced. Frozen primitive references bypass owners.
            if expander._ifx_meaning(tok) != ("prim", name):
                raise EngineError(f"\\advance/\\multiply/\\divide: \\{name} is not an arithmetic register")
        if name in _DIRECT_FAMILIES and name != "toks":
            idx = parse_integer(expander, allow_negative=False)
            _check_index(idx)
            return name, idx, _DIRECT_OPERAND
        # Named parameter (\lineskip, \baselineskip, …): arithmetic targets the
        # backing 256-319 slot.  \openup relies on this (§Component 2).
        if self._named_params is not None:
            entry = self._named_params.lookup(name)
            if entry is not None:
                family = _PARAM_KIND_FAMILY.get(entry.kind)
                if family is not None:  # TOKS → None → not arithmetic
                    return family, entry.slot, _Operand(internal=True, entry=entry)
        raise EngineError(f"\\advance/\\multiply/\\divide: \\{name} is not an arithmetic register")

    def _fire_operand_on_set(self, family: str, idx: int, operand: _Operand) -> None:
        """Fire a named parameter's ``on_set`` after an arithmetic write.

        TeX treats ``\\advance\\baselineskip`` as an assignment to
        ``\\baselineskip``; a mirror that fires on ``\\baselineskip=`` must
        fire here too ( Q7).  No-op for direct-family operands.
        """
        entry = operand.entry
        if entry is None or entry.on_set is None:
            return
        if family == "count":
            value: object = self.get_count(idx, _internal=True)
        elif family == "dimen":
            value = self.get_dimen(idx, _internal=True)
        elif family == "skip":
            value = self.get_skip(idx, _internal=True)
        else:
            value = self.get_muskip(idx, _internal=True)
        entry.on_set(value)

    # ------------------------------------------------------------------
    # Direct accessors
    # ------------------------------------------------------------------

    def get_count(self, index: int, *, _internal: bool = False) -> int:
        """Return the value of count register ``index``.

        Args:
            index:     Register index.  User-facing range is 0-255; named
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
            index:     Register index.  User-facing range is 0-255; named
                       parameters may use 256-319 via ``_internal=True``.
            value:     New value; must be in [-2^31, 2^31-1].
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
                self._group_stack.retain_global(("count", index))
            self._group_stack.consume_global()
        self._bank.count[index] = value

    def get_dimen(self, index: int, *, _internal: bool = False) -> int:
        """Return the value of dimen register ``index`` in scaled points."""
        if _internal:
            _check_internal_slot(index)
        else:
            _check_index(index)
        return self._bank.dimen[index]

    def set_dimen(self, index: int, value: int, *, _internal: bool = False, _unbounded: bool = False) -> None:
        """Set dimen register ``index`` to ``value`` scaled points.

        Saves the old value to the group stack unless the assignment is global.

        Args:
            index:      Register index.  See ``get_count`` for slot ranges.
            value:      New value; ``abs(value)`` must be ≤ MAX_DIMEN.
            _internal:  If True, accept slots 0-319 (NamedParameterRegistry path).
            _unbounded: If True, skip the MAX_DIMEN check: a value TeX computes
                itself is stored as is (§1146 ``\\predisplaysize`` may exceed it).

        Raises:
            EngineError: on range violation.
        """
        if _internal:
            _check_internal_slot(index)
        else:
            _check_index(index)
        if not _unbounded and abs(value) > MAX_DIMEN:
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
                self._group_stack.retain_global(("dimen", index))
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
                self._group_stack.retain_global(("skip", index))
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
                self._group_stack.retain_global(("muskip", index))
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
                self._group_stack.retain_global(("toks", index))
            self._group_stack.consume_global()
        self._bank.toks[index] = list(value)

    def define_alias(self, cs_name: str, family: str, index: int,
                     *, is_global: bool | None = None) -> None:
        """Register a CS name as an alias for a specific register slot.

        Saves the old alias to the group stack unless the assignment is global.

        Args:
            is_global: Captured assignment scope, or None for the current scope.
            cs_name: CS name without backslash.
            family:  One of ``"count"``, ``"dimen"``, ``"skip"``, ``"toks"``.
            index:   Register index 0-255.
        """
        _check_index(index)
        if is_global is None:
            is_global = self._group_stack is None or self._group_stack.is_global_pending
        self._release_binding(cs_name, "REGISTER", is_global=is_global)
        if self._group_stack is not None:
            if not is_global:
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
                self._group_stack.retain_global(("alias", cs_name))
            self._group_stack.consume_global()
        self._aliases[cs_name] = (family, index)

    def _release_binding(self, cs_name: str, kind: str, *, is_global: bool | None = None) -> None:
        """Clear *cs_name*'s other bindings before defining it here ( D2)."""
        bindings = self._bindings
        if bindings is None:
            return
        from aspose_tex._engine.meanings import BindingKind

        gs = self._group_stack
        bindings.release(
            cs_name, BindingKind[kind],
            is_global=(gs is None or gs.is_global_pending) if is_global is None else is_global,
        )

    def has_command(self, cs_name: str) -> bool:
        """Return whether :meth:`execute` would recognise ``cs_name``.

        Covers the register families, the arithmetic and ``\\...def`` commands
        and the names defined by ``\\countdef`` and its siblings; the
        ``\\chardef`` constants are answered by :meth:`resolve_constant`.

        Args:
            cs_name: Control sequence name without backslash.

        Returns:
            ``True`` if ``cs_name`` is a register command or register alias.
        """
        return (
            cs_name in _DIRECT_FAMILIES
            or cs_name in _REGISTER_COMMANDS
            or cs_name in self._aliases
        )

    def resolve_alias(self, cs_name: str) -> tuple[str, int] | None:
        """Return ``(family, index)`` if ``cs_name`` is a known alias, else ``None``."""
        return self._aliases.get(cs_name)

    def define_constant(self, cs_name: str, kind: str, value: int,
                        *, is_global: bool | None = None) -> None:
        """Define ``cs_name`` as a frozen integer constant.

        ``kind`` is one of ``"chardef"`` (0..255) or ``"mathchardef"``
        (0..0x8000).  The mapping is group-scoped — saved on first write per
        with namespace key ``("const", cs_name)``.

        Args:
            is_global: Captured assignment scope, or None for the current scope.
            cs_name: Control sequence name without backslash.
            kind:    ``"chardef"`` or ``"mathchardef"``.
            value:   The frozen integer value.
        """
        if is_global is None:
            is_global = self._group_stack is None or self._group_stack.is_global_pending
        self._release_binding(cs_name, "CONSTANT", is_global=is_global)
        if self._group_stack is not None:
            if not is_global:
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
                self._group_stack.retain_global(("const", cs_name))
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


def _eat_optional_equals(expander: Expander, *, expanded: bool = False) -> None:
    """Skip optional spaces and one optional '=' token."""
    next_token = expander.get_x_token if expanded else expander._next_raw
    tok = next_token()
    while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
        tok = next_token()
    if isinstance(tok, CharToken) and tok.char == "=" and tok.catcode == Catcode.OTHER:
        # Skip one optional space after '='
        nxt = next_token()
        if nxt is not None and not (isinstance(nxt, CharToken) and nxt.catcode == Catcode.SPACE):
            expander._stack.append(nxt)
    elif tok is not None:
        expander._stack.append(tok)


def _read_cs_name(expander: Expander) -> str:
    """Read an unexpanded shorthand target, including an active name (§1215)."""
    tok = expander._next_raw()
    while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
        tok = expander._next_raw()
    if isinstance(tok, CharToken) and tok.catcode == Catcode.ACTIVE:
        from aspose_tex._engine.macro import active_char_key

        return active_char_key(tok.char)
    if not isinstance(tok, ControlSequenceToken):
        raise EngineError(f"Control sequence expected, got {tok!r}")
    return tok.name


def _read_toks_value(expander: Expander) -> list[Token]:
    """Read a brace-delimited token list for \\toks assignment."""
    expander._scan_left_brace("\\toks value")
    return expander._scan_balanced_group()


def _int_to_tokens(value: int) -> list[Token]:
    """Convert an integer to a list of Catcode.OTHER CharTokens (decimal string)."""
    return [CharToken(c, Catcode.OTHER) for c in str(value)]


def _dimen_to_tokens(sp: int) -> list[Token]:
    """Return ``\\the``'s text for a dimension: §103 ``print_scaled`` + ``pt``.

    Example::

        _dimen_to_tokens(655360)   # -> the characters of "10.0pt"
    """
    return [CharToken(c, Catcode.OTHER) for c in f"{print_scaled(sp)}pt"]


def _glue_to_tokens(glue: Glue, unit: str = "pt") -> list[Token]:
    """Return ``\\the``'s text for glue, as §178 ``print_spec`` writes it.

    Args:
        glue: the glue value; finite components are in 2^-16 ``unit``.
        unit: ``"pt"`` for a skip, ``"mu"`` for a muskip.

    A ``plus``/``minus`` part is printed only when its amount is non-zero,
    whatever its order, so ``0pt plus 0fil`` prints as ``0.0pt``.

    Example::

        _glue_to_tokens(Glue(65536, 131072, GlueOrder.FIL, 0, GlueOrder.NORMAL))
        # -> the characters of "1.0pt plus 2.0fil"
    """
    parts: list[str] = [f"{print_scaled(glue.width)}{unit}"]
    if glue.stretch != 0:
        parts.append(f"plus {_print_glue(glue.stretch, glue.stretch_order, unit)}")
    if glue.shrink != 0:
        parts.append(f"minus {_print_glue(glue.shrink, glue.shrink_order, unit)}")
    text = " ".join(parts)
    return [CharToken(c, Catcode.SPACE if c == " " else Catcode.OTHER) for c in text]


def _print_glue(value: int, order: GlueOrder, unit: str) -> str:
    """§177 ``print_glue``: a stretch or shrink amount with its order or unit.

    Infinite orders are stored in 2^-16 fil units (§454), so ``plus 2fil``
    prints as ``2.0fil``.
    """
    suffix = unit if order == GlueOrder.NORMAL else ["", "fil", "fill", "filll"][int(order)]
    return f"{print_scaled(value)}{suffix}"
