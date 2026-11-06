"""TeX math-font sigma /xi parameter provider (, §A/B/C).

Promotes the M3 "stored CS only" :class:`MathFamilyRegistry` into a
real metrics provider.  Reads the 22 math-symbol parameters (sigma 1…sigma 22, family 2)
and the 6 math-extension parameters (xi 8…xi 13, family 3) by name, selecting the
``\\textfont`` / ``\\scriptfont`` / ``\\scriptscriptfont`` slot by the current
:class:`MathStyle`.

The sigma /xi index → name maps below are TeX-canonical constants from
TeX:The Program §700 (`mathsy`), §701 (`mathex`), and §702 (style selection).
They are NOT derived — they match §A verbatim and are the single
source of truth for the generated accessors.
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
    from aspose_tex._fonts.font_manager import FontManager
    from aspose_tex._fonts.font_metrics import FontMetrics
    from aspose_tex._fonts.math_family_registry import MathFamilyRegistry


class MathStyle(enum.Enum):
    """Math size selector for sigma /xi parameter resolution (§A, §702).

    maps its eight TeXbook styles (display/text/script/scriptscript and
    their primed/cramped variants) down to these three sizes; display and text
    both select the TEXT size.  This module only requires the three-valued
    size selector.
    """

    TEXT = "text"
    SCRIPT = "script"
    SCRIPTSCRIPT = "scriptscript"


# sigma -parameters — math symbol font, family 2 (TeX:The Program §700; §A).
# Index is the 1-based \fontdimen index.  sigma 5/sigma 6 alias the standard text params
# 5/6 of the symbol font (math_x_height / math_quad).
_SIGMA_PARAMS: dict[str, int] = {
    "math_x_height": 5,
    "math_quad": 6,
    "num1": 8,
    "num2": 9,
    "num3": 10,
    "denom1": 11,
    "denom2": 12,
    "sup1": 13,
    "sup2": 14,
    "sup3": 15,
    "sub1": 16,
    "sub2": 17,
    "sup_drop": 18,
    "sub_drop": 19,
    "delim1": 20,
    "delim2": 21,
    "axis_height": 22,
}

# xi -parameters — math extension font, family 3 (TeX:The Program §701; §A).
_XI_PARAMS: dict[str, int] = {
    "default_rule_thickness": 8,
    "big_op_spacing1": 9,
    "big_op_spacing2": 10,
    "big_op_spacing3": 11,
    "big_op_spacing4": 12,
    "big_op_spacing5": 13,
}

# Validity gates (§C, TeX:The Program §700/§701/§1195).
_SYMBOL_FAMILY = 2
_EXTENSION_FAMILY = 3
_SYMBOL_MIN_PARAMS = 22
_EXTENSION_MIN_PARAMS = 13

# Role name per style, for the FR-4 diagnostic ("\\textfont 2 is ...").
_STYLE_ROLE: dict[MathStyle, str] = {
    MathStyle.TEXT: "textfont",
    MathStyle.SCRIPT: "scriptfont",
    MathStyle.SCRIPTSCRIPT: "scriptscriptfont",
}


class MathFontParameters:
    """Resolves sigma /xi math-font parameters by name and math style (§B).

    sigma accessors read ``\\textfont2`` / ``\\scriptfont2`` / ``\\scriptscriptfont2``;
    xi accessors read the family-3 equivalents — both selected by the
    :class:`MathStyle` argument.  Every accessor returns scaled points (sp).

    Resolution is cached per ``(family, style)``: the underlying FontMetrics is
    resolved once and reused across calls (NFR-1).  :meth:`invalidate` drops the
    cache and must be called by the interpreter after any
    ``\\textfont`` / ``\\scriptfont`` / ``\\scriptscriptfont`` reassignment to
    family 2 or 3.

    FR-4 validation is lazy: a too-small or unset family-2/3 font raises an
    :class:`EngineError` only when a sigma /xi value is actually requested — never at
    assignment time (the M3 load-without-execute contract of is
    preserved).

    Example::

        params = MathFontParameters(registry, font_manager)
        registry.set_text(2, "tensy")          # cmsy10
        params.axis_height(MathStyle.TEXT)     # sigma 22 in sp
    """

    __slots__ = ("_cache", "_family_registry", "_font_manager")

    def __init__(
        self, family_registry: MathFamilyRegistry, font_manager: FontManager
    ) -> None:
        """
        Args:
            family_registry: Router holding the math-family CS assignments.
            font_manager:    Font manager holding the loaded FontMetrics.
        """
        self._family_registry = family_registry
        self._font_manager = font_manager
        self._cache: dict[tuple[int, MathStyle, str | None], FontMetrics] = {}

    def invalidate(self) -> None:
        """Drop the cached ``(family, style)`` → FontMetrics resolutions (NFR-1)."""
        self._cache.clear()

    # ------------------------------------------------------------------
    # Resolution + validation (§C — lazy, read-time, never at assign)
    # ------------------------------------------------------------------

    def _resolve(self, family: int, style: MathStyle) -> FontMetrics:
        key = (family, style, self._family_registry.font_cs_for(family, style))
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        metrics = self._family_registry.resolve_metrics(family, style)
        role = _STYLE_ROLE[style]
        if metrics is None:
            raise EngineError(f"\\{role} {family} is undefined")
        if family == _SYMBOL_FAMILY and metrics.param_count < _SYMBOL_MIN_PARAMS:
            raise EngineError(f"\\{role} {family} is not a math symbol font")
        if family == _EXTENSION_FAMILY and metrics.param_count < _EXTENSION_MIN_PARAMS:
            raise EngineError(f"\\{role} {family} is not a math extension font")

        self._cache[key] = metrics
        return metrics

    def _sigma(self, name: str, style: MathStyle) -> int:
        return self._resolve(_SYMBOL_FAMILY, style).fontdimen(_SIGMA_PARAMS[name])

    def _xi(self, name: str, style: MathStyle) -> int:
        return self._resolve(_EXTENSION_FAMILY, style).fontdimen(_XI_PARAMS[name])

    # ------------------------------------------------------------------
    # sigma accessors (family 2) — generated below from _SIGMA_PARAMS.
    # ------------------------------------------------------------------

    def math_x_height(self, style: MathStyle) -> int:
        """sigma 5 — x-height of the math symbol font, in sp."""
        return self._sigma("math_x_height", style)

    def math_quad(self, style: MathStyle) -> int:
        """sigma 6 — quad width of the math symbol font, in sp."""
        return self._sigma("math_quad", style)

    def num1(self, style: MathStyle) -> int:
        """sigma 8 — numerator shift-up (display), in sp."""
        return self._sigma("num1", style)

    def num2(self, style: MathStyle) -> int:
        """sigma 9 — numerator shift-up (non-display, no \\atop), in sp."""
        return self._sigma("num2", style)

    def num3(self, style: MathStyle) -> int:
        """sigma 10 — numerator shift-up (non-display, \\atop), in sp."""
        return self._sigma("num3", style)

    def denom1(self, style: MathStyle) -> int:
        """sigma 11 — denominator shift-down (display), in sp."""
        return self._sigma("denom1", style)

    def denom2(self, style: MathStyle) -> int:
        """sigma 12 — denominator shift-down (non-display), in sp."""
        return self._sigma("denom2", style)

    def sup1(self, style: MathStyle) -> int:
        """sigma 13 — superscript shift-up (display), in sp."""
        return self._sigma("sup1", style)

    def sup2(self, style: MathStyle) -> int:
        """sigma 14 — superscript shift-up (non-display, non-cramped), in sp."""
        return self._sigma("sup2", style)

    def sup3(self, style: MathStyle) -> int:
        """sigma 15 — superscript shift-up (cramped), in sp."""
        return self._sigma("sup3", style)

    def sub1(self, style: MathStyle) -> int:
        """sigma 16 — subscript shift-down (no superscript), in sp."""
        return self._sigma("sub1", style)

    def sub2(self, style: MathStyle) -> int:
        """sigma 17 — subscript shift-down (with superscript), in sp."""
        return self._sigma("sub2", style)

    def sup_drop(self, style: MathStyle) -> int:
        """sigma 18 — superscript baseline drop from nucleus top, in sp."""
        return self._sigma("sup_drop", style)

    def sub_drop(self, style: MathStyle) -> int:
        """sigma 19 — subscript baseline drop from nucleus bottom, in sp."""
        return self._sigma("sub_drop", style)

    def delim1(self, style: MathStyle) -> int:
        """sigma 20 — delimiter size for display-style operators, in sp."""
        return self._sigma("delim1", style)

    def delim2(self, style: MathStyle) -> int:
        """sigma 21 — delimiter size for non-display operators, in sp."""
        return self._sigma("delim2", style)

    def axis_height(self, style: MathStyle) -> int:
        """sigma 22 — math axis height (fraction-bar / relation centreline), in sp."""
        return self._sigma("axis_height", style)

    # ------------------------------------------------------------------
    # xi accessors (family 3).
    # ------------------------------------------------------------------

    def default_rule_thickness(self, style: MathStyle) -> int:
        """xi 8 — default rule thickness (fraction bar, \\overline), in sp."""
        return self._xi("default_rule_thickness", style)

    def big_op_spacing1(self, style: MathStyle) -> int:
        """xi 9 — minimum glue above a big operator's limit, in sp."""
        return self._xi("big_op_spacing1", style)

    def big_op_spacing2(self, style: MathStyle) -> int:
        """xi 10 — minimum glue below a big operator's limit, in sp."""
        return self._xi("big_op_spacing2", style)

    def big_op_spacing3(self, style: MathStyle) -> int:
        """xi 11 — minimum baseline-to-limit distance above, in sp."""
        return self._xi("big_op_spacing3", style)

    def big_op_spacing4(self, style: MathStyle) -> int:
        """xi 12 — minimum baseline-to-limit distance below, in sp."""
        return self._xi("big_op_spacing4", style)

    def big_op_spacing5(self, style: MathStyle) -> int:
        """xi 13 — extra space added above and below big-operator limits, in sp."""
        return self._xi("big_op_spacing5", style)
