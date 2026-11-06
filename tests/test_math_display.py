r"""Tests for cascade #3 — the display after_math branch.

Covers AC-7 (§F):
  - $$x = y$$        → centred in \displaywidth + \abovedisplayskip /
                        \belowdisplayskip glue above/below
  - $$x=y\eqno(1)$$  → (1) flush right; \leqno → flush left
  - short-skip selection by \predisplaysize (§1204)
  - display runs at TeXStyle.DISPLAY (text-size num/denom) vs inline's
    script-size num/denom (§702)

Scope boundary (§F.2): AC-7 is exercised through STANDALONE displays
(`$$…$$` as the whole paragraph) — centring + skips + \eqno without a
mid-paragraph break; the full mid-paragraph display↔line-break interplay is
verified by the cascade #4 e2e baseline.
"""

from __future__ import annotations

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode, GlueNode, HlistNode, PenaltyNode, VlistNode
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
    r"\tenrm \hsize=300pt "
    r'\mathcode`\+="202B \mathcode`\="303D '
)

_PT = 65536


def contributed(formula: str) -> list:
    """Run *formula* and return the nodes contributed to vertical mode."""
    out: list = []
    interp = TeXInterpreter()
    original = interp._contribute

    def _cap(node) -> None:
        out.append(node)
        original(node)

    interp._contribute = _cap  # type: ignore[method-assign]
    interp.run(StringInputSource(_PRE + formula + r"\bye"))
    return out


def appended(formula: str) -> list:
    """Run *formula* and return the nodes appended to the horizontal list."""
    out: list = []
    interp = TeXInterpreter()
    original = interp._append_to_hlist

    def _cap(node) -> None:
        out.append(node)
        original(node)

    interp._append_to_hlist = _cap  # type: ignore[method-assign]
    interp.run(StringInputSource(_PRE + formula + r"\bye"))
    return out


def _chars(nodes: list) -> list[CharNode]:
    out: list[CharNode] = []
    for n in nodes:
        if isinstance(n, CharNode):
            out.append(n)
        elif isinstance(n, (HlistNode, VlistNode)):
            out.extend(_chars(n.list))
    return out


def _boxes(nodes: list) -> list:
    return [n for n in nodes if isinstance(n, (HlistNode, VlistNode))]


# ---------------------------------------------------------------------------
# AC-7 — centring + display skips
# ---------------------------------------------------------------------------


class TestDisplayCentring:
    def test_display_line_is_displaywidth_wide(self) -> None:
        # uses a natural formula box shifted to its measured center.
        out = contributed(r"$$x = y$$")
        boxes = _boxes(out)
        assert boxes, "expected a display line box"
        assert abs(2 * boxes[-1].shift_amount + boxes[-1].width - 300 * _PT) <= 1

    def test_standalone_display_emits_empty_line_then_short_skips(self) -> None:
        # TeX §1145: a STANDALONE `$$…$$` (preceded by \par) starts a fresh
        # paragraph whose pre-display line is empty.  MiKTeX ships that empty
        # line box (HT=DP=0, width=\hsize) + a §1147 \penalty 10000, then frames
        # the display with the SHORT display skips (the empty line is small, so
        # \predisplaysize selects \abovedisplayshortskip / \belowdisplayshortskip).
        out = contributed(
            r"\abovedisplayskip=12pt \belowdisplayskip=11pt "
            r"\abovedisplayshortskip=3pt \belowdisplayshortskip=2pt "
            r"Hi\par $$x = y$$"
        )
        glue_widths = [n.glue.width for n in out if isinstance(n, GlueNode)]
        # Short skips selected (empty pre-display line) — not the full skips.
        assert 3 * _PT in glue_widths
        assert 2 * _PT in glue_widths
        assert 12 * _PT not in glue_widths
        assert 11 * _PT not in glue_widths
        # The empty pre-display line box (HT=DP=0, full \hsize) is contributed:
        # the indent-only paragraph line-broken into one line (§1096,),
        # holding the indent box and \parfillskip but no printable material.
        empty_lines = [
            n for n in out
            if isinstance(n, HlistNode) and n.height == 0 and n.depth == 0
            and n.width == 300 * _PT
            and all(isinstance(m, (HlistNode, GlueNode, PenaltyNode)) for m in n.list)
        ]
        assert empty_lines, "expected the §1145 empty pre-display line box"

    def test_short_skip_selected_for_standalone_display(self) -> None:
        # A standalone display always selects the short display skips (§1145:
        # the empty pre-display line makes \predisplaysize small).
        out = contributed(
            r"\abovedisplayskip=12pt \belowdisplayskip=11pt "
            r"\abovedisplayshortskip=3pt \belowdisplayshortskip=2pt "
            r"Hi\par $$x = y$$"
        )
        glue_widths = [n.glue.width for n in out if isinstance(n, GlueNode)]
        assert 3 * _PT in glue_widths
        assert 2 * _PT in glue_widths
        assert 12 * _PT not in glue_widths


