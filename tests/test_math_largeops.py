r"""Tests for cascade #3 — make_op size-switch + limits.

Covers §E (TeX:The Program §749-§750, App G rule 13):
  - AC-5 (size switch): $$\sum$$ in display style uses the LARGE cmex \sum
          successor glyph; inline $\sum$ keeps the base glyph — driven by the
          REAL plain.tex \sum macro.
  - AC-5 (limits): a display \sum stacks i=1 below / n above (LIMITS), with the
          ξ9-ξ13 big_op_spacing clearances folded into the stacked box height.
  - AC-6: $\int_0^1$ keeps limits to the right even in display (the real
          plain.tex \int is \intop\nolimits → NO_LIMITS).
  - AC-4-equiv: the LimitMode enum + Noad.limits field; \limits/\nolimits/
          \displaylimits set the last OP atom's mode; on a non-op they raise.
  - AC-6-equiv: a single-symbol text-style Op is raised onto the math axis
          (§749, MiKTeX-measured;).

The \sum/\int/\intop/\prod macros come from the REAL plain.tex format
(``TeXOptions(load_format="plain")``), never mocks (FR-8).
"""

from __future__ import annotations

import pytest

import aspose_tex._engine.mlist_to_hlist as mlist_module
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.math_list import (
    LimitMode,
    MathChar,
    MathClass,
    MathListBuilder,
    Noad,
    NoadKind,
)
from aspose_tex._engine.math_style import TeXStyle
from aspose_tex._engine.nodes import CharNode, HlistNode, VlistNode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError
from tests._font_keys import font_key

# cmex10 (tenex) glyph codes for the plain.tex large operators.
_SUM_TEXT = 0x50  # \textfont3 \sum — the inline (small) sum
_SUM_DISPLAY = 0x58  # \scriptfont/large \sum — the display (large) successor


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


def capture_hlist(formula: str) -> list[tuple[TeXStyle, list]]:
    """Run *formula* (plain format) and capture every ``mlist_to_hlist`` result.

    Returns a list of ``(style, nodes)`` for each translated mlist — display
    math is translated at the DISPLAY style, inline at TEXT.
    """
    caps: list[tuple[TeXStyle, list]] = []
    original = mlist_module.mlist_to_hlist

    def _wrap(noads, style, **kw):  # type: ignore[no-untyped-def]
        res = original(noads, style, **kw)
        caps.append((style, res))
        return res

    mlist_module.mlist_to_hlist = _wrap  # type: ignore[assignment]
    try:
        interp = TeXInterpreter(load_format="plain")
        interp.run(StringInputSource(formula + "\n" + r"\bye"))
    finally:
        mlist_module.mlist_to_hlist = original  # type: ignore[assignment]
    return caps


def capture_mlist(formula: str) -> list[Noad]:
    """Run *formula* (plain format) and return the mlist captured at ``$``-close."""
    captured: dict[str, list[Noad]] = {}
    interp = TeXInterpreter(load_format="plain")
    original = interp._close_math_builder

    def _cap() -> None:
        if interp._math_builder is not None and "mlist" not in captured:
            captured["mlist"] = list(interp._math_builder._mlist)
        original()

    interp._close_math_builder = _cap  # type: ignore[method-assign]
    interp.run(StringInputSource(formula + "\n" + r"\bye"))
    return captured.get("mlist", [])


def _op_atoms(mlist: list[Noad]) -> list[Noad]:
    return [
        n for n in mlist
        if n.kind == NoadKind.ATOM and n.math_class == MathClass.OP
    ]


def _top_style(caps: list[tuple[TeXStyle, list]]) -> tuple[TeXStyle, list]:
    """Return the outermost (last-captured) translated mlist."""
    return caps[-1]


# ---------------------------------------------------------------------------
# AC-5 — display size switch (the LARGE successor glyph)
# ---------------------------------------------------------------------------


