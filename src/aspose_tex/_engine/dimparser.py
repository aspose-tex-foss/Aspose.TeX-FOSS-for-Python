"""Dimension and glue parsing from the TeX token stream.

Implements: conversion of textual dimension
and glue specifications into internal scaled-point values.

See the project documentation for design rationale.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from aspose_tex._engine.tex_arith import UNITY, round_decimals, xn_over_d, xn_over_d_remainder
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken, PrimitiveRefToken
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
    from aspose_tex._engine.expansion import Expander
    from aspose_tex._engine.registers import Glue, GlueOrder


# ---------------------------------------------------------------------------
# Unit conversion table  (TeX §458 ``set_conversion``: 1 unit = num/denom pt)
# The ratio is applied to the scanned number and its 2^-16 fraction together,
# never to a pre-rounded sp-per-unit constant — that would multiply the
# rounding error of the constant by the integer part.
# ---------------------------------------------------------------------------

_UNIT_CONVERSION: Final[dict[str, tuple[int, int]]] = {
    "pt": (1, 1),
    # §4d / — math unit, accepted in muglue specs (\thinmuskip
    # etc.); §456 attaches its fraction exactly as for pt.
    "mu": (1, 1),
    "pc": (12, 1),
    "in": (7227, 100),
    "cm": (7227, 254),
    "mm": (7227, 2540),
    "bp": (7227, 7200),
    "dd": (1238, 1157),
    "cc": (14856, 1157),
}

# ``sp`` takes the integer as-is and drops any fraction (§458 ``goto done``).
_FIXED_UNITS: Final[frozenset[str]] = frozenset(_UNIT_CONVERSION) | {"sp"}


_DEC_DIGITS: Final[frozenset[str]] = frozenset("0123456789")
_OCT_DIGITS: Final[frozenset[str]] = frozenset("01234567")
_HEX_DIGITS: Final[frozenset[str]] = frozenset("0123456789ABCDEFabcdef")


# ---------------------------------------------------------------------------
# Internal helpers — thin wrappers around private Expander state
# ---------------------------------------------------------------------------

def _next_raw(expander: Expander):
    """Pull the next raw token from the expander."""
    return expander._next_raw()


def _next_x(expander: Expander):
    """Pull the next token after expansion (TeX ``get_x_token``, §380).

    Every scanner here reads this way, as TeX's ``scan_int`` (§440),
    ``scan_dimen`` (§448) and ``scan_keyword`` (§407) do, so a macro in front
    of or inside a number expands to its digits.
    """
    return expander.get_x_token()


def _push_back(expander: Expander, tok) -> None:
    """Push a single token back onto the expander stack."""
    if tok is not None:
        expander._stack.append(tok)


def _primitive_token(expander: Expander, tok):
    """Return *tok* as the primitive a ``\\let`` alias of one means.

    ``get_x_token`` hands such an alias back as read, so after
    ``\\let\\cnt=\\count`` the text ``\\cnt5`` reaches a scanner as ``\\cnt``;
    scanners dispatch on the result and push back the original.
    """
    if tok is None or not hasattr(expander, "primitive_token"):
        return tok
    return expander.primitive_token(tok)


def _register_owner(regs, tok) -> tuple[str, int] | None:
    r"""Return the ``(family, index)`` register owner *tok* names, if any.

    a ``\countdef``-style owner outranks the built-in its name
    spells, so ``\countdef\count=1`` makes ``\count`` read register 1 with no
    index; a frozen primitive reference (D3) never resolves to an owner.
    """
    if isinstance(tok, PrimitiveRefToken):
        return None
    return regs.resolve_alias(tok.name)


def _is_space(expander: Expander, tok) -> bool:
    """Return whether *tok* is a space token, explicit or implicit.

    TeX tests ``cur_cmd = spacer`` (§443, §455), so a control sequence or an
    active character ``\\let`` to a space counts, as ``get_x_token`` hands it
    back as the alias.
    """
    if tok is None:
        return False
    if isinstance(tok, CharToken) and tok.catcode != Catcode.ACTIVE:
        return tok.catcode == Catcode.SPACE
    meaning = expander._ifx_meaning(tok)
    return isinstance(meaning, tuple) and meaning[0] == "char" and meaning[2] == Catcode.SPACE


def _eat_spaces(expander: Expander):
    """Consume leading space tokens; return first non-space token (or None)."""
    tok = _next_x(expander)
    while _is_space(expander, tok):
        tok = _next_x(expander)
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
    Absorbs one optional trailing space.  Tokens are read with expansion
    (``get_x_token``, §440), so a macro may supply any part of the number;
    an assignment command such as ``\\def`` ends it unexecuted.

    Args:
        expander:       The active expander to read tokens from.
        allow_negative: If ``False``, a leading ``-`` raises ``EngineError``.

    Returns:
        The parsed integer value.

    Raises:
        EngineError: on malformed input or missing digits.

    Example::

        # Stream '"FF ':
        parse_integer(expander)   # -> 255
        # Stream "\\x7 " after \\def\\x{1} — the macro supplies a digit:
        parse_integer(expander)   # -> 17
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

    # CS token → register lookup; a \let alias reads as its primitive.
    read = _primitive_token(expander, tok)
    if isinstance(read, ControlSequenceToken):
        name = read.name
        if name in ('hyphenchar', 'skewchar'):
            return sign * _lookup_font_integer(expander, name)
        regs = getattr(expander, "_register_set", None)
        if regs is not None:
            alias = _register_owner(regs, read)
            if alias is not None and alias[0] == "count":
                return sign * regs.get_count(alias[1])
            if alias is not None and alias[0] == "dimen":
                return sign * regs.get_dimen(alias[1])
            if alias is None and name == "count":
                idx = parse_integer(expander, allow_negative=False)
                return sign * regs.get_count(idx)
            if alias is None and name == "dimen":
                idx = parse_integer(expander, allow_negative=False)
                return sign * regs.get_dimen(idx)
            # \chardef / \mathchardef constants are integer-readable
            # (§3c).  Used by patterns like
            # ``\catcode`\~=\active`` (plain.tex line 19).  A frozen
            # primitive is not the constant that later took its name.
            const = None if isinstance(read, PrimitiveRefToken) else regs.resolve_constant(name)
            if const is not None:
                return sign * const[1]
        box_dim = _lookup_box_dimension(expander, name)
        if box_dim is not None:
            return sign * box_dim
        font_dim = _lookup_fontdimen(expander, name)
        if font_dim is not None:
            return sign * font_dim
        # TeX §440 lowers internal glue to its width in integer context.
        glue = _lookup_glue_value(expander, read)
        if glue is not None:
            return sign * glue.width
        internal = _lookup_internal_quantity(expander, name)
        if internal is not None and internal[0] in ("int", "dimen"):
            return sign * int(internal[1])
        named = _lookup_named_parameter(expander, name)
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
            nxt = _next_x(expander)
            if isinstance(nxt, CharToken) and nxt.catcode == Catcode.OTHER and nxt.char in _DEC_DIGITS:
                digits.append(nxt.char)
            elif _is_space(expander, nxt):
                break
            else:
                _push_back(expander, nxt)
                break
        return sign * int("".join(digits))

    if char == "'":
        digits = []
        while True:
            nxt = _next_x(expander)
            if isinstance(nxt, CharToken) and nxt.catcode == Catcode.OTHER and nxt.char in _OCT_DIGITS:
                digits.append(nxt.char)
            elif _is_space(expander, nxt):
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
            nxt = _next_x(expander)
            if (
                isinstance(nxt, CharToken)
                and nxt.catcode in (Catcode.OTHER, Catcode.LETTER)
                and nxt.char in _HEX_DIGITS
            ):
                digits.append(nxt.char)
            elif _is_space(expander, nxt):
                break
            else:
                _push_back(expander, nxt)
                break
        if not digits:
            raise EngineError('Number expected after "')
        return sign * int("".join(digits), 16)

    if char == "`":
        # §442: the character after ` is read without expansion.
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
        sp = _next_x(expander)
        if not _is_space(expander, sp):
            _push_back(expander, sp)
        return sign * val

    _push_back(expander, tok)
    raise EngineError("Number expected")


def parse_dimen(
    expander: Expander,
    *,
    em_sp: int | None = None,
    ex_sp: int | None = None,
    allow_negative: bool = True,
) -> int:
    """Read a TeX dimension from the expander token stream.

    Parses: ``[sign] <number>[.<frac>] <unit>``

    The decimal fraction is first rounded to 2^-16 (§452 ``round_decimals``).
    Fixed units then follow TeX §458: the number and its fraction are scaled
    together by the unit's exact ``num/denom`` ratio in points, so ``.3pt`` is
    19661 sp and ``.33333in`` is 1578738 sp, as in TeX; ``sp`` drops the
    fraction.  ``true`` units are first divided by ``\\mag/1000`` the same way
    (§457).  ``em``/``ex`` and internal dimensions used as units (``.5\\hsize``)
    follow §455: ``sp = int_part * v + xn_over_d(v, f, 2^16)``, where ``v`` is
    the current font's quad or x-height, or the dimension's value.

    Args:
        expander:       The active expander to read tokens from.
        em_sp:          Override for 1em in sp.  ``None`` (the default) reads
                        ``\\fontdimen6`` of the current font at scan time (§455).
        ex_sp:          Override for 1ex in sp.  ``None`` (the default) reads
                        ``\\fontdimen5`` of the current font at scan time (§455).
        allow_negative: If ``False``, a leading ``-`` raises ``EngineError``.

    Returns:
        The dimension in scaled points.

    Raises:
        EngineError: on overflow, unknown unit, or malformed input.

    Example::

        # Stream "1em " with cmr7 (plain's \\sevenrm) as the current font:
        parse_dimen(expander)              # -> 522469, cmr7's \\fontdimen6
        # Stream "2em " with an explicit override (no font lookup):
        parse_dimen(expander, em_sp=100)   # -> 200
        # Stream ".33333in " (§458, MiKTeX-exact):
        parse_dimen(expander)              # -> 1578738
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

    # \dimen N or alias as a dimension source; a \let alias reads as its primitive.
    read = _primitive_token(expander, tok)
    if isinstance(read, ControlSequenceToken):
        name = read.name
        regs = getattr(expander, "_register_set", None)
        if regs is not None:
            alias = _register_owner(regs, read)
            if alias is None and name == "dimen":
                idx = parse_integer(expander, allow_negative=False)
                return sign * regs.get_dimen(idx)
            if alias is not None and alias[0] == "dimen":
                return sign * regs.get_dimen(alias[1])
        glue = _lookup_glue_value(expander, read)
        if glue is not None:
            return sign * glue.width
        box_dim = _lookup_box_dimension(expander, name)
        if box_dim is not None:
            return sign * box_dim
        font_dim = _lookup_fontdimen(expander, name)
        if font_dim is not None:
            return sign * font_dim
        internal = _lookup_internal_quantity(expander, name)
        if internal is not None:
            kind, value = internal
            if kind == "dimen":
                return sign * int(value)
            if kind == "skip":
                return sign * value.width
        named = _lookup_named_parameter(expander, name)
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
            nxt = _next_x(expander)
            if isinstance(nxt, CharToken) and nxt.catcode == Catcode.OTHER and nxt.char in _DEC_DIGITS:
                int_digits.append(nxt.char)
            else:
                tok = nxt
                break
        int_part = int("".join(int_digits))
    elif isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER and tok.char in ".,":
        # Leading decimal point — consume frac digits immediately
        int_part = 0
        while True:
            nxt = _next_x(expander)
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
    if isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER and tok.char in ".,":
        while True:
            nxt = _next_x(expander)
            if isinstance(nxt, CharToken) and nxt.catcode == Catcode.OTHER and nxt.char in _DEC_DIGITS:
                frac_digits.append(nxt.char)
            else:
                tok = nxt
                break

    return _finish_dimen(expander, sign, int_part, frac_digits, tok, em_sp, ex_sp, MAX_DIMEN)