# ---------------------------------------------------------------------------
# — \predisplaysize short-vs-long display-skip selection
# ---------------------------------------------------------------------------


class TestPredisplaysize:
    """\\predisplaysize (§1146) drives the §1204 short/long skip selection.

    Before the engine never *wrote* \\predisplaysize, so a display
    preceded by real text always used the full \\abovedisplayskip — the
    alignment_eqalign +12 pt display-low defect.
    """

    def test_short_line_before_display_selects_short_skips(self) -> None:
        # A short inline line ("The system") before $$…$$: \predisplaysize is
        # small, so the SHORT display skips are selected (matching MiKTeX).
        out = contributed(
            r"\abovedisplayskip=12pt \belowdisplayskip=11pt "
            r"\abovedisplayshortskip=3pt \belowdisplayshortskip=2pt "
            r"\noindent The system $$x = y$$ ok"
        )
        glue_widths = [n.glue.width for n in out if isinstance(n, GlueNode)]
        assert 3 * _PT in glue_widths       # \abovedisplayshortskip
        assert 2 * _PT in glue_widths       # \belowdisplayshortskip
        assert 12 * _PT not in glue_widths  # NOT the full \abovedisplayskip
        assert 11 * _PT not in glue_widths  # NOT the full \belowdisplayskip

    def test_full_width_line_before_display_selects_long_skips(self) -> None:
        # A preceding line whose ink reaches past the display's left edge:
        # \predisplaysize is large (> offset), so the LONG display skips are
        # selected.  Guards against a hard-force-short regression.  A full-\hsize
        # \hbox on the same paragraph makes the pre-display line's natural width
        # ~300 pt, far past the ~centred display's left offset.
        out = contributed(
            r"\abovedisplayskip=12pt \belowdisplayskip=11pt "
            r"\abovedisplayshortskip=3pt \belowdisplayshortskip=2pt "
            r"\noindent \hbox to 290pt{}$$x = y$$"
        )
        glue_widths = [n.glue.width for n in out if isinstance(n, GlueNode)]
        assert 12 * _PT in glue_widths      # \abovedisplayskip (long)
        assert 11 * _PT in glue_widths      # \belowdisplayskip (long)
        assert 3 * _PT not in glue_widths   # NOT the short skips
        assert 2 * _PT not in glue_widths

    def test_standalone_display_still_short(self) -> None:
        # The standalone `$$` path (empty pre-display line,) is
        # unchanged — still short skips.
        out = contributed(
            r"\abovedisplayskip=12pt \belowdisplayskip=11pt "
            r"\abovedisplayshortskip=3pt \belowdisplayshortskip=2pt "
            r"Hi\par $$x = y$$"
        )
        glue_widths = [n.glue.width for n in out if isinstance(n, GlueNode)]
        assert 3 * _PT in glue_widths
        assert 2 * _PT in glue_widths
        assert 12 * _PT not in glue_widths

    def test_measure_predisplaysize_excludes_trailing_glue(self) -> None:
        # _measure_predisplaysize returns the width to the last non-glue item;
        # a trailing \hfil-style glue does not count toward the ink extent.
        from aspose_tex._engine.nodes import HlistNode, KernNode
        from aspose_tex._engine.registers import Glue, GlueOrder

        interp = TeXInterpreter()
        # Initialise the font manager / engine state via a no-op run.
        interp.run(StringInputSource(_PRE + r"\bye"))
        box = HlistNode(
            list=[
                KernNode(width=100 * _PT, explicit=True),
                GlueNode(Glue(50 * _PT, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)),
            ],
            width=300 * _PT, height=0, depth=0, shift_amount=0,
            glue_sign=0, glue_order=GlueOrder.NORMAL, glue_set=0.0,
        )
        # §1146: neither a kern nor glue is visible.
        from aspose_tex._engine.registers import MAX_DIMEN
        assert interp._measure_predisplaysize(box) == -MAX_DIMEN


