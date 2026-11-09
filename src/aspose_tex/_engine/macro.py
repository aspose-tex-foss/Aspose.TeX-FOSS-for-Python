"""Macro definition types for the TeX expansion engine.

See the project documentation for design rationale.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from aspose_tex._input.token import CharToken, ControlSequenceToken


@dataclasses.dataclass(slots=True, frozen=True)
class MacroDefinition:
    """A user-defined macro produced by \\def / \\edef / \\gdef / \\xdef.

    ``param_pattern`` describes the parameter text (TeXbook Chapter 20):

    - An ``int`` (1-9) marks a parameter position (#1 through #9).
    - A ``Token`` is a delimiter token that must appear between parameters or
      after the last parameter in the input.

    ``replacement`` describes the replacement text:

    - An ``int`` (1-9) inserts the argument bound to that parameter.
    - A ``Token`` is a literal token to be yielded.

    Example -- ``\\def\\swap#1,#2.{#2,#1.}``::

        MacroDefinition(
            param_pattern=(1, CharToken(',', Catcode.OTHER), 2, CharToken('.', Catcode.OTHER)),
            replacement=(2, CharToken(',', Catcode.OTHER), 1, CharToken('.', Catcode.OTHER)),
        )
    """

    param_pattern: tuple  # tuple[Token | int, ...]
    replacement: tuple    # tuple[Token | int, ...]
    long: bool = False    # \\long\\def: \\par allowed inside arguments
    outer: bool = False   # \\outer\\def: detection stored; enforcement deferred


@dataclasses.dataclass(frozen=True, slots=True)
class PrimitiveMeaning:
    r"""The built-in command originally named ``name``.

    ``\let\endgraf=\par`` stores ``PrimitiveMeaning("par")``: the alias keeps
    the primitive even after ``\def\par{…}`` (TeX copies ``eq_type/equiv``).

    Example::

        m = PrimitiveMeaning("par")
        assert m.name == "par"
    """

    name: str


# Meaning of a control sequence: a macro, a built-in primitive, or a token
# alias (\\let).  A CharToken alias represents \\let\\x=c; a
# ControlSequenceToken alias remains only for an undefined right-hand side.
# Using Union string form to avoid circular import at runtime.
Meaning = Union[MacroDefinition, PrimitiveMeaning, "CharToken | ControlSequenceToken"]


# Active characters share the macro table with control sequences but not their
# keys: TeX keeps them in separate hash regions (§222 active_base vs
# single_base), so plain's accent ``\~`` and its tie ``~`` are distinct.  The
# NUL prefix cannot be written as a control-sequence name in source (the
# sentinel pattern).  See.
ACTIVE_CHAR_PREFIX = "\x00active:"


def active_char_key(char: str) -> str:
    r"""Return the macro-table key holding the meaning of active character *char*.

    Args:
        char: The active character, e.g. ``"~"``.

    Returns:
        The reserved key, distinct from the key ``char`` of the control
        symbol ``\<char>`` (TeX §222).

    Example::

        active_char_key("~")   # -> "\x00active:~"
    """
    return ACTIVE_CHAR_PREFIX + char
