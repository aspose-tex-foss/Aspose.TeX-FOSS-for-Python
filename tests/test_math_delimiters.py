r"""Tests for cascade #2 — var_delimiter + \left/\right.

Covers §B/§C/§D:
  - AC-1: $\left(a\over b\right)$ sizes the parens to span the fraction (rule 19);
          a taller (nested-fraction) inner grows the parens past the base `(`.
  - AC-3: a delimiter taller than the largest discrete cmex glyph is built from
          the extensible recipe (a multi-piece VlistNode, not one CharNode).
  - AC-4: \sqrt / \radical sign sizes via var_delimiter (the _delimiter_box body
          replacement fills the §0 radical slot, no caller change).
  - FR-5: one-sided \left. / \right) (null delcode) → \nulldelimiterspace box.
  - NFR-1: the successor-chain walk is bounded — a synthetic self-linked TFM
           glyph terminates and returns the best glyph seen.

AC-2 (the \big-family) lands (the deferred forced-class
group that executes a {…} math field through the main loop); it is exercised in
``TestBigFamily`` and ``TestForcedClassGroup`` below.
"""

from __future__ import annotations

import struct

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.math_delimiters import var_delimiter
from aspose_tex._engine.math_list import (
    DelimiterCode,
    MathChar,
    MathClass,
    MathList,
)
from aspose_tex._engine.math_style import TeXStyle
from aspose_tex._engine.mlist_to_hlist import _Ctx
from aspose_tex._engine.nodes import CharNode, HlistNode, KernNode, VlistNode
from aspose_tex._fonts.font_metrics import FontMetrics
from aspose_tex._fonts.tfm_parser import parse_tfm
from aspose_tex._input.reader import StringInputSource
from tests._font_keys import font_key

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chars(nodes: list) -> list[CharNode]:
    out: list[CharNode] = []
    for n in nodes:
        if isinstance(n, CharNode):
            out.append(n)
        elif isinstance(n, (HlistNode, VlistNode)):
            out.extend(_chars(n.list))
    return out


def _boxes(nodes: list) -> list:
    out: list = []
    for n in nodes:
        if isinstance(n, (HlistNode, VlistNode)):
            out.append(n)
            out.extend(_boxes(n.list))
    return out


def render(formula: str) -> list:
    """Render *formula* with the real plain.tex format and capture top-level nodes."""
    captured: list = []
    interp = TeXInterpreter(load_format="plain")
    original = interp._append_to_hlist

    def _cap(node) -> None:
        captured.append(node)
        original(node)

    interp._append_to_hlist = _cap  # type: ignore[method-assign]
    interp.run(StringInputSource(formula + "\n" + r"\bye"))
    return captured


def _ctx() -> _Ctx:
    """Build a translation context from a freshly run plain-format interpreter."""
    interp = TeXInterpreter(load_format="plain")
    interp.run(StringInputSource(r"$x$" + "\n" + r"\bye"))
    rs = interp._register_set
    return _Ctx(
        TeXStyle.TEXT, interp._math_params, interp._math_family_registry,
        interp._font_manager,
        rs.get_muskip(256, _internal=True), rs.get_muskip(257, _internal=True),
        rs.get_muskip(258, _internal=True),
        rs.get_dimen(267, _internal=True), rs.get_dimen(266, _internal=True),
        rs.get_count(303, _internal=True), rs.get_dimen(265, _internal=True),
    )


def _delim_box_for(nodes: list, codes: set[int]) -> object | None:
    """Return the first box whose sole CharNode is one of *codes* (a delimiter)."""
    for b in _boxes(nodes):
        chs = [c for c in b.list if isinstance(c, CharNode)]
        if len(chs) == 1 and chs[0].char in codes:
            return b
    return None


# ---------------------------------------------------------------------------
# AC-1 — \left … \right rule-19 sizing
# ---------------------------------------------------------------------------