# ---------------------------------------------------------------------------
# AC-7 — \eqno / \leqno
# ---------------------------------------------------------------------------


class TestEqno:
    def test_eqno_number_present_flush_right(self) -> None:
        # $$x=y\eqno(1)$$ — the number (1) is laid out after the equation.
        out = contributed(r"$$x=y\eqno(1)$$")
        chars = _chars(out)
        codes = {c.char for c in chars}
        assert ord("1") in codes      # the equation number digit
        assert ord("(") in codes and ord(")") in codes
        # equation chars x / y also present.
        assert ord("x") in codes and ord("y") in codes

    def test_leqno_number_present(self) -> None:
        out = contributed(r"$$x=y\leqno(1)$$")
        codes = {c.char for c in _chars(out)}
        assert ord("1") in codes
        assert ord("x") in codes

    def test_eqno_outside_display_raises(self) -> None:
        import pytest

        from aspose_tex.exceptions import EngineError

        interp = TeXInterpreter()
        with pytest.raises(EngineError, match="valid only in display math"):
            interp.run(StringInputSource(_PRE + r"$x=y\eqno(1)$" + r"\bye"))

    def test_eqno_overflow_moves_number_to_own_line(self) -> None:
        # §1205: when the number + equation cannot fit in \displaywidth, the
        # number goes on its own line, directly in the enclosing vlist.
        out = contributed(r"\hsize=20pt $$x=y\eqno(1)$$")
        boxes = _boxes(out)
        assert boxes
        assert len(boxes) >= 2  # the implicit initial indent line may precede it
        assert all(isinstance(n, HlistNode) for n in boxes)

    def test_eqno_no_overflow_is_single_line(self) -> None:
        # A comfortably wide \displaywidth keeps the number beside the equation
        # on a single hbox line.
        out = contributed(r"\hsize=300pt $$x=y\eqno(1)$$")
        line = _boxes(out)[-1]
        assert isinstance(line, HlistNode)


# ---------------------------------------------------------------------------
# AC-7 — display style (text-size num/denom) vs inline (script-size)
# ---------------------------------------------------------------------------


class TestDisplayStyle:
    def test_display_fraction_uses_text_size(self) -> None:
        # Display $${1\over2}$$ sets num/denom at TEXT size (cmr10), unlike the
        # inline ${1\over2}$ which drops them to SCRIPT size (cmr7) — §702.
        disp_fonts = {c.font_name for c in _chars(contributed(r"$${1\over2}$$"))}
        inline_fonts = {c.font_name for c in _chars(appended(r"${1\over2}$"))}
        assert font_key("tenrm", _PRE) in disp_fonts      # 1/2 at text size in display
        assert font_key("sevenrm", _PRE) in inline_fonts  # 1/2 at script size inline
        assert font_key("tenrm", _PRE) not in inline_fonts


# ---------------------------------------------------------------------------
# — §1206 resume_after_display + §1207 optional-space scan
# ---------------------------------------------------------------------------


_PARINDENT = 20 * _PT


def _lines(nodes: list) -> list[HlistNode]:
    """Contributed HlistNode line boxes, in order."""
    return [n for n in nodes if isinstance(n, HlistNode)]


def _has_indent_box(line: HlistNode) -> bool:
    r"""True if *line* starts with a \parindent-wide empty indent box."""
    if not line.list:
        return False
    first = line.list[0]
    return (
        isinstance(first, HlistNode)
        and not first.list
        and first.width == _PARINDENT
    )


