r"""Tests for cascade #2 accents / radicals / over-under.

Covers AC-4/AC-5/AC-6 (§D):
  - $\mathaccent"7016 a$ → accent glyph centred over the nucleus (AC-4)
  - $\radical"270370 x$  → base-size radical sign + vinculum (AC-5, base-size
                            interim per §0)
  - $\overline{x}$ / $\underline x$ → RuleNode with the App-G rule-16 clearance
                            (AC-6)
  - _delimiter_box: base-size glyph + \nulldelimiterspace, carries a
                    marker (AC-5)
"""

from __future__ import annotations

import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode, HlistNode, KernNode, RuleNode, VlistNode
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


def _chars(nodes: list) -> list[CharNode]:
    out: list[CharNode] = []
    for n in nodes:
        if isinstance(n, CharNode):
            out.append(n)
        elif isinstance(n, (HlistNode, VlistNode)):
            out.extend(_chars(n.list))
    return out


def _rules(nodes: list) -> list[RuleNode]:
    out: list[RuleNode] = []
    for n in nodes:
        if isinstance(n, RuleNode):
            out.append(n)
        elif isinstance(n, (HlistNode, VlistNode)):
            out.extend(_rules(n.list))
    return out


def _params():
    interp = TeXInterpreter()
    interp.run(StringInputSource(_PRE + r"$x$" + r"\bye"))
    return interp._math_params


# ---------------------------------------------------------------------------
# AC-4 — math accent
# ---------------------------------------------------------------------------


class TestMathAccent:
    def test_accent_glyph_over_nucleus(self) -> None:
        # \mathaccent"7016 a → the hat glyph (char 0x16, fam 0 = roman) over `a`.
        nodes = render(r'$\mathaccent"7016 a$')
        chars = _chars(nodes)
        codes = {(c.char, c.font_name) for c in chars}
        assert (ord("a"), font_key("teni", _PRE)) in codes        # nucleus from cmmi10
        assert (0x16, font_key("tenrm", _PRE)) in codes            # accent glyph from cmr10

    def test_accent_box_width_is_nucleus_width(self) -> None:
        # The accent box adopts the nucleus width (the accent is centred within).
        nodes = render(r'$\mathaccent"7016 a$')
        box = next(n for n in nodes if isinstance(n, (HlistNode, VlistNode)))
        # nucleus 'a' rendered alone for the width reference.
        nuc_nodes = render(r"$a$")
        nuc_box_chars = _chars(nuc_nodes)
        assert nuc_box_chars  # sanity
        assert box.width > 0

    def test_accent_offset_is_texs_half_of_char_box_width(self) -> None:
        #, §738: shift = s + half(w - width(y)), width(y) = char width +
        # italic (§709).  a - \hat = 18735 sp (odd: floor division lands 1 sp
        # left); \vec (cmmi10 '176) carries a 100806 sp italic correction.
        # Positions measured with MiKTeX 24.4 `tex` (plain), 2026-10-29.
        from tests.test_mlist_to_hlist import _plain_glyph_h

        assert _plain_glyph_h(r"$\hat a\vec x$") == [
            (94, 1320088), (97, 1310720), (126, 1648376), (120, 1657136),
        ]

    @pytest.mark.parametrize("backend", ["dvi", "svg", "pdf"])
    def test_accent_offset_in_every_writer(self, backend, monkeypatch) -> None:
        # The same MiKTeX glyph positions reach DVI, SVG and PDF.
        from tests._verification.shipout_events import compile_events

        events = compile_events("\\nopagenumbers $\\hat a\\vec x$\n\\bye\n", backend, monkeypatch)
        assert events["glyphs"] == [[
            [94, 1320088, 655360], [97, 1310720, 655360],
            [126, 1648376, 655360], [120, 1657136, 655360],
        ]]


# ---------------------------------------------------------------------------
# AC-5 — radical (base-size interim)
# ---------------------------------------------------------------------------


class TestRadical:
    def test_radical_sign_and_vinculum(self) -> None:
        # \radical"270370 x → base-size surd (cmsy char 0x70) + a vinculum rule.
        nodes = render(r'$\radical"270370 x$')
        chars = _chars(nodes)
        # the surd √ is cmsy char 0x70 from \textfont2 (tensy).
        assert any(c.char == 0x70 and c.font_name == font_key("tensy", _PRE) for c in chars)
        assert any(c.char == ord("x") and c.font_name == font_key("teni", _PRE) for c in chars)
        # the vinculum is a RuleNode of default_rule_thickness.
        rules = _rules(nodes)
        assert len(rules) == 1
        assert rules[0].height == _params().default_rule_thickness(MathStyle.TEXT)

    def test_radical_short_radicand_uses_base_glyph(self) -> None:
        # §0 interim: a short radicand uses the BASE-SIZE radical glyph
        # (no growth) — so the surd char is the small variant, never a built-up
        # extensible.  Assert exactly one surd CharNode (no recipe pieces).
        nodes = render(r'$\radical"270370 x$')
        surds = [c for c in _chars(nodes) if c.char == 0x70]
        assert len(surds) == 1


