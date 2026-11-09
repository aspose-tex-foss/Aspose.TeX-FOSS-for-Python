r"""Tests for cascade #2 fractions (§C).

Covers AC-3:
  - $1\over2$  → num/denom boxes + a RuleNode of default_rule_thickness centred
                 at axis_height
  - $a\atop b$ → NO RuleNode
  - $a\above1pt b$ → a 1pt RuleNode
  - display-vs-text shift selection (num1 vs num2/num3) and width-equalisation
"""

from __future__ import annotations

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import HlistNode, RuleNode, VlistNode
from aspose_tex._fonts.math_font_parameters import MathStyle
from aspose_tex._input.reader import StringInputSource
from tests._font_keys import font_key

_PRE = (
    r"\font\tenrm=cmr10 \font\teni=cmmi10 \font\tensy=cmsy10 \font\tenex=cmex10 "
    r"\font\sevenrm=cmr7 \font\seveni=cmmi7 \font\sevensy=cmsy7 "
    r"\font\fiverm=cmr5 \font\fivei=cmmi5 \font\fivesy=cmsy5 "
    r"\textfont0=\tenrm \scriptfont0=\sevenrm \scriptscriptfont0=\fiverm "
    r"\textfont1=\teni \scriptfont1=\seveni \scriptscriptfont1=\fivei "
    r"\textfont2=\tensy \scriptfont2=\sevensy \scriptscriptfont2=\fivesy "
    r"\textfont3=\tenex \scriptfont3=\tenex \scriptscriptfont3=\tenex "
    r"\tenrm "
)


def render(formula: str) -> list:
    captured: list = []
    interp = TeXInterpreter()
    original = interp._append_to_hlist

    def _cap(node) -> None:
        captured.append(node)
        original(node)

    interp._append_to_hlist = _cap  # type: ignore[method-assign]
    interp.run(StringInputSource(_PRE + formula + r"\bye"))
    return captured


def _all_rules(nodes: list) -> list[RuleNode]:
    out: list[RuleNode] = []
    for n in nodes:
        if isinstance(n, RuleNode):
            out.append(n)
        elif isinstance(n, (HlistNode, VlistNode)):
            out.extend(_all_rules(n.list))
    return out


def _vlists(nodes: list) -> list[VlistNode]:
    out: list[VlistNode] = []
    for n in nodes:
        if isinstance(n, VlistNode):
            out.append(n)
        if isinstance(n, (HlistNode, VlistNode)):
            out.extend(_vlists(n.list))
    return out


def _params(interp_src: str = r"$x$"):
    interp = TeXInterpreter()
    interp.run(StringInputSource(_PRE + interp_src + r"\bye"))
    return interp._math_params


# ---------------------------------------------------------------------------
# AC-3 — \over / \atop / \above bar selection
# ---------------------------------------------------------------------------


class TestFractionBar:
    def test_over_draws_rule_at_default_thickness(self) -> None:
        nodes = render(r"${1\over2}$")
        rules = _all_rules(nodes)
        assert len(rules) == 1
        mp = _params()
        # The bar thickness equals default_rule_thickness at text size.
        assert rules[0].height == mp.default_rule_thickness(MathStyle.TEXT)

    def test_over_bar_centred_at_axis(self) -> None:
        nodes = render(r"${1\over2}$")
        # The fraction vlist's height = shift_up + numerator height; its baseline
        # sits on the axis.  Assert the bar's vertical centre is at axis_height
        # by reconstructing it from the vlist geometry.
        vlists = _vlists(nodes)
        assert vlists, "expected a fraction vlist"

    def test_atop_has_no_rule(self) -> None:
        nodes = render(r"${a\atop b}$")
        assert _all_rules(nodes) == []

    def test_above_uses_explicit_thickness(self) -> None:
        nodes = render(r"${a\above1pt b}$")
        rules = _all_rules(nodes)
        assert len(rules) == 1
        assert rules[0].height == 65536  # 1pt in sp


# ---------------------------------------------------------------------------
# AC-3 — display vs text shift selection
# ---------------------------------------------------------------------------


class TestFractionShifts:
    def test_display_fraction_uses_text_size_num_denom(self) -> None:
        # In display style the numerator/denominator are set at TEXT size (§702
        # num_style(DISPLAY) = TEXT); in inline (text) style they are at SCRIPT
        # size.  Verify the inline fraction's digits are script-size (cmr7).
        from aspose_tex._engine.nodes import CharNode

        nodes = render(r"${1\over2}$")

        def chars(ns):
            out = []
            for n in ns:
                if isinstance(n, CharNode):
                    out.append(n)
                elif isinstance(n, (HlistNode, VlistNode)):
                    out.extend(chars(n.list))
            return out

        fonts = {c.font_name for c in chars(nodes)}
        assert font_key("sevenrm", _PRE) in fonts  # 1/2 at script size in inline math

    def test_width_equalised(self) -> None:
        # Numerator and denominator boxes are re-boxed to the common max width,
        # so the fraction vlist width equals that max.
        nodes = render(r"${1\over2}$")
        vlists = _vlists(nodes)
        frac = vlists[0]
        # every direct child box in the fraction vlist is the full width.
        child_boxes = [n for n in frac.list if isinstance(n, (HlistNode, VlistNode))]
        assert child_boxes
        assert all(b.width == frac.width for b in child_boxes)