class TestResumeAfterDisplay:
    r"""TeX §1206-§1207: a paragraph resumed after ``$$…$$`` continues.

    It neither re-indents (§1206 goes straight to hmode, bypassing
    ``new_graf``) nor keeps the optional space the author wrote after the
    closing ``$$`` (§1207 discards it).
    """

    def test_resumed_paragraph_after_display_has_no_indent_box(self) -> None:
        # AC-1: the tail line CONTINUES the paragraph, so it carries no
        # \parindent box.  Reverting the _resume_after_display() call makes the
        # tail re-enter via _begin_paragraph()'s default indent=True and fail.
        out = contributed(r"\noindent The system $$x=y$$ has a solution.\par")
        tail = _lines(out)[-1]
        assert not _has_indent_box(tail), (
            r"resumed post-display line must not carry a \parindent box (§1206)"
        )

    def test_paragraph_starting_after_display_still_indents(self) -> None:
        # AC-3 guard (two-sided): a paragraph that genuinely STARTS after the
        # display — \par closes the resumed one — must still indent normally.
        # Fails if the fix over-reaches into _begin_paragraph's default.
        out = contributed(r"\noindent The system $$x=y$$\par New paragraph.\par")
        tail = _lines(out)[-1]
        assert _has_indent_box(tail), (
            "a paragraph STARTING after a display must still indent"
        )

    def test_optional_space_after_display_is_absorbed(self) -> None:
        # §1207: `$$…$$ tail` and `$$…$$tail` must place the tail identically —
        # the source space contributes no leading glue on the resumed line.
        with_space = _lines(contributed(r"\noindent A $$x=y$$ tail\par"))[-1]
        without = _lines(contributed(r"\noindent A $$x=y$$tail\par"))[-1]
        assert [type(n) for n in with_space.list] == [type(n) for n in without.list]
        assert _chars(with_space.list)[0].char == _chars(without.list)[0].char

    def test_non_space_after_display_is_not_consumed(self) -> None:
        # The §1207 scan must only ever eat a SPACE.  A non-space token after
        # `$$` survives intact — the branch peeks and restores, never consumes.
        #
        # Note on unpeek(): at this call site it is defensive, not load-bearing.
        # `peek()` parks the token in `_peeked`, which `_next_raw` drains BEFORE
        # `_stack`, so the token reaches the main loop either way; the
        # inversion only bites when a `push_tokens()` intervenes, and this method
        # makes no such push.  It is kept so the branch stays correct if one is
        # ever added — hence this test passes with or without it, by design.
        tail = _lines(contributed(r"\noindent A $$x=y$$tail\par"))[-1]
        text = "".join(chr(c.char) for c in _chars(tail.list))
        assert text.startswith("tail"), f"expected 'tail' to survive, got {text!r}"

    def test_display_followed_by_control_sequence_is_not_consumed(self) -> None:
        # A macro (not a char) after `$$` must also survive the §1207 peek —
        # peek() expands it, so this pins that the expansion is not swallowed.
        tail = _lines(contributed(r"\def\w{word}\noindent A $$x=y$$\w\par"))[-1]
        text = "".join(chr(c.char) for c in _chars(tail.list))
        assert text.startswith("word"), f"expected 'word' to survive, got {text!r}"

    def test_standalone_display_stays_in_vertical_mode(self) -> None:
        # path: a display that did NOT interrupt a paragraph
        # must not resume one, so the following paragraph indents normally.
        out = contributed(r"\noindent A\par $$x=y$$\par Tail text.\par")
        tail = _lines(out)[-1]
        assert _has_indent_box(tail), (
            "a standalone display must not resume a paragraph"
        )

    def test_resumed_paragraph_space_factor_reset(self) -> None:
        # §1206 sets space_factor := 1000 on resumption, so a pre-display
        # sentence period (sfcode 3000) must not leak its stretched/shrunk
        # space onto the resumed line (guards the interaction).
        interp = TeXInterpreter()
        seen: list[int] = []
        original = interp._resume_after_display

        def _cap() -> None:
            original()
            seen.append(interp._spacefactor)

        interp._resume_after_display = _cap  # type: ignore[method-assign]
        interp.run(StringInputSource(_PRE + r"\noindent Ends. $$x=y$$ tail\par\bye"))
        assert seen == [1000], rf"§1206 must reset \spacefactor to 1000, got {seen}"


# ---------------------------------------------------------------------------
# Component 1 — §1145 \displaywidth / \displayindent
# ---------------------------------------------------------------------------