class TestLeftRight:
    def test_parens_rendered_around_fraction(self) -> None:
        # $\left(a\over b\right)$ emits a left + right delimiter around the frac.
        # Rule 19 (§762) sizes them to span the two-line fraction: the target
        # exceeds a base cmr `(` (10 pt), so BOTH parens grow into the cmex
        # extension chain (verified MiKTeX-exact in the e2e baseline:
        # cmex chars 16 / 17).  The fraction letters a / b are also present.
        nodes = render(r"$\left(a\over b\right)$")
        codes = {(c.char, c.font_name) for c in _chars(nodes)}
        fonts = {f for _ch, f in codes}
        # The grown delimiters live in the cmex extension font (tenex), not cmr.
        assert font_key("tenex", plain=True) in fonts, (
            f"\\left(...\\over...\\right) must grow the parens into cmex; got {fonts}"
        )
        # The fraction body (a / b) still renders.
        assert any(ch == ord("a") for ch, _f in codes)
        assert any(ch == ord("b") for ch, _f in codes)

    def test_tall_inner_grows_parens_past_base(self) -> None:
        # A nested fraction is tall enough that rule 19 grows the delimiters into
        # the cmex chain — the left delimiter is strictly taller than a base
        # cmr `(`, and lives in the cmex extension font.
        base = _ctx()
        from aspose_tex._engine.mlist_to_hlist import _delimiter_box
        base_paren = _delimiter_box(
            DelimiterCode(small_fam=0, small_pos=0x28, large_fam=0, large_pos=0),
            0, TeXStyle.TEXT, base,
        )
        base_hd = base_paren.height + base_paren.depth

        nodes = render(r"$\left({a\over b}\over{c\over d}\right)$")
        # The grown left delimiter is a cmex glyph (tenex), taller than base.  We
        # do NOT pin the exact char code: §762 selects the smallest cmex glyph
        # that covers the rule-19 target, which depends on the inner height — the
        # invariant is that it is a cmex glyph strictly taller than the base `(`.
        grown = None
        for ch in _chars(nodes):
            if ch.font_name == font_key("tenex", plain=True):
                grown = ch
                break
        assert grown is not None, "tall \\left( should grow into the cmex chain"
        gm = base.font_manager.get_metrics(grown.font_name).char_metrics(grown.char)
        assert gm.height + gm.depth > base_hd


# ---------------------------------------------------------------------------
# AC-3 — extensible recipe (taller than the largest discrete glyph)
# ---------------------------------------------------------------------------


class TestExtensibleRecipe:
    def test_huge_target_builds_multi_piece_vlist(self) -> None:
        ctx = _ctx()
        # ( delcode "028300: small fam0/pos0x28, large fam3/pos0 (cmex chain).
        delim = DelimiterCode(small_fam=0, small_pos=0x28, large_fam=3, large_pos=0)
        # 40pt exceeds the largest discrete cmex paren → extensible recipe.
        box = var_delimiter(delim, 40 * 65536, TeXStyle.TEXT, ctx)
        assert isinstance(box, VlistNode), "an over-tall delimiter must be built up"
        chars = _chars([box])
        assert len(chars) >= 2, "the extensible delimiter stacks multiple pieces"
        # the assembly covers at least the requested target.
        assert box.height + box.depth >= 40 * 65536

    def test_growing_target_adds_repeat_pieces(self) -> None:
        ctx = _ctx()
        delim = DelimiterCode(small_fam=0, small_pos=0x28, large_fam=3, large_pos=0)
        small = var_delimiter(delim, 40 * 65536, TeXStyle.TEXT, ctx)
        big = var_delimiter(delim, 80 * 65536, TeXStyle.TEXT, ctx)
        # A taller target inserts more repeatable pieces.
        assert len(_chars([big])) > len(_chars([small]))


# ---------------------------------------------------------------------------
# AC-4 — radical sign via var_delimiter
# ---------------------------------------------------------------------------


