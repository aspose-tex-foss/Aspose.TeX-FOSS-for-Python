"""TeX math styles and the style-transition functions ( / §E).

TeX has eight math styles (display / text / script / scriptscript, each in a
normal and a *cramped* variant); the math-font size selector
:class:`~aspose_tex._fonts.math_font_parameters.MathStyle` has only three sizes
(TEXT / SCRIPT / SCRIPTSCRIPT).  This module owns the 8-to-3 collapse and the
cramped / script / fraction style transitions.

The transition functions are TeX-canonical constants from TeX:The Program §702
(`cramped_style`, `sub_style`, `sup_style`, `num_style`, `denom_style`).  They
are NOT re-derived.  uses :func:`size_of` (font-size selection) and
:func:`cramped`; :func:`sub_style` / :func:`sup_style` / :func:`num_style` /
:func:`denom_style` are defined here so (scripts / fractions) imports
them rather than re-deriving the §702 arithmetic.
"""

from __future__ import annotations

import enum

from aspose_tex._fonts.math_font_parameters import MathStyle


class TeXStyle(enum.IntEnum):
    """The eight TeX math styles (TeX:The Program §688; §E).

    The integer values match TeX's ``display_style`` … ``cramped_script_script``
    numbering: even = normal, odd = cramped; ``// 2`` selects the size tier and
    ``| 1`` makes a style cramped (the §702 arithmetic relies on this layout).
    """

    DISPLAY = 0
    DISPLAY_CRAMPED = 1
    TEXT = 2
    TEXT_CRAMPED = 3
    SCRIPT = 4
    SCRIPT_CRAMPED = 5
    SCRIPTSCRIPT = 6
    SCRIPTSCRIPT_CRAMPED = 7


def size_of(style: TeXStyle) -> MathStyle:
    """Collapse a TeX style to its math-font size tier (TeX:The Program §702).

    Display and text both select the TEXT size; the cramped variants do not
    change the size.

    Example::

        size_of(TeXStyle.DISPLAY) is MathStyle.TEXT
        size_of(TeXStyle.SCRIPT_CRAMPED) is MathStyle.SCRIPT
    """
    tier = style // 2
    if tier == 0:  # display / display-cramped → text size
        return MathStyle.TEXT
    if tier == 1:  # text / text-cramped → text size
        return MathStyle.TEXT
    if tier == 2:  # script / script-cramped → script size
        return MathStyle.SCRIPT
    return MathStyle.SCRIPTSCRIPT  # scriptscript / cramped → scriptscript size


def cramped(style: TeXStyle) -> TeXStyle:
    """Return the cramped variant of *style* (TeX:The Program §702 ``cramped_style``)."""
    return TeXStyle((style // 2) * 2 + 1)


def sub_style(style: TeXStyle) -> TeXStyle:
    """Subscript style: script size of *style*, always cramped (§702 ``sub_style``)."""
    return TeXStyle(2 * (style // 4) + 4 + 1)


def sup_style(style: TeXStyle) -> TeXStyle:
    """Superscript style: script size, crampedness preserved (§702 ``sup_style``)."""
    return TeXStyle(2 * (style // 4) + 4 + (style % 2))


def num_style(style: TeXStyle) -> TeXStyle:
    """Fraction numerator style (TeX:The Program §702 ``num_style``)."""
    return TeXStyle(style + 2 - 2 * (style // 6))


def denom_style(style: TeXStyle) -> TeXStyle:
    """Fraction denominator style: cramped numerator style (§702 ``denom_style``)."""
    return TeXStyle(2 * (style // 2) + 3 - 2 * (style // 6))