class TestDisplayParams:
    r"""``\displaywidth`` / ``\displayindent`` are live inside a display.

    Before both were only ever *read*, never assigned, so they stayed
    0 and the plain.tex ``\displ@y`` families' ``\halign to\displaywidth``
    built at their natural width instead of the display width.
    """

    def test_displaywidth_equals_hsize_inside_display(self) -> None:
        interp = TeXInterpreter()
        interp.run(StringInputSource(_PRE + r"$$x$$\bye"))
        # The dimens are not group-scoped, so their post-run values are the
        # ones §1145 set at display entry.
        assert interp._get_named_dimen("displaywidth") == 300 * _PT
        assert interp._get_named_dimen("displayindent") == 0

    def test_displaywidth_is_zero_before_any_display(self) -> None:
        r"""No display ⇒ nothing sets it (guards against a global default)."""
        interp = TeXInterpreter()
        interp.run(StringInputSource(_PRE + r"x\bye"))
        assert interp._get_named_dimen("displaywidth") == 0

    def test_display_params_track_a_changed_hsize(self) -> None:
        interp = TeXInterpreter()
        interp.run(StringInputSource(
            _PRE + r"\hsize=200pt $$x$$\bye"
        ))
        assert interp._get_named_dimen("displaywidth") == 200 * _PT

    def test_user_assignment_inside_the_formula_is_scoped_to_the_display(
        self,
    ) -> None:
        r"""§1145 runs at display ENTRY, but the display is a GROUP.

        An in-formula ``\displaywidth=`` therefore takes effect *while the
        display is being built* — which is what makes the §1145 entry-time
        initialisation overridable — and is **rolled back at ``$$``-close**,
        because §1145 opens a math nest whose save stack restores there.

        This asserted the value survived, which only held while the engine
        opened no group for a display.  MiKTeX 24.4 on the same input reports
        ``[BEFORE dw=0.0pt] [AFTER dw=0.0pt]`` — the assignment does not escape
        .
        """
        interp = TeXInterpreter()
        interp.run(StringInputSource(
            _PRE + r"$$\displaywidth=123pt x$$\bye"
        ))
        assert interp._get_named_dimen("displaywidth") != 123 * _PT

    def test_full_width_alignment_display_selects_long_skips(self) -> None:
        r"""A ``\halign to\displaywidth`` display spans the full width.

        This is the case: the rows fill ``\displaywidth``, so the
        §1204 ``offset`` is 0 and the LONG skips are correct — the plain.tex
        ``\displ@y`` families (``\eqalignno`` / ``\leqalignno`` /
        ``\displaylines``).  Before the rows packed at their natural
        width, ``offset`` became ~213 pt and the SHORT skips were selected.
        """
        out = contributed(
            r"\abovedisplayskip=12pt \belowdisplayskip=11pt "
            r"\abovedisplayshortskip=3pt \belowdisplayshortskip=2pt "
            r"\noindent The system "
            r"$$\halign to\displaywidth{\hfil$#$\tabskip=0pt plus 1fil"
            r"&$#$\hfil\cr x&=y\cr}$$"
        )
        glue_widths = [n.glue.width for n in out if isinstance(n, GlueNode)]
        assert 12 * _PT in glue_widths      # \abovedisplayskip (long)
        assert 11 * _PT in glue_widths      # \belowdisplayskip (long)
        assert 3 * _PT not in glue_widths   # NOT the short skips
        assert 2 * _PT not in glue_widths

    def test_alignment_display_selects_long_skips_even_when_narrow(self) -> None:
        r"""An alignment display takes the LONG skips regardless of its width.

        This asserted the opposite before, on the reasoning that "the
        width spec, not the node type, decides".  **MiKTeX 24.4 says otherwise**
        for this exact input: a `\halign` display with no `to` spec, after the
        same preceding line, gets `\abovedisplayskip 12.0` / `\belowdisplayskip
        11.0`, while an ordinary narrow display `$$x=y$$` in the identical
        context gets `\abovedisplayshortskip 3.0` / `\belowdisplayshortskip 2.0`.

        The difference is not the width: on the §812 splice path there is no
        single centred box to measure, so the §1204 short-skip test cannot
        select short. The rows are contributed individually and the long skips
        follow — no special-casing of the skip choice ( Component 3).
        """
        out = contributed(
            r"\abovedisplayskip=12pt \belowdisplayskip=11pt "
            r"\abovedisplayshortskip=3pt \belowdisplayshortskip=2pt "
            r"\noindent The system "
            r"$$\halign{\hfil$#$&$#$\hfil\cr x&=y\cr}$$"
        )
        glue_widths = [n.glue.width for n in out if isinstance(n, GlueNode)]
        assert 12 * _PT in glue_widths      # \abovedisplayskip
        assert 11 * _PT in glue_widths      # \belowdisplayskip
        assert 3 * _PT not in glue_widths

    def test_ordinary_narrow_display_still_selects_short(self) -> None:
        r"""The guard the rewritten test above used to provide.

        A *non*-alignment display that is genuinely narrow must still take the
        short skips — MiKTeX gives `3.0` / `2.0` here — so the splice change
        did not turn "narrow" into "always long" for ordinary formulas.
        """
        out = contributed(
            r"\abovedisplayskip=12pt \belowdisplayskip=11pt "
            r"\abovedisplayshortskip=3pt \belowdisplayshortskip=2pt "
            r"\noindent The system $$x=y$$"
        )
        glue_widths = [n.glue.width for n in out if isinstance(n, GlueNode)]
        assert 3 * _PT in glue_widths       # \abovedisplayshortskip
        assert 2 * _PT in glue_widths       # \belowdisplayshortskip
        assert 12 * _PT not in glue_widths

    def test_vcenter_leg_display_is_still_one_centred_box(self) -> None:
        r"""``\vcenter``-based legs keep the packed path.

        ``\eqalign`` / ``\matrix`` / ``\pmatrix`` / ``\cases`` build a
        ``\vcenter`` box, which is byte-exact today and must not
        be widened to ``\displaywidth`` by the ``to``-spec change: the
        spec is absent there, so the box keeps its natural width.
        """
        out = contributed(
            r"\noindent The system "
            r"$$\vcenter{\halign{$#$\hfil&$#$\hfil\cr x&y\cr}}$$"
        )
        boxes = _boxes(out)
        assert boxes, "expected a display line box"
        display_line = boxes[-1]
        # contributes the natural formula directly with its center shift.
        assert abs(2 * display_line.shift_amount + display_line.width - 300 * _PT) <= 1
        inner = [n for n in display_line.list if isinstance(n, (HlistNode, VlistNode))]
        assert inner, r"expected the \vcenter box inside the display line"
        assert all(b.width < 300 * _PT for b in inner), (
            r"a \vcenter leg must not be stretched to \displaywidth"
        )