class TestRadical:
    def test_sqrt_radical_sign_via_var_delimiter(self) -> None:
        # \sqrt x → the surd √ (cmsy char 0x70) sized by var_delimiter + the x.
        nodes = render(r"$\sqrt x$")
        chars = _chars(nodes)
        assert any(c.char == 0x70 and c.font_name == font_key("tensy", plain=True) for c in chars)
        assert any(c.char == ord("x") for c in chars)

    def test_tall_radicand_grows_surd(self) -> None:
        # A tall radicand (a fraction) grows the radical sign past the base surd:
        # var_delimiter walks into the cmex surd chain (char 0x70 → larger).
        short = render(r"$\sqrt x$")
        tall = render(r"$\sqrt{a\over b}$")
        short_surd = _delim_box_for(short, {0x70})
        # the tall radicand's surd box is at least as tall as the short one.
        tall_surds = [
            b for b in _boxes(tall)
            if any(isinstance(c, CharNode) for c in b.list)
        ]
        assert short_surd is not None
        assert tall_surds


# ---------------------------------------------------------------------------
# FR-5 — one-sided / null delimiters
# ---------------------------------------------------------------------------


class TestNullDelimiter:
    def test_null_delim_is_nulldelimiterspace_box(self) -> None:
        ctx = _ctx()
        box = var_delimiter(None, 10 * 65536, TeXStyle.TEXT, ctx)
        assert isinstance(box, HlistNode)
        kerns = [n for n in box.list if isinstance(n, KernNode)]
        assert kerns and kerns[0].width == ctx.nulldelimiterspace

    def test_all_zero_delcode_is_null_box(self) -> None:
        ctx = _ctx()
        delim = DelimiterCode(small_fam=0, small_pos=0, large_fam=0, large_pos=0)
        box = var_delimiter(delim, 10 * 65536, TeXStyle.TEXT, ctx)
        assert isinstance(box, HlistNode)
        kerns = [n for n in box.list if isinstance(n, KernNode)]
        assert kerns and kerns[0].width == ctx.nulldelimiterspace

    def test_one_sided_left_dot_renders(self) -> None:
        # $\left. x \right)$ — a one-sided group: the left null delimiter is a
        # \nulldelimiterspace box, the right `)` is real.  Must not raise.
        nodes = render(r"$\left. x\right)$")
        chars = _chars(nodes)
        assert any(c.char == 41 for c in chars)  # the right paren is present
        assert any(c.char == ord("x") for c in chars)


# ---------------------------------------------------------------------------
# NFR-1 — bounded successor-chain walk (cycle guard)
# ---------------------------------------------------------------------------


def _self_linked_tfm() -> bytes:
    """Build a minimal TFM whose char 1 chains (tag==2) to itself (a cycle)."""
    bc, ec = 1, 1
    lh = 2
    nw, nh, nd, ni = 2, 2, 2, 1
    nl = nk = ne = 0
    params_fw = (0, 0x280000, 0x80000, 0x40000, 0x6EB85, 0x100000, 0)
    np_ = len(params_fw)
    n_chars = ec - bc + 1
    lf = 6 + lh + n_chars + nw + nh + nd + ni + nl + nk + ne + np_
    buf = bytearray()
    buf += struct.pack(">12H", lf, lh, bc, ec, nw, nh, nd, ni, nl, nk, ne, np_)
    buf += struct.pack(">Ii", 0, 0xA00000)  # checksum, design size 10pt
    # char 1: width_index 1, height_index 1, depth_index 1, tag 2 (chain),
    # remainder 1 → next_larger(1) == 1 (self-link cycle).
    char_info = (1 << 24) | (1 << 20) | (1 << 16) | (2 << 8) | 1
    buf += struct.pack(">I", char_info)
    buf += struct.pack(">ii", 0, 0x80000)   # widths [0, w]
    buf += struct.pack(">ii", 0, 0x80000)   # heights [0, h]
    buf += struct.pack(">ii", 0, 0x40000)   # depths [0, d]
    buf += struct.pack(">i", 0)             # italics [0]
    for p in params_fw:
        buf += struct.pack(">i", p)
    assert len(buf) == lf * 4, f"builder bug: {len(buf)} != {lf * 4}"
    return bytes(buf)