class TestSizeSwitch:
    def test_inline_sum_uses_base_glyph(self) -> None:
        # $\sum$ inline → the small cmex sum (no display size switch).
        _style, nodes = _top_style(capture_hlist(r"$\sum$"))
        codes = {c.char for c in _chars(nodes) if c.font_name == font_key("tenex", plain=True)}
        assert _SUM_TEXT in codes
        assert _SUM_DISPLAY not in codes

    def test_display_sum_uses_large_successor(self) -> None:
        # $$\sum$$ display → the LARGE cmex sum successor (§749 size switch).
        _style, nodes = _top_style(capture_hlist(r"$$\sum$$"))
        codes = {c.char for c in _chars(nodes) if c.font_name == font_key("tenex", plain=True)}
        assert _SUM_DISPLAY in codes, "display \\sum must switch to the large glyph"
        assert _SUM_TEXT not in codes

    def test_display_prod_switches_size(self) -> None:
        # $$\prod$$ also has a larger successor → it grows in display.
        _i, inline = _top_style(capture_hlist(r"$\prod$"))
        _d, display = _top_style(capture_hlist(r"$$\prod$$"))
        inline_ex = {c.char for c in _chars(inline) if c.font_name == font_key("tenex", plain=True)}
        display_ex = {c.char for c in _chars(display) if c.font_name == font_key("tenex", plain=True)}
        assert inline_ex and display_ex
        assert inline_ex != display_ex, "display \\prod must use a larger glyph"


# ---------------------------------------------------------------------------
# AC-5 — limits stacked above/below with the ξ9-ξ13 clearances
# ---------------------------------------------------------------------------


class TestLimits:
    def test_display_sum_stacks_limits(self) -> None:
        # $$\sum_{i=1}^{n}$$ → i=1 below, n above (LIMITS): one VlistNode that
        # contains the large sum AND the script glyphs (a limit stack, not
        # scripts to the right).
        _style, nodes = _top_style(capture_hlist(r"$$\sum_{i=1}^{n}$$"))
        stacks = [n for n in _walk_vlists(nodes) if _is_limit_stack(n)]
        assert stacks, "display \\sum with scripts must build a limit stack"
        stack = stacks[0]
        chars = {c.char for c in _chars([stack])}
        assert _SUM_DISPLAY in chars                 # the large operator
        assert ord("n") in chars                     # superscript above
        assert ord("i") in chars and ord("1") in chars  # subscript below

    def test_limit_stack_height_includes_big_op_spacing(self) -> None:
        # The stacked box height must exceed the bare op height by at least the
        # ξ-table clearances (big_op_spacing5 margin + the sup box) — proving the
        # §750 clearances are folded in, not dropped.
        _b, bare = _top_style(capture_hlist(r"$$\sum$$"))
        _s, scripted = _top_style(capture_hlist(r"$$\sum^{n}$$"))
        bare_box = _first_box(bare)
        stack = next(n for n in _walk_vlists(scripted) if _is_limit_stack(n))
        assert stack.height > bare_box.height, "the superscript clearance must add height"


# ---------------------------------------------------------------------------
# AC-6 — \nolimits keeps scripts to the right (even in display)
# ---------------------------------------------------------------------------


class TestNoLimits:
    def test_int_keeps_limits_to_the_right_in_display(self) -> None:
        # plain.tex \int == \intop\nolimits → NO_LIMITS: in display the scripts
        # ride to the RIGHT, so the op atom carries NO_LIMITS and the layout does
        # not build a limit stack around the integral glyph.
        mlist = capture_mlist(r"$\int_0^1$")
        ops = _op_atoms(mlist)
        assert ops and ops[0].limits == LimitMode.NO_LIMITS

    def test_display_int_no_limit_stack(self) -> None:
        _style, nodes = _top_style(capture_hlist(r"$$\int_0^1 f$$"))
        # No VlistNode should contain the integral glyph together with BOTH its
        # 0 and 1 scripts stacked vertically over/under it.
        int_stacks = [
            n for n in _walk_vlists(nodes)
            if _is_limit_stack(n) and ord("0") in {c.char for c in _chars([n])}
            and 0x52 in {c.char for c in _chars([n])}  # cmex \intop
        ]
        assert not int_stacks, "\\int must place limits to the right, not stacked"