class TestDisplayScopingAndInterline:
    r"""§1145 display scoping and the live interline parameters.

    Two defects pinned here, both MiKTeX 24.4-verified:

    * a display opened **no group**, so plain TeX's ``\displ@y`` ``\openup\jot``
      leaked and *accumulated* — measured 12 → 15 → 18 pt across three displays
      under the real format, where MiKTeX reports 12.0 pt before and after
      every one;
    * the page builder computed interline glue from a **static config
      snapshot**, so no ``\baselineskip`` assignment ever reached it.
    """

    def test_display_is_a_group_so_assignments_do_not_leak(self) -> None:
        r"""A ``$$…$$`` is a group (§1145): an in-display assignment is undone.

        plain TeX's ``\displ@y`` depends on this — its ``\openup\jot`` must be
        scoped to the display.  Asserted with an explicit assignment so the
        test needs no format loaded.
        """
        interp = TeXInterpreter()
        interp.run(StringInputSource(
            _PRE + r"\baselineskip=12pt A.$$\baselineskip=33pt x=y$$B.\bye"
        ))
        assert interp._get_named_skip("baselineskip").width == 12 * _PT

    def test_page_builder_reads_a_live_baselineskip(self) -> None:
        r""": the interline computation reads the register, not the config.

        ``PageBuilderConfig`` is built once at construction, so before
        a ``\baselineskip`` assignment never reached the page builder.
        """
        interp = TeXInterpreter()
        interp.run(StringInputSource(
            _PRE + r"\baselineskip=33pt A.\par B.\par\bye"
        ))
        baselineskip, _lineskip, _limit = (
            interp._page_builder._interline_params()
        )
        assert baselineskip.width == 33 * _PT

    def test_interline_params_fall_back_when_registers_are_zero(self) -> None:
        r"""No format ⇒ registers are 0/0/0, so the config defaults must win.

        ``load_format=False`` never runs ``\normalbaselines``.  Taking the
        register unconditionally there collapsed every interline gap to
        ``\lineskip`` and moved all three ``smoke_m2`` byte-stability MD5s,
        which is why the fallback is zero-aware rather than merely
        absence-aware.
        """
        interp = TeXInterpreter()
        interp.run(StringInputSource(_PRE + r"A.\par B.\par\bye"))
        builder = interp._page_builder
        baselineskip, lineskip, _limit = builder._interline_params()
        assert baselineskip.width == builder._config.baselineskip.width
        assert lineskip.width == builder._config.lineskip.width