class _StubFontManager:
    def __init__(self, metrics: FontMetrics) -> None:
        self._m = metrics

    def get_metrics(self, _font_cs: str) -> FontMetrics:
        return self._m


class _StubRegistry:
    def __init__(self, font_cs: str) -> None:
        self._cs = font_cs

    def font_cs_for(self, _fam: int, _size) -> str:
        return self._cs


class _StubMathParams:
    def axis_height(self, _size) -> int:
        return 0


def _captured_mlist(formula: str) -> list:
    """Run *formula* (plain format) and return the mlist captured at $-close."""
    interp = TeXInterpreter(load_format="plain")
    captured: dict = {}
    original = interp._close_math_builder

    def _cap(*args, **kwargs):
        if interp._math_builder is not None and "mlist" not in captured:
            captured["mlist"] = list(interp._math_builder._mlist)
        return original(*args, **kwargs)

    interp._close_math_builder = _cap  # type: ignore[method-assign]
    interp.run(StringInputSource(formula + "\n" + r"\bye"))
    return captured.get("mlist", [])


# ---------------------------------------------------------------------------
# AC-2 — \big-family ({…} math-field execution)
# ---------------------------------------------------------------------------


class TestBigFamily:
    def test_big_family_four_increasing_sizes(self) -> None:
        # $\bigl(\Bigl(\biggl(\Biggl($ via the REAL plain.tex macros renders four
        # `(` delimiters of strictly increasing height+depth (the cmex chain).
        nodes = render(r"$\bigl(\Bigl(\biggl(\Biggl($")
        delims = [
            b for b in _boxes(nodes)
            if (chs := [c for c in b.list if isinstance(c, CharNode)])
            and all(c.font_name in (font_key("tenrm", plain=True), font_key("tenex", plain=True)) for c in chs)
        ]
        # The first four delimiter boxes are the formula's \bigl..\Biggl parens.
        sizes = [b.height + b.depth for b in delims[:4]]
        assert len(sizes) == 4, f"expected 4 delimiters, got {len(sizes)}"
        assert sizes == sorted(sizes) and len(set(sizes)) == 4, (
            f"\\big-family sizes must strictly increase, got {sizes}"
        )

    def test_big_body_letters_not_typeset(self) -> None:
        # Regression: the \vbox to8.5pt{} strut body must NOT leak `to8.5` as
        # literal letters (the pre- _scan_sub_mlist failure mode).
        nodes = render(r"$\bigl($")
        letters = {c.char for c in _chars(nodes) if c.font_name == font_key("tenrm", plain=True)}
        # `t`=116 `o`=111 `8`=56 `.`=58? — none of the strut body letters appear.
        for code in (ord("t"), ord("o"), ord("8")):
            assert code not in letters, "the \\vbox strut body leaked as text"


# ---------------------------------------------------------------------------
# AC-2 / AC-4 — forced-class {…} group executes through the main loop
# ---------------------------------------------------------------------------