def _finish_dimen(expander, sign, int_part, frac_digits, unit_first_tok, em_sp, ex_sp, max_dimen):
    """Convert integer+fraction+unit into scaled points and apply sign.

    Follows TeX §453-§458 on the unsigned number: the fraction ``f`` is the
    §452 ``round_decimals`` of ``frac_digits`` (2^-16 units), and every unit
    then scales the pair ``(int_part, f)`` exactly.

    ``true*`` units (FR-16 / §4a) divide the pair by ``mag/1000``
    before the unit is applied (§457), so that the later ``mag/1000``
    document magnification cancels back out.  ``mag`` is read live from
    ``NamedParameterRegistry`` via the expander's ``_named_params`` /
    ``_register_set`` attributes; absent the registry (e.g. unit-test
    pipelines) it defaults to 1000 (true* == plain).
    """
    f = round_decimals(frac_digits)

    dimen_unit_sp = _lookup_dimension_unit(expander, unit_first_tok)
    if dimen_unit_sp is not None:
        # §455 found: nx_plus_y(cur_val, v, xn_over_d(v, f, 2^16)).
        sp = int_part * dimen_unit_sp + xn_over_d(dimen_unit_sp, f, UNITY)
        return sign * _check_dimen(sp, max_dimen)

    unit = _read_unit(expander, unit_first_tok)
    is_true = unit.startswith("true") and len(unit) >= 6
    base_unit = unit[4:] if is_true else unit

    if base_unit in ("em", "ex"):
        if base_unit == "em":
            v = em_sp if em_sp is not None else _current_font_dimen(expander, _QUAD)
        else:
            v = ex_sp if ex_sp is not None else _current_font_dimen(expander, _X_HEIGHT)
        sp = int_part * v + xn_over_d(v, f, UNITY)
        if is_true:
            sp = sp * 1000 // _lookup_mag(expander)
        return sign * _check_dimen(sp, max_dimen)
    if base_unit not in _FIXED_UNITS:
        raise EngineError(f"unknown dimension unit '{unit}'")

    if is_true:
        mag = _lookup_mag(expander)
        if mag != 1000:
            int_part, f = _scale_fraction(int_part, f, 1000, mag)

    if base_unit == "sp":
        sp = int_part
    else:
        num, denom = _UNIT_CONVERSION[base_unit]
        int_part, f = _scale_fraction(int_part, f, num, denom)
        sp = int_part * UNITY + f

    return sign * _check_dimen(sp, max_dimen)