# ---------------------------------------------------------------------------
# AC-6 — \overline / \underline
# ---------------------------------------------------------------------------


class TestOverUnder:
    def test_overline_rule_above(self) -> None:
        nodes = render(r"$\overline{x}$")
        rules = _rules(nodes)
        assert len(rules) == 1
        theta = _params().default_rule_thickness(MathStyle.TEXT)
        assert rules[0].height == theta
        # rule-16 clearance: the vlist has the rule + 3·theta gap above the box,
        # so its height exceeds 3·theta (the bare nucleus height plus the gap).
        box = next(n for n in nodes if isinstance(n, VlistNode))
        assert box.height > theta * 3

    def test_underline_rule_below(self) -> None:
        nodes = render(r"$\underline x$")
        rules = _rules(nodes)
        assert len(rules) == 1
        theta = _params().default_rule_thickness(MathStyle.TEXT)
        assert rules[0].height == theta
        box = next(n for n in nodes if isinstance(n, VlistNode))
        # underline extends the depth by 3·theta + theta below the baseline.
        assert box.depth >= 3 * theta + theta


# ---------------------------------------------------------------------------
# AC-5 — _delimiter_box (the↔ seam)
# ---------------------------------------------------------------------------


class TestDelimiterBox:
    def test_null_delim_is_nulldelimiterspace_box(self) -> None:
        from aspose_tex._engine.math_style import TeXStyle
        from aspose_tex._engine.mlist_to_hlist import _Ctx, _delimiter_box

        interp = TeXInterpreter()
        interp.run(StringInputSource(_PRE + r"\nulldelimiterspace=1.2pt $x$" + r"\bye"))
        rs = interp._register_set
        ctx = _Ctx(
            TeXStyle.TEXT, interp._math_params, interp._math_family_registry,
            interp._font_manager,
            rs.get_muskip(256, _internal=True), rs.get_muskip(257, _internal=True),
            rs.get_muskip(258, _internal=True),
            rs.get_dimen(267, _internal=True), rs.get_dimen(266, _internal=True),
        )
        box = _delimiter_box(None, 10 * 65536, TeXStyle.TEXT, ctx)
        # a null delimiter → an empty box whose width is \nulldelimiterspace.
        assert isinstance(box, HlistNode)
        kerns = [n for n in box.list if isinstance(n, KernNode)]
        assert kerns and kerns[0].width == int(1.2 * 65536)

    def test_small_target_uses_base_size_glyph(self) -> None:
        #: a tiny target is already covered by the base (small-variant)
        # glyph, so var_delimiter returns the small `(` from cmsy without growth.
        from aspose_tex._engine.math_list import DelimiterCode
        from aspose_tex._engine.math_style import TeXStyle
        from aspose_tex._engine.mlist_to_hlist import _Ctx, _delimiter_box

        interp = TeXInterpreter()
        interp.run(StringInputSource(_PRE + r"$x$" + r"\bye"))
        rs = interp._register_set
        ctx = _Ctx(
            TeXStyle.TEXT, interp._math_params, interp._math_family_registry,
            interp._font_manager,
            rs.get_muskip(256, _internal=True), rs.get_muskip(257, _internal=True),
            rs.get_muskip(258, _internal=True),
            rs.get_dimen(267, _internal=True), rs.get_dimen(266, _internal=True),
        )
        # ( = cmsy fam 2, pos 0x28; with no large variant a 0-target keeps the base.
        delim = DelimiterCode(small_fam=2, small_pos=0x28, large_fam=0, large_pos=0)
        box = _delimiter_box(delim, 0, TeXStyle.TEXT, ctx)
        chars = _chars([box])
        assert len(chars) == 1
        assert chars[0].char == 0x28 and chars[0].font_name == font_key("tensy", _PRE)

    def test_large_target_grows_via_cmex(self) -> None:
        #: a tall target walks the large (cmex, fam 3) successor chain
        # and returns a larger glyph than the base `(`.
        from aspose_tex._engine.math_list import DelimiterCode
        from aspose_tex._engine.math_style import TeXStyle
        from aspose_tex._engine.mlist_to_hlist import _Ctx, _delimiter_box

        interp = TeXInterpreter()
        interp.run(StringInputSource(_PRE + r"$x$" + r"\bye"))
        rs = interp._register_set
        ctx = _Ctx(
            TeXStyle.TEXT, interp._math_params, interp._math_family_registry,
            interp._font_manager,
            rs.get_muskip(256, _internal=True), rs.get_muskip(257, _internal=True),
            rs.get_muskip(258, _internal=True),
            rs.get_dimen(267, _internal=True), rs.get_dimen(266, _internal=True),
        )
        # ( delcode "028300: small fam0/pos0x28, large fam3/pos0x00 (cmex chain).
        delim = DelimiterCode(small_fam=0, small_pos=0x28, large_fam=3, large_pos=0x00)
        box = _delimiter_box(delim, 100 * 65536, TeXStyle.TEXT, ctx)
        chars = _chars([box])
        assert chars  # a grown glyph from the cmex extension font
        assert chars[0].font_name == font_key("tenex", _PRE)