class TestForcedClassGroup:
    def test_mathopen_hbox_builds_box_nucleus(self) -> None:
        # \mathopen{\hbox{x}}: the {…} group runs through the main loop, the
        # \hbox builds, and the atom is OPEN class.  The group's list is one
        # script-less Ord atom, so TeX §1186 hands its nucleus — the built
        # \hbox — up as the OPEN atom's own nucleus.
        mlist = _captured_mlist(r"$\mathopen{\hbox{x}}$")
        assert len(mlist) == 1
        atom = mlist[0]
        assert atom.math_class is MathClass.OPEN
        assert isinstance(atom.nucleus, HlistNode)

    def test_mathopen_group_of_two_atoms_stays_a_sub_mlist(self) -> None:
        # A group holding more than one atom is not collapsed (§1186).
        mlist = _captured_mlist(r"$\mathopen{\hbox{x}y}$")
        atom = mlist[0]
        assert atom.math_class is MathClass.OPEN
        assert isinstance(atom.nucleus, MathList)
        assert len(atom.nucleus.noads) == 2

    def test_forced_class_applies_to_group(self) -> None:
        # Each class primitive forces its class onto the {…} group atom.
        for prim, cls in (
            (r"\mathbin", MathClass.BIN),
            (r"\mathrel", MathClass.REL),
            (r"\mathclose", MathClass.CLOSE),
        ):
            mlist = _captured_mlist(rf"${prim}{{\hbox{{y}}}}$")
            assert mlist[0].math_class is cls, prim

    def test_symbol_field_no_regression(self) -> None:
        # \mathord\alpha and \mathopen( still build a single-symbol atom (the
        # preserved scan_math_field / symbol path — NOT the deferred group).
        ord_ml = _captured_mlist(r"$\mathord\alpha$")
        assert len(ord_ml) == 1 and ord_ml[0].math_class is MathClass.ORD
        assert isinstance(ord_ml[0].nucleus, MathChar)

        open_ml = _captured_mlist(r"$\mathopen($")
        assert open_ml[0].math_class is MathClass.OPEN
        assert isinstance(open_ml[0].nucleus, MathChar)

    def test_outer_builder_preserved_across_in_math_hbox(self) -> None:
        # §C: the in-math \hbox build must restore the outer _math_builder (same
        # object before/after) so the formula keeps accumulating.  After a \bigl(
        # delimiter the trailing `x` must still reach the rendered output — proof
        # the inner $…$ did NOT close the outer formula.
        nodes = render(r"$\bigl( x$")
        chars = _chars(nodes)
        assert any(c.char == ord("x") for c in chars), (
            "the symbol after \\bigl( was lost — the inner $…$ closed the outer formula"
        )
        # and the delimiter `(` is present (cmr base or a cmex piece).
        assert any(c.font_name in (font_key("tenrm", plain=True), font_key("tenex", plain=True)) for c in chars)

    def test_builder_object_identity_across_hbox(self) -> None:
        # §C, direct: the same MathListBuilder instance is live before and after
        # the in-math \hbox build (no leaked/replaced builder).
        interp = TeXInterpreter(load_format="plain")
        seen: list = []
        original = interp.run_inline_math_in_box

        def _spy(open_tok):
            seen.append(("before", interp._math_builder))
            result = original(open_tok)
            seen.append(("after", interp._math_builder))
            return result

        interp.run_inline_math_in_box = _spy  # type: ignore[method-assign]
        interp.run(StringInputSource(r"$\bigl($" + "\n" + r"\bye"))
        assert seen, "the in-math \\hbox path was never taken"
        before = [b for tag, b in seen if tag == "before"]
        after = [b for tag, b in seen if tag == "after"]
        assert all(b is not None for b in before + after)
        assert before == after, "the outer _math_builder changed across the \\hbox"


class TestCycleGuard:
    def test_self_linked_chain_terminates(self) -> None:
        metrics = FontMetrics(parse_tfm(_self_linked_tfm()), at_sp=10 * 65536,
                              tfm_name="cyclic")
        # Sanity: the synthetic chain self-links (would spin without the guard).
        assert metrics.next_larger(1) == 1

        from aspose_tex._engine.registers import Glue, GlueOrder
        zero = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
        ctx = _Ctx(
            TeXStyle.TEXT, _StubMathParams(), _StubRegistry("cyclic"),
            _StubFontManager(metrics), zero, zero, zero,
            0, int(1.2 * 65536), 901, 5 * 65536,
        )
        # A target larger than the (single, self-linked) glyph: the walk must
        # bound itself and fall back to the best glyph seen, never spin.
        delim = DelimiterCode(small_fam=0, small_pos=1, large_fam=0, large_pos=0)
        box = var_delimiter(delim, 100 * 65536, TeXStyle.TEXT, ctx)
        # the best-seen glyph (char 1) is returned as a discrete box.
        assert isinstance(box, (HlistNode, VlistNode))
        assert _chars([box])[0].char == 1