def _scale_fraction(whole: int, f: int, num: int, denom: int) -> tuple[int, int]:
    """Scale the fixed-point number ``whole + f/2^16`` by ``num/denom``.

    TeX §457/§458: ``cur_val := xn_over_d(cur_val, num, denom)``, then the
    remainder joins the fraction, ``f := (num*f + 2^16*remainder) div denom``,
    and any carry past 2^16 moves back into the whole part.
    """
    whole, remainder = xn_over_d_remainder(whole, num, denom)
    f = (num * f + UNITY * remainder) // denom
    return whole + f // UNITY, f % UNITY


def _check_dimen(sp: int, max_dimen: int) -> int:
    """Reject a dimension at or beyond 2^30 sp (§448 ``attach_sign``)."""
    if abs(sp) > max_dimen:
        raise EngineError(f"dimension {sp}sp exceeds TeX maximum")
    return sp


_X_HEIGHT: Final[int] = 5
_QUAD: Final[int] = 6


def _current_font_dimen(expander: Expander, index: int) -> int:
    r"""Return ``\fontdimen<index>`` of the current font (§455 ``cur_font``).

    ``em``/``ex`` are read at scan time, so ``\sevenrm\quad`` sees cmr7's quad.
    With no font selected — or no font manager wired, as in bare parser
    pipelines — the current font is ``\nullfont``, whose parameters are all 0.
    """
    interp = getattr(expander, "_interpreter", None)
    font_manager = getattr(interp, "_font_manager", None)
    if font_manager is None:
        return 0
    cs = font_manager.current_font_id
    return font_manager.fontdimen(cs if cs is not None else font_manager._nullfont_id, index)


