"""Math-mode shell primitive dispatcher.

The math shell consumes the operands of known math primitives and emits no
nodes; math atoms are built by :mod:`aspose_tex._engine.math_list`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from enum import IntEnum
from typing import TYPE_CHECKING

from aspose_tex._engine.dimparser import parse_dimen, parse_glue, parse_integer
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
    from aspose_tex._engine.code_arrays import CodeArrays
    from aspose_tex._engine.expansion import Expander
    from aspose_tex._engine.interpreter import ModeKind
    from aspose_tex._fonts.math_family_registry import MathFamilyRegistry


class MathOperandKind(IntEnum):
    """Operand pattern consumed by one math-shell primitive."""

    NONE = 0
    INT_DELIMITER = 1
    INT_MATHCHAR = 2
    DELIM = 3
    MATH_FIELD = 4
    MATHACCENT = 5
    RADICAL = 6
    DIMEN_OPERAND = 7
    MUDIMEN = 8
    MUGLUE = 9
    DELIM_DELIM = 10
    DELIM_DELIM_DIMEN = 11
    FOUR_BALANCED = 12


@dataclasses.dataclass(frozen=True, slots=True)
class _MathPrim:
    """One math-shell primitive binding."""

    name: str
    arity: MathOperandKind


_MATH_PRIMITIVES: list[_MathPrim] = [
    _MathPrim("over", MathOperandKind.NONE),
    _MathPrim("atop", MathOperandKind.NONE),
    _MathPrim("above", MathOperandKind.DIMEN_OPERAND),
    _MathPrim("overwithdelims", MathOperandKind.DELIM_DELIM),
    _MathPrim("atopwithdelims", MathOperandKind.DELIM_DELIM),
    _MathPrim("abovewithdelims", MathOperandKind.DELIM_DELIM_DIMEN),
    _MathPrim("left", MathOperandKind.DELIM),
    _MathPrim("right", MathOperandKind.DELIM),
    _MathPrim("mathopen", MathOperandKind.MATH_FIELD),
    _MathPrim("mathclose", MathOperandKind.MATH_FIELD),
    _MathPrim("mathbin", MathOperandKind.MATH_FIELD),
    _MathPrim("mathrel", MathOperandKind.MATH_FIELD),
    _MathPrim("mathop", MathOperandKind.MATH_FIELD),
    _MathPrim("mathord", MathOperandKind.MATH_FIELD),
    _MathPrim("mathpunct", MathOperandKind.MATH_FIELD),
    _MathPrim("mathinner", MathOperandKind.MATH_FIELD),
    _MathPrim("mathchoice", MathOperandKind.FOUR_BALANCED),
    _MathPrim("displaystyle", MathOperandKind.NONE),
    _MathPrim("textstyle", MathOperandKind.NONE),
    _MathPrim("scriptstyle", MathOperandKind.NONE),
    _MathPrim("scriptscriptstyle", MathOperandKind.NONE),
    _MathPrim("nonscript", MathOperandKind.NONE),
    # \limits / \nolimits / \displaylimits moved to the noad builder (
    # §E.1, TeX §1158): they set the last OP atom's limit mode and raise if it is
    # not a large operator — see MathListBuilder.add_limits.
    _MathPrim("mskip", MathOperandKind.MUGLUE),
    _MathPrim("mkern", MathOperandKind.MUDIMEN),
    _MathPrim("overline", MathOperandKind.MATH_FIELD),
    _MathPrim("underline", MathOperandKind.MATH_FIELD),
    _MathPrim("mathaccent", MathOperandKind.MATHACCENT),
    _MathPrim("radical", MathOperandKind.RADICAL),
    _MathPrim("delimiter", MathOperandKind.INT_DELIMITER),
    _MathPrim("mathchar", MathOperandKind.INT_MATHCHAR),
    _MathPrim("char", MathOperandKind.INT_MATHCHAR),
]


class MathShellRegistry:
    """Consumes known math-mode primitives without producing nodes.

    Args:
        expander: Active expander/token stream.
        code_arrays: Code arrays backing delimiter lookups.
        math_family_registry: Family-font storage surface.
        mode_provider: Callback returning the interpreter's current mode.

    Example:
        registry.dispatch_if_known("over")
    """

    __slots__ = ("_code_arrays", "_dispatch", "_expander", "_left_right_depth", "_mfr", "_mode_provider")

    def __init__(
        self,
        expander: Expander,
        code_arrays: CodeArrays,
        math_family_registry: MathFamilyRegistry,
        *,
        mode_provider: Callable[[], ModeKind] | None = None,
    ) -> None:
        self._expander = expander
        self._code_arrays = code_arrays
        self._mfr = math_family_registry
        self._mode_provider = mode_provider
        self._left_right_depth = 0
        self._dispatch = {prim.name: prim.arity for prim in _MATH_PRIMITIVES}

    @property
    def left_right_depth(self) -> int:
        """Current unmatched ``\\left`` depth."""
        return self._left_right_depth

    def knows(self, name: str) -> bool:
        """Return whether *name* is a math-shell primitive, without consuming."""
        return name in self._dispatch

    def dispatch_if_known(self, name: str) -> bool:
        """Consume operands for *name* if it is a math-shell primitive."""
        arity = self._dispatch.get(name)
        if arity is None:
            return False
        self._consume(name, arity)
        return True

    def consume_math_field(self) -> None:
        """Consume one TeX math field: a token or balanced ``{...}`` group."""
        tok = self._next_non_space()
        if tok is None:
            raise EngineError("math field expected")
        if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
            self._expander._scan_balanced_group()

    def check_left_right_balanced(self) -> None:
        """Raise if the current math formula leaves unmatched ``\\left``."""
        if self._left_right_depth != 0:
            self._left_right_depth = 0
            raise EngineError("missing \\right")

    def _consume(self, name: str, arity: MathOperandKind) -> None:
        if arity == MathOperandKind.NONE:
            return
        if arity in (MathOperandKind.INT_DELIMITER, MathOperandKind.INT_MATHCHAR):
            parse_integer(self._expander)
            return
        if arity == MathOperandKind.DELIM:
            if name == "right":
                if self._left_right_depth == 0:
                    raise EngineError("\\right without \\left")
                self._left_right_depth -= 1
            self._consume_delimiter()
            if name == "left":
                self._left_right_depth += 1
            return
        if arity == MathOperandKind.MATH_FIELD:
            self.consume_math_field()
            return
        if arity in (MathOperandKind.MATHACCENT, MathOperandKind.RADICAL):
            parse_integer(self._expander)
            self.consume_math_field()
            return
        if arity in (MathOperandKind.DIMEN_OPERAND, MathOperandKind.MUDIMEN):
            parse_dimen(self._expander)
            return
        if arity == MathOperandKind.MUGLUE:
            parse_glue(self._expander)
            return
        if arity == MathOperandKind.DELIM_DELIM:
            self._consume_delimiter()
            self._consume_delimiter()
            return
        if arity == MathOperandKind.DELIM_DELIM_DIMEN:
            self._consume_delimiter()
            self._consume_delimiter()
            parse_dimen(self._expander)
            return
        if arity == MathOperandKind.FOUR_BALANCED:
            for _ in range(4):
                self._consume_balanced_group("mathchoice")
            return

    def _consume_delimiter(self) -> None:
        tok = self._next_non_space()
        if tok is None:
            raise EngineError("math delimiter expected")
        if isinstance(tok, ControlSequenceToken):
            return
        if isinstance(tok, CharToken):
            # Touch delcode so the table is in the dispatch path.
            self._code_arrays.get_delcode(ord(tok.char))
            return
        raise EngineError("math delimiter expected")

    def _consume_balanced_group(self, name: str) -> None:
        self._expander._scan_left_brace(f"\\{name}")
        self._expander._scan_balanced_group()

    def _next_non_space(self):
        tok = self._expander._next_raw()
        while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
            tok = self._expander._next_raw()
        return tok


def _build_math_shell_registry(
    expander: Expander,
    code_arrays: CodeArrays,
    mfr: MathFamilyRegistry,
    *,
    mode_provider: Callable[[], ModeKind] | None = None,
) -> MathShellRegistry:
    """Build the math-shell registry."""
    return MathShellRegistry(expander, code_arrays, mfr, mode_provider=mode_provider)
