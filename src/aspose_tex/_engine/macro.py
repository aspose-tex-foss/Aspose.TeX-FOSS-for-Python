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

 param_pattern: tuple # tuple[Token | int, ...]
 replacement: tuple # tuple[Token | int, ...]
 long: bool = False # \\long\\def: \\par allowed inside arguments
 outer: bool = False # \\outer\\def: detection stored; enforcement deferred


# Meaning of a control sequence: either a macro or a token alias (\\let).
# A ControlSequenceToken alias represents a primitive or macro alias.
# A CharToken alias represents \\let\\x=c (char token alias).
# Using Union string form to avoid circular import at runtime.
Meaning = Union[MacroDefinition, "CharToken | ControlSequenceToken"]