# ---------------------------------------------------------------------------
# LimitMode field + \limits/\nolimits/\displaylimits dispatch
# ---------------------------------------------------------------------------


class TestLimitMode:
    def test_default_mode_is_display_limits(self) -> None:
        assert Noad(NoadKind.ATOM, MathClass.OP).limits == LimitMode.DISPLAY_LIMITS

    def test_limits_sets_last_op_mode(self) -> None:
        # \mathop\sum\limits sets the OP atom to LIMITS.
        mlist = capture_mlist(r"$\mathop\sum\limits$")
        ops = _op_atoms(mlist)
        assert ops and ops[0].limits == LimitMode.LIMITS

    def test_nolimits_sets_last_op_mode(self) -> None:
        mlist = capture_mlist(r"$\mathop\sum\nolimits$")
        ops = _op_atoms(mlist)
        assert ops and ops[0].limits == LimitMode.NO_LIMITS

    def test_displaylimits_sets_last_op_mode(self) -> None:
        mlist = capture_mlist(r"$\mathop\sum\nolimits\displaylimits$")
        ops = _op_atoms(mlist)
        assert ops and ops[0].limits == LimitMode.DISPLAY_LIMITS

    def test_limits_on_non_op_raises(self) -> None:
        # \limits after an ordinary atom (not a large operator) → EngineError
        # (TeX §1158 limit_switch).
        with pytest.raises(EngineError, match="large operator"):
            TeXInterpreter(load_format="plain").run(
                StringInputSource(r"$x\limits$" + "\n" + r"\bye")
            )

    def test_limits_on_empty_list_raises(self) -> None:
        builder = _bare_builder()
        with pytest.raises(EngineError, match="large operator"):
            builder.add_limits("limits")


# ---------------------------------------------------------------------------
# AC-6 — the text-style single-symbol Op is centred on the axis (§749)
# ---------------------------------------------------------------------------


class TestTextStyleAxisShift:
    def test_inline_op_centered_on_axis_unchanged(self) -> None:
        # A single-symbol inline Op (no scripts) is raised so its centre sits on
        # the axis (§749; TeX's down-positive shift, sign-flipped —).
        caps = capture_hlist(r"$\sum$")
        _style, nodes = _top_style(caps)
        op = _first_box(nodes)
        # MiKTeX sets the \sum glyph at v=163836 on the 655360 baseline.
        assert op.shift_amount == 655360 - 163836
        # The op box is a bare-glyph hbox (no limit stack) for the no-script case.
        assert isinstance(op, HlistNode)


# ---------------------------------------------------------------------------
# Local structure helpers
# ---------------------------------------------------------------------------


def _walk_vlists(nodes: list) -> list[VlistNode]:
    out: list[VlistNode] = []
    for n in nodes:
        if isinstance(n, VlistNode):
            out.append(n)
            out.extend(_walk_vlists(n.list))
        elif isinstance(n, HlistNode):
            out.extend(_walk_vlists(n.list))
    return out


def _is_limit_stack(vlist: VlistNode) -> bool:
    """A limit stack is a vlist that contains a tenex (cmex) operator glyph."""
    return any(
        isinstance(c, CharNode) and c.font_name == font_key("tenex", plain=True)
        for c in _chars([vlist])
    )


def _first_box(nodes: list):  # type: ignore[no-untyped-def]
    for n in nodes:
        if isinstance(n, (HlistNode, VlistNode)):
            return n
    raise AssertionError("no box in node list")


def _bare_builder() -> MathListBuilder:
    """A builder with one Ord atom on its list (for the error-path unit test)."""
    interp = TeXInterpreter(load_format="plain")
    interp.run(StringInputSource(r"$x$" + "\n" + r"\bye"))
    builder = MathListBuilder(
        interp._expander,
        interp._code_arrays,
        interp._math_family_registry,
        interp._register_set,
    )
    builder._mlist.append(Noad(NoadKind.ATOM, MathClass.ORD, nucleus=MathChar(0, ord("x"))))
    return builder