def _lookup_dimension_unit(expander: Expander, tok) -> int | None:
    """Return the scaled-point unit for ``<number><dimen-register>`` forms."""
    tok = _primitive_token(expander, tok)
    if not isinstance(tok, ControlSequenceToken):
        return None
    regs = getattr(expander, "_register_set", None)
    if regs is not None:
        unit: int | None = None
        alias = _register_owner(regs, tok)
        if alias is None and tok.name == "dimen":
            idx = parse_integer(expander, allow_negative=False)
            unit = regs.get_dimen(idx)
        elif alias is not None and alias[0] == "dimen":
            unit = regs.get_dimen(alias[1])
        if unit is not None:
            sp = _next_x(expander)
            if not _is_space(expander, sp):
                _push_back(expander, sp)
            return unit
    # TeX §455: any <internal dimen> is a unit, so `.5\wd0` and
    # `-.5\fontdimen2\font` scale the box/font dimension like a register.
    glue = _lookup_glue_value(expander, tok)
    if glue is not None:
        return glue.width
    box_dim = _lookup_box_dimension(expander, tok.name)
    if box_dim is not None:
        return box_dim
    font_dim = _lookup_fontdimen(expander, tok.name)
    if font_dim is not None:
        return font_dim
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
    em_sp: int | None = None,
    ex_sp: int | None = None,
) -> Glue:
    """Read a TeX glue specification from the expander token stream.

    Grammar::

        <glue> ::= <dimen> [plus <dimen_or_fill> [minus <dimen_or_fill>]]

        <dimen_or_fill> ::= <dimen> | <decimal> fil[l[l]]

    Args:
        expander: The active expander to read tokens from.
        em_sp:    Override for 1em in sp; ``None`` reads the current font's
                  ``\\fontdimen6`` (§455).
        ex_sp:    Override for 1ex in sp; ``None`` reads the current font's
                  ``\\fontdimen5`` (§455).

    Returns:
        A ``Glue`` value.

    Raises:
        EngineError: on malformed input or dimension overflow.

    Example::

        # Stream "1em plus 2em minus 1ex" with cmr7 as the current font —
        # every component reads the same font:
        parse_glue(expander)   # -> Glue(522469, stretch=1044938, shrink=197518)
        # Stream "0pt plus 2fil" — fil units use \\hfil's 2^16 scale (§454):
        parse_glue(expander)   # -> Glue(0, stretch=131072, stretch_order=FIL, ...)
        # Stream "0pt minus 1.5fill" — a fraction attaches as for pt (§452):
        parse_glue(expander)   # -> Glue(0, shrink=98304, shrink_order=FILL, ...)
    """
    from aspose_tex._engine.registers import Glue, GlueOrder

    tok = _eat_spaces(expander)
    sign = 1
    while isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER and tok.char in "+-":
        if tok.char == "-":
            sign = -sign
        tok = _eat_spaces(expander)
    direct = _lookup_glue_value(expander, tok)
    if direct is not None:
        sp = _next_x(expander)
        if not _is_space(expander, sp):
            _push_back(expander, sp)
        # §461: the sign applies to the whole internal glue, preserving orders.
        return Glue(sign * direct.width, sign * direct.stretch, direct.stretch_order,
                    sign * direct.shrink, direct.shrink_order)
    _push_back(expander, tok)

    width = sign * parse_dimen(expander, em_sp=em_sp, ex_sp=ex_sp)

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

    tok = _primitive_token(expander, tok)
    if not isinstance(tok, ControlSequenceToken):
        return None
    regs = getattr(expander, "_register_set", None)
    if regs is not None:
        alias = _register_owner(regs, tok)
        if alias is None and tok.name == "skip":
            idx = parse_integer(expander, allow_negative=False)
            return regs.get_skip(idx)
        if alias is None and tok.name == "muskip":
            # \mskip\muskip0 keeps the register's stretch and shrink.
            idx = parse_integer(expander, allow_negative=False)
            return regs.get_muskip(idx)
        if alias is not None and alias[0] == "skip":
            return regs.get_skip(alias[1])
        if alias is not None and alias[0] == "muskip":
            return regs.get_muskip(alias[1])
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
    em_sp: int | None,
    ex_sp: int | None,
) -> tuple[int, GlueOrder]:
    """Parse a dimen or a decimal constant followed by fil/fill/filll.

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

    # If a decimal constant leads: try fil* detection
    if isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER and tok.char in _DEC_DIGITS | {".", ","}:
        consumed.append(tok)
        int_digits = [tok.char] if tok.char not in ".," else []
        frac_digits: list[str] = []
        digits = int_digits if tok.char not in ".," else frac_digits
        while True:
            nxt = _next_x(expander)
            if isinstance(nxt, CharToken) and nxt.catcode == Catcode.OTHER and nxt.char in _DEC_DIGITS:
                digits.append(nxt.char)
                consumed.append(nxt)
            elif (
                isinstance(nxt, CharToken) and nxt.catcode == Catcode.OTHER
                and nxt.char in ".," and digits is int_digits
            ):
                digits = frac_digits
                consumed.append(nxt)
            else:
                _push_back(expander, nxt)
                break
        # §454 attaches fil units like pt: ``cur_val * unity + f`` (§452
        # ``round_decimals``), so ``1fil`` equals the 65536 of ``\hfil``'s
        # built-in glue (§1058) and ``1.5fil`` is 98304.
        from aspose_tex._engine.registers import MAX_DIMEN

        fil_val = sign * (int("".join(int_digits) or "0") * UNITY + round_decimals(frac_digits))

        # Longest-match first
        if _scan_keyword(expander, "filll"):
            return _check_dimen(fil_val, MAX_DIMEN), GlueOrder.FILLL
        if _scan_keyword(expander, "fill"):
            return _check_dimen(fil_val, MAX_DIMEN), GlueOrder.FILL
        if _scan_keyword(expander, "fil"):
            return _check_dimen(fil_val, MAX_DIMEN), GlueOrder.FIL

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


def _lookup_font_integer(expander: Expander, name: str) -> int:
    """Read a per-font integer from the active scanner, including subexpanders."""
    from aspose_tex._fonts.font_manager import scan_font_id

    manager = expander._interpreter._font_manager
    return getattr(manager, name)(scan_font_id(expander))


def _lookup_fontdimen(expander: Expander, name: str) -> int | None:
    r"""Return a ``\fontdimen<n><font>`` value as an ``<internal dimen>`` (§E).

    Recognises the control sequence ``\fontdimen`` in ``<internal dimen>``
    position (e.g. ``\kern\fontdimen1\font``).  Parses ``<n>`` then resolves the
    ``<font>`` operand — ``\font`` (current font), a ``\font``-defined CS, or
    ``\nullfont`` — via the shared :func:`resolve_font_cs` resolver, and returns
    the fontdimen value in scaled points.  Returns ``None`` for any other name so
    the caller falls through to the remaining ``<internal dimen>`` arms.
    """
    if name != "fontdimen":
        return None
    interp = getattr(expander, "_interpreter", None)
    font_manager = getattr(interp, "_font_manager", None)
    if font_manager is None:
        return None
    from aspose_tex._fonts.font_manager import scan_font_id

    n = parse_integer(expander, allow_negative=False)
    font_cs = scan_font_id(expander)
    return font_manager.fontdimen(font_cs, n)


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


_ALL_UNITS: Final[frozenset[str]] = frozenset(
    {*_FIXED_UNITS, "em", "ex"} | {"true" + u for u in (*_FIXED_UNITS, "em", "ex")}
)
_UNIT_PREFIXES: Final[frozenset[str]] = frozenset(
    u[:n] for u in _ALL_UNITS for n in range(1, len(u) + 1)
)


def _is_known_unit(unit: str) -> bool:
    """Return True if ``unit`` is a known 2-letter unit or ``true<2-letter>``."""
    if unit in _FIXED_UNITS or unit in ("em", "ex"):
        return True
    if unit.startswith("true") and len(unit) >= 6:
        base = unit[4:]
        return base in _FIXED_UNITS or base in ("em", "ex")
    return False


def _read_unit(expander: Expander, first_tok) -> str:
    """Read a unit keyword from the expander (2..6 letters; §4b).

    ``first_tok`` is the already-consumed first token (may be ``None``).  The
    scanner reads LETTER/OTHER chars (with expansion) only while they remain a
    prefix of a unit from ``_FIXED_UNITS``, ``{"em","ex"}`` or the
    ``true<unit>`` family, so it never reads past a complete unit.  One
    optional trailing space is then absorbed (§443).  On failure every read
    token is pushed back in original order.

    Returns the lowercase unit string.  Raises ``EngineError`` if no match.
    """
    tok = first_tok
    if tok is None:
        tok = _next_x(expander)

    # Skip leading spaces
    while _is_space(expander, tok):
        tok = _next_x(expander)

    chars: list[str] = []
    char_toks: list = []
    # Read only while the letters can still grow into a unit, as TeX's
    # keyword-by-keyword scan does (§407/§453): a macro after a complete
    # ``pt`` is expanded just once, for the optional-space check (§443).
    while (
        isinstance(tok, CharToken)
        and tok.catcode in (Catcode.LETTER, Catcode.OTHER)
        and "".join(chars) + tok.char.lower() in _UNIT_PREFIXES
    ):
        chars.append(tok.char.lower())
        char_toks.append(tok)
        tok = _next_x(expander)

    boundary = tok  # may be None / SPACE / non-letter token
    unit = "".join(chars)

    if _is_known_unit(unit):
        # §443: absorb one optional trailing space.
        if boundary is not None and not (
            _is_space(expander, boundary)
        ):
            _push_back(expander, boundary)
        return unit

    # Not a unit — restore the stream and report what was read.
    if isinstance(boundary, CharToken) and boundary.catcode in (Catcode.LETTER, Catcode.OTHER):
        unit += boundary.char.lower()
    if boundary is not None:
        _push_back(expander, boundary)
    for t in reversed(char_toks):
        _push_back(expander, t)
    if not unit:
        raise EngineError("Dimension unit expected")
    raise EngineError(f"unknown dimension unit '{unit}'")


def _scan_keyword(expander: Expander, keyword: str) -> bool:
    """Try to consume an exact keyword (case-insensitive), eating leading spaces.

    Returns ``True`` if the keyword was fully matched and consumed (plus one
    optional trailing space).  Returns ``False`` and restores the full stream
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
            current = _next_x(expander)
            if current is None:
                for t in reversed(consumed):
                    _push_back(expander, t)
                return False

    # Full keyword matched — absorb one optional trailing space
    sp = _next_x(expander)
    if not _is_space(expander, sp):
        _push_back(expander, sp)

    return True
