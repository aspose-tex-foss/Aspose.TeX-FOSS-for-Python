r""" cascade (a) — \halign execution.

Covers the two-pass algorithm (AC-1..AC-7), \tabskip glue, ragged rows,
recursive \halign, the preamble/position error matrix, and the migrated
outside-alignment / definition-time-parse / \let\par=\cr assertions from the
retired stub suite.
"""
from __future__ import annotations

import pytest

from aspose_tex._engine.alignment import (
    AlignmentError,
    build_alignment_handlers,
)
from aspose_tex._engine.interpreter import ModeKind, TeXInterpreter
from aspose_tex._engine.nodes import (
    GlueNode,
    HlistNode,
    RuleNode,
    VlistNode,
)
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.reader import StringInputSource
from aspose_tex._input.token import CharToken
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

_NO_FORMAT = TeXOptions(load_format=False)
_FONT_PREAMBLE = r"\font\tenrm=cmr10 \tenrm "


def _run(tex: str) -> None:
    """Run *tex* through a bare interpreter with a DVI device."""
    TeXInterpreter().run_with_device(StringInputSource(tex), DviDevice())


def _run_job(tex: str, options: TeXOptions = _NO_FORMAT) -> TeXJob:
    job = TeXJob(StringInputSource(tex), DviDevice(), options=options)
    job.run()
    return job


def _halign_result(
    body: str, *, spec: str = "", preamble_prefix: str = "",
) -> VlistNode:
    """Run ``\\halign{body}`` (font selected) and return its packed vlist.

    Args:
        body: The preamble + rows placed inside the alignment braces.
        spec: An optional ``to <dimen>`` / ``spread <dimen>`` width spec placed
            between ``\\halign`` and its ``{``.
        preamble_prefix: TeX executed just before the ``\\halign`` (e.g. a
            ``\\tabskip`` assignment).

    Wraps the alignment in ``\\setbox0=\\vbox{…}`` so it takes the
    *packed* path (a box frame is open), whose vlist carries the row hboxes +
    inter-row interline glue — the structure these tests assert on.  (A
    *top-level* ``\\halign`` splices its rows directly into the page's vertical
    list per ``fin_align`` §812, so there is no single packed box to
    capture there; ``tests/test_interline_glue.py`` /
    ``tests/test_alignment_contribution.py`` cover that path.)
    """
    interp = TeXInterpreter()
    interp.run_with_device(
        StringInputSource(
            _FONT_PREAMBLE + preamble_prefix
            + r"\setbox0=\vbox{\halign " + spec + "{" + body + r"}}\bye"
        ),
        DviDevice(),
    )
    result = interp._box_regs.getbox(0)
    assert isinstance(result, VlistNode), "no alignment vbox was built"
    return result


def _row_hboxes(vlist: VlistNode) -> list[HlistNode]:
    return [n for n in vlist.list if isinstance(n, HlistNode)]


def _cell_hboxes(row: HlistNode) -> list[HlistNode]:
    return [n for n in row.list if isinstance(n, HlistNode)]


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

class TestBuildAlignmentHandlers:
    def test_seven_handlers_registered(self) -> None:
        handlers = build_alignment_handlers(TeXInterpreter())
        assert set(handlers) == {
            "halign", "valign", "cr", "crcr", "noalign", "span", "omit",
        }

    def test_handlers_are_callables(self) -> None:
        for handler in build_alignment_handlers(TeXInterpreter()).values():
            assert callable(handler)


# ---------------------------------------------------------------------------
# AC-1..AC-7 — the two-pass algorithm
# ---------------------------------------------------------------------------

class TestHalignAlgorithm:
    def test_ac1_single_column_two_rows(self) -> None:
        vlist = _halign_result(r"#\cr a\cr b\cr")
        rows = _row_hboxes(vlist)
        assert len(rows) == 2

    def test_ac1_single_column_rows_share_width(self) -> None:
        vlist = _halign_result(r"#\cr a\cr b\cr")
        rows = _row_hboxes(vlist)
        # Both rows are repacked to the same column width.
        assert rows[0].width == rows[1].width

    def test_ac2_multi_column_alignment(self) -> None:
        vlist = _halign_result(r"#&#\cr a&b\cr c&d\cr")
        rows = _row_hboxes(vlist)
        assert len(rows) == 2
        cells0 = _cell_hboxes(rows[0])
        cells1 = _cell_hboxes(rows[1])
        assert len(cells0) == len(cells1) == 2
        # Column j has the same width across both rows.
        assert cells0[0].width == cells1[0].width
        assert cells0[1].width == cells1[1].width

    def test_ac3_template_tokens_applied(self) -> None:
        # \hfil#\hfil centres the cell; the cell hbox must carry the fil glue.
        vlist = _halign_result(r"\hfil#\hfil&#\cr x&y\cr")
        rows = _row_hboxes(vlist)
        first_cell = _cell_hboxes(rows[0])[0]
        fil_glues = [
            n for n in first_cell.list
            if isinstance(n, GlueNode) and n.glue.stretch_order.value > 0
        ]
        assert len(fil_glues) == 2

    def test_ac4_noalign_injects_rule_between_rows(self) -> None:
        vlist = _halign_result(r"#\cr a\cr\noalign{\hrule}b\cr")
        kinds = [type(n).__name__ for n in vlist.list]
        assert kinds == ["HlistNode", "RuleNode", "HlistNode"]

    def test_ac5_omit_suppresses_template(self) -> None:
        # With the template, the first cell would carry leading fil glue.
        # \omit suppresses it, so the omitted cell has no fil glue.
        vlist = _halign_result(r"\hfil#&#\cr \omit a&b\cr c&d\cr")
        omitted_cell = _cell_hboxes(_row_hboxes(vlist)[0])[0]
        fil_glues = [
            n for n in omitted_cell.list
            if isinstance(n, GlueNode) and n.glue.stretch_order.value > 0
        ]
        assert fil_glues == []

    def test_ac6_span_merges_cells(self) -> None:
        # \span between two cells fuses their content into one hbox whose body
        # is the concatenation of both cells' node lists. The fused cell holds
        # both characters' CharNodes.
        from aspose_tex._engine.nodes import CharNode

        vlist = _halign_result(r"#&#\cr a\span b\cr")
        cells = _cell_hboxes(_row_hboxes(vlist)[0])
        assert len(cells) == 1
        chars = [n for n in cells[0].list if isinstance(n, CharNode)]
        assert {chr(n.char) for n in chars} == {"a", "b"}

    def test_ac6_span_records_span_count(self) -> None:
        # Inspect the algorithm state directly to assert the merge happened.
        from aspose_tex._engine import alignment

        captured_states: list = []
        original = alignment._measure_columns

        def _spy(state):
            captured_states.append(state)
            return original(state)

        alignment._measure_columns = _spy
        try:
            _run(_FONT_PREAMBLE + r"\halign{#&#\cr a\span b\cr}\bye")
        finally:
            alignment._measure_columns = original
        assert captured_states
        spans = [
            cell.span_count
            for row in captured_states[0].rows
            if isinstance(row, list)
            for cell in row
        ]
        assert 2 in spans

    def test_ac7_everycr_set_inside_a_cell_does_not_escape(self) -> None:
        r"""An ``\everycr`` set in a cell BODY is rolled back at cell end (§791).

        This assertion was inverted before: the engine did not group
        alignment cells, so the in-cell assignment leaked and injected a rule.
        MiKTeX 24.4 emits **no rule** for this exact input — its `\showbox` of
        the surrounding `\vbox` contains only the two row hboxes and their
        `\baselineskip` glue — because the cell group restores `\everycr`
        before the row break fires it.  ``\everycr`` set *outside* the
        alignment still fires every row (see the sibling test below).
        """
        vlist = _halign_result(r"#\cr a\cr\everycr={\noalign{\hrule}}b\cr")
        assert not any(isinstance(n, RuleNode) for n in vlist.list)

    def test_ac7_everycr_set_before_fires_each_row(self) -> None:
        # \everycr={\noalign{\kern1pt}} set before the alignment fires at every
        # row break — a kern is injected between rows.
        # Wrap in \setbox\vbox so the alignment takes the packed path
        # (a box frame is open), whose vlist carries the per-row \everycr kerns.
        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(
                _FONT_PREAMBLE
                + r"\everycr={\noalign{\kern1pt}}\setbox0=\vbox{\halign{#\cr a\cr b\cr}}\bye"
            ),
            DviDevice(),
        )
        box0 = interp._box_regs.getbox(0)
        kinds = [type(n).__name__ for n in box0.list]
        assert kinds.count("KernNode") >= 1


class TestEverycrRecursionGuard:
    """ Q5 — \\everycr whose body ends in \\cr must not loop forever."""

    def test_everycr_with_bare_cr_terminates(self) -> None:
        # Before the firing_everycr guard this looped forever (the everycr-pushed
        # \cr created an empty row that re-fired \everycr). It must now terminate.
        from aspose_tex._engine import alignment

        fire_count = [0]
        original = alignment._fire_everycr

        def _counted(interp, state):
            fire_count[0] += 1
            if fire_count[0] > 1000:
                raise AssertionError("\\everycr fired >1000 times — guard missing")
            return original(interp, state)

        alignment._fire_everycr = _counted
        try:
            _run(_FONT_PREAMBLE + r"\everycr={\cr}\halign{#\cr a\cr}\bye")
        finally:
            alignment._fire_everycr = original
        # Bounded: one fire per genuine \cr (the recursive \cr is suppressed).
        assert fire_count[0] <= 4

    def test_everycr_guard_reenables_for_next_real_row(self) -> None:
        r"""The guard clears after each token list, so every firing contributes.

        TeX fires ``\everycr`` once per `align_peek`, which runs before **every**
        attempt to read a row — including the attempt that finds the closing
        ``}`` — so a 3-row alignment fires **4** times (
        Component 3).  MiKTeX 24.4 ``\showbox`` for this exact input, taken at
        ``\showboxdepth=10 \showboxbreadth=100``, contains four ``\kern 1.0``
        nodes interleaved as ``kern · row · kern · row · kern · row · kern``.

        This asserted ``3`` before, which only held because the leading
        firing was missing.
        """
        from aspose_tex._engine.nodes import KernNode

        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(
                _FONT_PREAMBLE
                + r"\everycr={\noalign{\kern1pt}}\setbox0=\vbox{\halign{#\cr a\cr b\cr c\cr}}\bye"
            ),
            DviDevice(),
        )
        box0 = interp._box_regs.getbox(0)
        kerns = [n for n in box0.list if isinstance(n, KernNode)]
        assert len(kerns) == 4, "3 rows must fire \\everycr 1 + 3 times"
        # The leading firing's kern must come FIRST, before any row.
        assert isinstance(box0.list[0], KernNode), [
            type(n).__name__ for n in box0.list
        ]


# ---------------------------------------------------------------------------
# \tabskip glue (SKIP 267)
# ---------------------------------------------------------------------------

class TestTabskip:
    def test_tabskip_glue_around_columns(self) -> None:
        vlist = _halign_result(r"#&#\cr a&b\cr")  # default tabskip 0
        glues = [n for n in _row_hboxes(vlist)[0].list if isinstance(n, GlueNode)]
        # before col0, between col0/col1, after col1 == 3 tabskip glues.
        assert len(glues) == 3

    def test_tabskip_value_is_live(self) -> None:
        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(
                _FONT_PREAMBLE
                + r"\tabskip=5pt\setbox0=\vbox{\halign{#&#\cr a&b\cr}}\bye"
            ),
            DviDevice(),
        )
        box0 = interp._box_regs.getbox(0)
        row0 = next(n for n in box0.list if isinstance(n, HlistNode))
        glues = [n.glue.width for n in row0.list if isinstance(n, GlueNode)]
        assert glues == [327680, 327680, 327680]  # 5pt == 327680 sp


# ---------------------------------------------------------------------------
# Ragged rows + recursive alignment (Q6)
# ---------------------------------------------------------------------------

class TestRaggedAndRecursive:
    def test_ragged_rows_fewer_cells_than_preamble(self) -> None:
        vlist = _halign_result(r"#&#&#\cr a\cr b&c\cr")
        rows = _row_hboxes(vlist)
        assert len(rows) == 2
        assert len(_cell_hboxes(rows[0])) == 1
        assert len(_cell_hboxes(rows[1])) == 2

    def test_recursive_halign_in_cell(self) -> None:
        vlist = _halign_result(r"#\cr \halign{#\cr p\cr}\cr q\cr")
        # The first row's cell hbox must contain the nested alignment vlist.
        first_cell = _cell_hboxes(_row_hboxes(vlist)[0])[0]
        nested = [n for n in first_cell.list if isinstance(n, VlistNode)]
        assert len(nested) == 1


# ---------------------------------------------------------------------------
# Q7 — error matrix
# ---------------------------------------------------------------------------

class TestPreambleErrors:
    def test_missing_hash_raises_alignment_error(self) -> None:
        with pytest.raises(AlignmentError, match="missing # in alignment preamble"):
            _run(_FONT_PREAMBLE + r"\halign{x\cr a\cr}\bye")

    def test_two_hashes_in_one_column_raise(self) -> None:
        with pytest.raises(AlignmentError, match="more than one #"):
            _run(_FONT_PREAMBLE + r"\halign{##\cr a\cr}\bye")

    def test_alignment_error_is_engine_error(self) -> None:
        assert issubclass(AlignmentError, EngineError)


class TestOutsideAlignment:
    def test_amp_in_outer_vertical_mode_raises(self) -> None:
        with pytest.raises(EngineError, match=r"alignment tab outside \\halign/\\valign"):
            _run(r"&\bye")

    def test_amp_in_horizontal_mode_raises(self) -> None:
        with pytest.raises(EngineError, match=r"alignment tab outside \\halign/\\valign"):
            _run(r"a&b\bye")

    def test_amp_in_restricted_horizontal_mode_raises(self) -> None:
        interp = TeXInterpreter()
        interp.run_with_device(StringInputSource(""), DviDevice())
        interp._mode_stack.push(ModeKind.RESTRICTED_HORIZONTAL)
        with pytest.raises(EngineError, match=r"alignment tab outside \\halign/\\valign"):
            interp._dispatch_char(CharToken("&", Catcode.ALIGNMENT))

    @pytest.mark.parametrize(
        ("name", "message"),
        [
            ("cr", r"\cr outside \halign/\valign"),
            ("crcr", r"\crcr outside \halign/\valign"),
            ("noalign", r"\noalign outside \halign/\valign"),
            ("span", r"\span outside \halign/\valign"),
            ("omit", r"\omit outside \halign/\valign"),
        ],
    )
    def test_outside_alignment_name_raises_engine_error(
        self, name: str, message: str,
    ) -> None:
        with pytest.raises(EngineError) as exc:
            build_alignment_handlers(TeXInterpreter())[name]()
        assert str(exc.value) == message

    def test_amp_inside_macro_body_does_not_raise_at_definition(self) -> None:
        _run(r"\def\foo{a&b}\bye")

    def test_amp_inside_macro_body_raises_at_invocation(self) -> None:
        with pytest.raises(EngineError, match=r"alignment tab outside \\halign/\\valign"):
            _run(r"\def\foo{a&b}\foo\bye")


class TestDefinitionTimeParse:
    def test_def_with_halign_body_does_not_raise(self) -> None:
        _run(r"\def\matrix#1{\halign{##\cr#1}}\bye")

    def test_def_with_amp_in_body_does_not_raise(self) -> None:
        _run(r"\def\foo{a&b\cr}\bye")

    def test_def_with_span_omit_noalign_in_body_does_not_raise(self) -> None:
        _run(r"\def\bar{\span\omit\noalign{x}}\bye")

    def test_nested_def_inside_def_body_parses(self) -> None:
        _run(r"\def\outermacro#1{\def\cr{\crcr\noalign{\let\cr\relax}}#1}\bye")


class TestMacroLetCr:
    def test_let_par_eq_cr_then_calling_par_raises(self) -> None:
        with pytest.raises(EngineError, match=r"\\cr outside \\halign/\\valign"):
            _run(r"\let\par=\cr\par")

    def test_let_par_eq_cr_without_call_succeeds(self) -> None:
        _run_job(r"\let\par=\cr\end")


# ---------------------------------------------------------------------------
# \valign now executes ( cascade b /) — full coverage lives
# in tests/test_alignment_valign.py. A smoke check here guards the dispatch
# wiring shared with \halign.
# ---------------------------------------------------------------------------

class TestValignExecutes:
    def test_valign_no_longer_raises_not_implemented(self) -> None:
        # The cascade-(a) placeholder raised NotImplementedError; cascade (b)
        # replaced it with the real vertical-mirror algorithm.
        _run(_FONT_PREAMBLE + r"\valign{#\cr a\cr b\cr}\bye")


# ---------------------------------------------------------------------------
# — the column u-template must precede the cell body
# ---------------------------------------------------------------------------

class TestUTemplateOrdering:
    r"""The u-part of a column template belongs BEFORE the cell's first token.

    ``_consume_omit_and_template`` peeks for a leading ``\omit``; that peek used
    to park the cell's first token in the expander's ``_peeked`` slot, which
    ``_next_raw`` drains *before* the push-back stack — so the u-template pushed
    immediately afterwards arrived one token late.  In ``alignment_text`` that
    put the template's ``\quad`` (``\hskip10pt``) between the first two glyphs, displacing the
    first glyph by 10 pt and destroying the pair adjacency the lig/kern pass
    needs.  These assert the node ORDER, not the box width: the width is
    identical either way, which is exactly why the defect went unseen.
    """

    def test_u_template_glue_is_the_cells_first_node(self) -> None:
        r"""AC-1: the 10 pt ``\quad`` precedes the cell's first character."""
        from aspose_tex._engine.nodes import CharNode

        vlist = _halign_result(r"#\hfil&\hskip10pt#\hfil\cr a&b\cr")
        cells = _cell_hboxes(_row_hboxes(vlist)[0])
        nodes = cells[1].list

        assert isinstance(nodes[0], GlueNode), (
            f"column-2 cell must open with the u-template glue, got "
            f"{[type(n).__name__ for n in nodes]}"
        )
        assert nodes[0].glue.width == 655360, "u-template glue is a 10pt quad"
        first_char = next(n for n in nodes if isinstance(n, CharNode))
        assert nodes.index(first_char) > 0, "a char must not precede the u-part"

    def test_u_template_does_not_break_lig_kern_adjacency(self) -> None:
        """AC-2: 't' and 'w' stay adjacent, so their kern is still inserted."""
        from aspose_tex._engine.nodes import CharNode

        vlist = _halign_result(r"#\hfil&\hskip10pt#\hfil\cr a&two\cr")
        cells = _cell_hboxes(_row_hboxes(vlist)[0])
        nodes = cells[1].list

        # t-w and w-o both kern in cmr10; neither may be separated by the glue.
        kinds = [type(n).__name__ for n in nodes]
        assert kinds.count("KernNode") == 2, (
            f"both cmr10 kerns must survive the u-template, got {kinds}"
        )
        chars = [chr(n.char) for n in nodes if isinstance(n, CharNode)]
        assert chars == ["t", "w", "o"]
        # Once the characters start, no u-template glue may sit between them.
        first_char_idx = next(
            i for i, n in enumerate(nodes) if isinstance(n, CharNode)
        )
        interior = nodes[first_char_idx : nodes.index(nodes[-1])]
        assert not any(
            isinstance(n, GlueNode) and n.glue.width == 655360 for n in interior
        ), "u-template glue leaked into the middle of the cell"

    def test_omit_still_suppresses_the_template(self) -> None:
        r"""``\omit`` is consumed correctly through the unpeek path."""
        vlist = _halign_result(r"#\hfil&\hskip10pt#\hfil\cr a&\omit b\cr")
        cells = _cell_hboxes(_row_hboxes(vlist)[0])
        widths = [n.glue.width for n in cells[1].list if isinstance(n, GlueNode)]
        assert 655360 not in widths, "omit must suppress the u-template quad"

    def test_empty_u_template_column_is_unchanged(self) -> None:
        """Column 1 has an empty u-part — it must open with its character."""
        from aspose_tex._engine.nodes import CharNode

        vlist = _halign_result(r"#\hfil&\hskip10pt#\hfil\cr ab&c\cr")
        cells = _cell_hboxes(_row_hboxes(vlist)[0])
        assert isinstance(cells[0].list[0], CharNode)
        assert chr(cells[0].list[0].char) == "a"


# ---------------------------------------------------------------------------
# Component 2 — the `to` / `spread` width spec
# ---------------------------------------------------------------------------

class TestAlignmentWidthSpec:
    r"""``\halign to <d>`` / ``spread <d>`` size the row hboxes.

    Before the spec was parsed and discarded ("natural width only"),
    which silently packed ``\halign to\displaywidth`` — the plain.tex
    ``\displ@y`` families — at their natural width.
    """

    def test_to_spec_sets_row_width(self) -> None:
        vlist = _halign_result(r"#&#\cr a&b\cr", spec=r"to 200pt")
        for row in _row_hboxes(vlist):
            assert row.width == 200 * 65536

    def test_spread_spec_widens_by_the_given_amount(self) -> None:
        natural = _row_hboxes(_halign_result(r"#&#\cr a&b\cr"))[0].width
        vlist = _halign_result(r"#&#\cr a&b\cr", spec=r"spread 10pt")
        assert _row_hboxes(vlist)[0].width == natural + 10 * 65536

    def test_no_spec_keeps_natural_width(self) -> None:
        r"""The spec-less corpus must be byte-identical to pre-."""
        vlist = _halign_result(r"#&#\cr a&b\cr")
        row = _row_hboxes(vlist)[0]
        # Natural width is the sum of the row's own contents, not a target.
        content = sum(
            n.width for n in row.list if isinstance(n, HlistNode)
        ) + sum(
            n.glue.width for n in row.list if isinstance(n, GlueNode)
        )
        assert row.width == content

    def test_tabskip_glue_absorbs_the_difference(self) -> None:
        r"""The stretch lands on ``\tabskip``, never on a cell box."""
        from aspose_tex._engine.nodes import GlueSign

        natural_cells = [
            n.width for n in _cell_hboxes(_row_hboxes(_halign_result(
                r"#&#\cr a&b\cr"
            ))[0])
        ]
        vlist = _halign_result(
            r"#&#\cr a&b\cr", preamble_prefix=r"\tabskip=0pt plus 1fil ",
            spec=r"to 200pt",
        )
        row = _row_hboxes(vlist)[0]
        assert row.width == 200 * 65536
        assert row.glue_sign == GlueSign.STRETCHING
        # The cells themselves are untouched — only the tabskip glue stretches.
        assert [n.width for n in _cell_hboxes(row)] == natural_cells


# ---------------------------------------------------------------------------
# Component 1 — the alignment cell is a group (TeX §791)
# ---------------------------------------------------------------------------

class TestCellGroup:
    r"""One logical cell is one group, so template assignments do not leak.

    plain.tex's ``\@lign`` (``\tabskip\z@skip\everycr{}``) is invoked from the
    u-template of every ``\displ@y``-family column.  Without the cell group its
    ``\everycr{}`` escaped and killed ``\everycr`` for the rest of the
    alignment — the defect that blocked.
    """

    @staticmethod
    def _everycr_token_counts(tex: str) -> list[int]:
        r"""Return the ``\everycr`` token count seen at each row break."""
        from aspose_tex._engine import alignment

        seen: list[int] = []
        original = alignment._fire_everycr

        def _spy(interpreter, state):
            seen.append(len(alignment._read_everycr(interpreter)))
            return original(interpreter, state)

        alignment._fire_everycr = _spy
        try:
            interp = TeXInterpreter()
            interp.run_with_device(StringInputSource(tex), DviDevice())
        finally:
            alignment._fire_everycr = original
        return seen

    def test_u_template_everycr_does_not_kill_outer_everycr(self) -> None:
        r"""The ``\@lign`` shape: ``\everycr{}`` issued from a u-template.

        MiKTeX fires the outer body at every row break; before ours
        fired it at none (0 tokens), because the template assignment escaped.
        """
        counts = self._everycr_token_counts(
            _FONT_PREAMBLE
            + r"\def\lgn{\everycr{}}\everycr{\noalign{\kern1pt}}"
            + r"\setbox0=\vbox{\halign{\lgn#\hfil&\lgn#\hfil\cr a&b\cr c&d\cr}}\bye"
        )
        assert counts, r"expected \everycr to be consulted at each row break"
        assert all(n > 0 for n in counts), (
            rf"u-template \everycr{{}} leaked out of its cell: {counts}"
        )

    def test_tabskip_in_a_preamble_is_read_at_preamble_time(self) -> None:
        r"""``\tabskip`` in a preamble is NOT subject to the cell group (§778).

        Deliberately pinned as a boundary of: ``\tabskip`` is scanned
        while the *preamble* is parsed, not while a cell runs, so an assignment
        written into a column template sets every following gap and is never
        rolled back.  MiKTeX 24.4 `\showbox` for this input gives
        ``3.0, 7.0, 7.0`` per row — the leading gap keeps the outer value and
        the rest take the template's.  (``\@lign`` sets ``\tabskip\z@skip`` for
        exactly this effect; only its ``\everycr{}`` needs the group.)
        """
        vlist = _halign_result(
            r"\tabskip=7pt#&#\cr a&b\cr c&d\cr",
            preamble_prefix=r"\tabskip=3pt ",
        )
        for row in _row_hboxes(vlist):
            widths = [n.glue.width for n in row.list if isinstance(n, GlueNode)]
            assert widths == [3 * 65536, 7 * 65536, 7 * 65536], widths

    def test_span_chain_shares_one_group(self) -> None:
        r"""``\span``-merged segments are ONE logical cell, so one group.

        MiKTeX: a ``\def`` in segment 1 is still visible in segment 2, but is
        gone after the row.  Grouping each segment separately would break
        ``\multispan``, whose ``\loop`` keeps state in a local ``\def\body``
        while ``\sp@n`` crosses segment boundaries.
        """
        vlist = _halign_result(r"#&#\cr \def\w{IN}a\span \w b&c\cr")
        rows = _row_hboxes(vlist)
        assert rows, "expected the spanned row to build"

    def test_group_is_balanced_across_cells(self) -> None:
        r"""The cell group is opened and closed symmetrically per logical cell.

        The close is ``finally``-scoped, so an error mid-cell cannot strand it;
        this asserts the balance directly by sampling the group depth at each
        row break, which sits *between* cells.
        """
        from aspose_tex._engine import alignment

        depths: list[int] = []
        original = alignment._fire_everycr

        def _spy(interpreter, state):
            depths.append(interpreter._group_stack.depth)
            return original(interpreter, state)

        alignment._fire_everycr = _spy
        try:
            _halign_result(r"#&#\cr a&b\cr c&d\cr")
        finally:
            alignment._fire_everycr = original

        assert depths, "expected to sample the group depth at a row break"
        assert len(set(depths)) == 1, (
            f"cell groups are not balanced across rows: {depths}"
        )


# ---------------------------------------------------------------------------
# Component 2 — \prevdepth tracks rows during collection
# ---------------------------------------------------------------------------

class TestPrevdepthDuringRowCollection:
    r"""``\prevdepth`` reports the preceding ROW while rows are collected.

    's two-pass model collects rows into ``state.rows`` and contributes
    nothing until pass 2, so before a ``\noalign`` body read whatever
    the *enclosing* list left behind — making plain.tex ``\displ@y``'s
    ``\ifdim\prevdepth>-1000\p@`` guard answer on stale data.
    """

    @staticmethod
    def _prevdepths(tex: str) -> list[float]:
        r"""Return ``\prevdepth`` (in pt) as seen at each ``\noalign``."""
        from aspose_tex._engine import alignment

        seen: list[float] = []
        original = alignment._scan_noalign

        def _spy(interpreter, **kwargs):
            seen.append(interpreter._prev_depth / 65536)
            return original(interpreter, **kwargs)

        alignment._scan_noalign = _spy
        try:
            interp = TeXInterpreter()
            interp.run_with_device(StringInputSource(tex), DviDevice())
        finally:
            alignment._scan_noalign = original
        return seen

    def test_prevdepth_reports_the_previous_row_depth(self) -> None:
        r"""A descender row is seen at its real depth, MiKTeX-exact.

        MiKTeX `\showbox` for this alignment gives ``\hbox(4.30554+1.94444)``
        per row, so ``\prevdepth`` must read **1.94444 pt** after a row.

        Since the list opens with the **leading** firing, which runs
        before any row exists and therefore sees the ``-1000 pt`` sentinel —
        MiKTeX agrees (`[F prevdepth=-1000.0pt]` for a `\halign` at the head of
        a fresh `\vbox`).  Only the per-row firings report a row depth.
        """
        depths = self._prevdepths(
            _FONT_PREAMBLE + r"\everycr{\noalign{\kern1pt}}"
            + r"\setbox0=\vbox{\halign{#\hfil\cr g\cr p\cr}}\bye"
        )
        assert depths, "expected \noalign material at the row breaks"
        assert depths[0] == -1000.0, f"leading firing must see the sentinel: {depths}"
        assert all(abs(d - 1.94444) < 0.001 for d in depths[1:]), depths

    def test_row_depth_is_the_max_cell_depth(self) -> None:
        r"""An hbox's depth is its deepest content, so the row's is too."""
        from aspose_tex._engine.alignment import _row_depth

        vlist = _halign_result(r"#&#\cr x&g\cr")
        row = _row_hboxes(vlist)[0]
        cells = _cell_hboxes(row)
        assert _row_depth(
            [type("C", (), {"box": c})() for c in cells]
        ) == max(c.depth for c in cells)

    def test_prevdepth_is_restored_after_the_alignment(self) -> None:
        r"""The alignment's chain must not leak into the enclosing list."""
        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(
                _FONT_PREAMBLE
                + r"\setbox0=\vbox{\halign{#\hfil\cr g\cr}}\bye"
            ),
            DviDevice(),
        )
        # The \vbox path resets to the sentinel on exit; the alignment's
        # per-row values must not survive it.
        assert interp._prev_depth == -65_536_000


# ---------------------------------------------------------------------------
# — the row-boundary classification runs INSIDE the cell group
# ---------------------------------------------------------------------------

def _row_texts(vlist: VlistNode) -> list[str]:
    """Return the characters of each row, in order."""
    texts = []
    for row in _row_hboxes(vlist):
        chars, stack = [], list(row.list)
        while stack:
            node = stack.pop(0)
            if isinstance(node, (HlistNode, VlistNode)):
                stack = list(node.list) + stack
            elif hasattr(node, "char"):
                chars.append(chr(node.char))
        texts.append("".join(chars))
    return texts


class TestEverycrFiresOncePerAlignPeek:
    r"""``\everycr`` fires ``1 + rows`` times, with material interleaved.

    TeX §785 ``align_peek`` runs before **every** attempt to read a row —
    including the attempt that finds the closing ``}`` — and each run fires
    ``\everycr``.  So an *n*-row alignment fires *n*+1 times and contributes
    ``material(1) · row1 · … · rowN · material(N+1)`` (
    Component 3).  Before the engine fired only after each row, so the
    leading firing was missing.

    Every figure below is MiKTeX 24.4 ``\showbox`` ground truth taken at
    ``\showboxdepth=10 \showboxbreadth=100`` — at plain's defaults the last
    kern is truncated away, which is the measurement trap records.
    """

    @staticmethod
    def _kerns(body: str) -> list[float]:
        from aspose_tex._engine.nodes import KernNode

        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(
                _FONT_PREAMBLE + r"\everycr{\noalign{\kern1pt}}"
                + r"\setbox0=\vbox{" + body + r"}\bye"
            ),
            DviDevice(),
        )
        box = interp._box_regs.getbox(0)
        if box is None:
            return []
        return [n.width / 65536 for n in box.list if isinstance(n, KernNode)]

    @pytest.mark.parametrize(("body", "rows"), [
        (r"\halign{#\cr}", 0),
        (r"\halign{#\cr a\cr}", 1),
        (r"\halign{#\cr a\cr b\cr}", 2),
        (r"\halign{#\cr a\cr b\cr c\cr}", 3),
    ])
    def test_firing_count_is_one_plus_rows(self, body: str, rows: int) -> None:
        assert len(self._kerns(body)) == rows + 1

    def test_zero_row_alignment_still_fires_once(self) -> None:
        r"""The discriminator: a trailing-only model also predicts 1 firing here.

        What separates them is ``\prevdepth`` — it reads the ``-1000 pt``
        sentinel, which only a *leading* firing can see (MiKTeX-verified).
        """
        assert self._kerns(r"\halign{#\cr}") == [1.0]

    def test_material_interleaves_with_rows(self) -> None:
        r"""Order is ``kern · row · kern · row · kern``, not all-trailing."""
        from aspose_tex._engine.nodes import KernNode

        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(
                _FONT_PREAMBLE + r"\everycr{\noalign{\kern1pt}}"
                + r"\setbox0=\vbox{\halign{#\cr a\cr b\cr}}\bye"
            ),
            DviDevice(),
        )
        shape = [
            "kern" if isinstance(n, KernNode)
            else "row" if isinstance(n, HlistNode)
            else "other"
            for n in interp._box_regs.getbox(0).list
        ]
        assert [s for s in shape if s != "other"] == [
            "kern", "row", "kern", "row", "kern",
        ], shape

    def test_crcr_terminated_row_does_not_double_fire(self) -> None:
        r"""``\crcr`` closing the last row still gives ``1 + rows`` (AC-7)."""
        assert len(self._kerns(r"\halign{#\cr a\cr b\crcr}")) == 3

    def test_canonical_prevdepth_branch_probe(self) -> None:
        r"""The cascade's canonical probe now yields MiKTeX's ``13, 7, 7``.

        This is's AC-1, which was unreachable until the leading firing
        existed: the ``13`` is the ``\else`` branch taken at the sentinel, and
        it belongs to a firing that precedes row 1.
        """
        from aspose_tex._engine.nodes import KernNode

        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(
                _FONT_PREAMBLE
                + r"\everycr{\noalign{\ifdim\prevdepth>-1000pt \kern7pt"
                r" \else \kern13pt \fi}}"
                + r"\setbox0=\vbox{\halign{#\hfil\cr a\cr b\cr}}\bye"
            ),
            DviDevice(),
        )
        kerns = [
            round(n.width / 65536, 1)
            for n in interp._box_regs.getbox(0).list
            if isinstance(n, KernNode)
        ]
        assert kerns == [13.0, 7.0, 7.0]

    def test_recursion_guard_is_clear_when_the_row_loop_starts(self) -> None:
        r"""The leading firing must not leave ``firing_everycr`` set (AC-6).

        If it did, the first genuine row break would silently skip its firing.
        Asserted indirectly and robustly: the per-row kerns are all present.
        """
        assert self._kerns(r"\halign{#\cr a\cr b\cr c\cr}") == [1.0] * 4


class TestPrevdepthIsInheritedNotReset:
    r"""An alignment INHERITS ``\prevdepth``; TeX never resets it (Component 5).

    Component 2 originally seeded the ``-1000 pt`` sentinel on entering
    an alignment.  That is wrong, and it only looked right because the case
    tested — a ``\halign`` at the head of a fresh ``\vbox`` — is
    indistinguishable from it: there the *``\vbox``* supplies the sentinel.

    MiKTeX 24.4 at the leading ``\everycr`` firing: ``-1000`` in a fresh
    ``\vbox``, **0.0** after an ``\hbox``, **7.0** after ``\prevdepth=7pt``.
    """

    @staticmethod
    def _leading_prevdepth(body: str) -> float:
        from aspose_tex._engine import alignment

        seen: list[float] = []
        original = alignment._scan_noalign

        def _spy(interpreter, **kwargs):
            seen.append(interpreter._prev_depth / 65536)
            return original(interpreter, **kwargs)

        alignment._scan_noalign = _spy
        try:
            interp = TeXInterpreter()
            interp.run_with_device(
                StringInputSource(
                    _FONT_PREAMBLE + r"\everycr{\noalign{\kern1pt}}"
                    + r"\setbox0=\vbox{" + body + r"}\bye"
                ),
                DviDevice(),
            )
        finally:
            alignment._scan_noalign = original
        return seen[0]

    def test_fresh_vbox_gives_the_sentinel(self) -> None:
        r"""The `\vbox` seeds it — this is the case AC-3 pins."""
        assert self._leading_prevdepth(r"\halign{#\hfil\cr a\cr}") == -1000.0

    def test_after_an_hbox_the_alignment_inherits_zero(self) -> None:
        assert self._leading_prevdepth(
            r"\hbox{X}\halign{#\hfil\cr a\cr}"
        ) == 0.0

    def test_an_explicit_prevdepth_is_inherited(self) -> None:
        assert self._leading_prevdepth(
            r"\prevdepth=7pt \halign{#\hfil\cr a\cr}"
        ) == 7.0


class TestDisplayHandsOverPrevdepth:
    r"""A display's alignment starts from the pre-display line's depth (AC-5).

    TeX ends and contributes the interrupted paragraph *before* the display's
    ``\halign`` collects rows, so the leading firing sees that line's depth —
    which is what plain.tex ``\displ@y``'s ``\ifdim\prevdepth>-1000\p@`` guard
    tests before emitting its ``\vskip`` pair.  Our two-pass model
    collects the rows first, so the value is handed over explicitly
    ( Component 5).
    """

    @staticmethod
    def _noalign_material(tex: str) -> list[list[str]]:
        from aspose_tex._engine import alignment

        out: list[list[str]] = []
        original = alignment._scan_noalign

        def _spy(interpreter, **kwargs):
            record = original(interpreter, **kwargs)
            out.append([type(n).__name__ for n in record.nodes])
            return record

        alignment._scan_noalign = _spy
        try:
            _run_job(tex, TeXOptions(load_format="plain"))
        finally:
            alignment._scan_noalign = original
        return out

    def test_eqalignno_leading_firing_carries_the_vskip_pair(self) -> None:
        r"""MiKTeX: firing 1 = two glue nodes, firings 2/3 = one penalty each.

        Before Component 5 firing 1 was empty, because the alignment started at
        the sentinel and `\displ@y`'s guard was therefore false.
        """
        material = self._noalign_material(
            "Text before."
            r"$$\eqalignno{u&=v&(1)\cr p&=q&(2)\cr}$$"
            "\n" r"\bye"
        )
        assert material[0] == ["GlueNode", "GlueNode"], material
        assert all(m == ["PenaltyNode"] for m in material[1:]), material


class TestRowBoundaryClassificationScope:
    r"""A ``\def`` as a cell's FIRST token must not escape the cell.

    TeX §785 ``align_peek`` classifies the row boundary with an *expanding*
    read, so a macro sitting there is expanded — but in TeX that happens with
    the row/cell group already open (§791), so anything non-structural it
    executes is rolled back at cell end.  We classified the boundary *outside*
    the group, so a leading assignment was saved one frame too shallow and
    survived the row.

    Every expectation below is MiKTeX 24.4 ground truth, taken by ``\showbox``
    and ``\message`` before the fix was written.
    """

    def test_def_as_first_cell_token_is_rolled_back(self) -> None:
        r"""``\halign{#\cr \def\g{Z}a\cr \g\cr}`` renders ``Y``, not ``Z``.

        MiKTeX ``\showbox``: row 2 is ``\tenrm Y``.  Ours rendered ``Z`` — the
        leak this task exists to close.
        """
        vlist = _halign_result(
            r"#\cr \def\g{Z}a\cr \g\cr", preamble_prefix=r"\def\g{Y}",
        )
        assert _row_texts(vlist) == ["a", "Y"]

    def test_def_reached_through_a_macro_is_also_rolled_back(self) -> None:
        r"""The assignment need not be written literally at the boundary.

        ``\def\ord{\def\g{Z}a}`` puts the assignment *inside* the macro the
        boundary peek expands.  MiKTeX still reports ``Y`` (measured:
        ``[MACRO-EXPANDS-TO-DEF: after=Y]``), because expansion happens with
        the cell group already open.  This is the case a purely raw-peek fix
        would NOT have closed.
        """
        vlist = _halign_result(
            r"#\cr \ord\cr \g\cr",
            preamble_prefix=r"\def\ord{\def\g{Z}a}\def\g{Y}",
        )
        assert _row_texts(vlist) == ["a", "Y"]

    def test_def_after_cell_content_stays_rolled_back(self) -> None:
        r"""The already-correct case must not regress (AC-2)."""
        vlist = _halign_result(
            r"#\cr a\def\g{Z}\cr \g\cr", preamble_prefix=r"\def\g{Y}",
        )
        assert _row_texts(vlist) == ["a", "Y"]

    def test_global_still_escapes_the_cell_group(self) -> None:
        r"""``\global`` must still escape (AC-3).

        ``\bordermatrix``'s ``\global\let\cr\endline`` self-alias depends on
        this, and it is what ``\global`` *means*.
        """
        vlist = _halign_result(
            r"#\cr \global\def\g{Z}a\cr \g\cr", preamble_prefix=r"\def\g{Y}",
        )
        assert _row_texts(vlist) == ["a", "Z"]

    def test_boundary_expansion_into_noalign_is_still_honoured(self) -> None:
        r"""A macro expanding to ``\noalign`` still works (AC-4).

        This is the guard against "fix it with a raw peek": TeX's boundary read
        is expanding, and MiKTeX's ``\showbox`` for this input contains
        ``\kern 3.0`` between the rows.  A raw peek would classify ``\mn`` as
        ordinary cell material and lose the ``\noalign`` entirely.
        """
        vlist = _halign_result(
            r"#\cr a\cr \mn b\cr",
            preamble_prefix=r"\def\mn{\noalign{\kern3pt}}",
        )
        kerns = [n.width for n in vlist.list if type(n).__name__ == "KernNode"]
        assert 3 * 65536 in kerns, kerns
        assert _row_texts(vlist) == ["a", "b"]

    def test_boundary_expansion_into_a_whole_row_is_still_honoured(self) -> None:
        r"""A macro expanding to ``x\cr`` still produces a row (AC-4).

        MiKTeX ``\showbox`` gives two rows, ``a`` then ``x``.
        """
        vlist = _halign_result(
            r"#\cr a\cr \myrow", preamble_prefix=r"\def\myrow{x\cr}",
        )
        assert _row_texts(vlist) == ["a", "x"]

    def test_let_aliased_noalign_is_still_recognised(self) -> None:
        r"""``\let\na=\noalign`` at the boundary still works (AC-4,)."""
        vlist = _halign_result(
            r"#\cr a\cr \na{\kern3pt}b\cr", preamble_prefix=r"\let\na=\noalign",
        )
        kerns = [n.width for n in vlist.list if type(n).__name__ == "KernNode"]
        assert 3 * 65536 in kerns, kerns

    def test_noalign_is_not_inside_the_cell_group(self) -> None:
        r"""``\noalign`` keeps its own alignment-level group.

        The speculative cell group is closed before the ``\noalign`` body is
        scanned, so its own ``\def`` is still rolled back by ITS group and not
        by the cell's.  MiKTeX: ``[AFTER-NOALIGN-DEF=Y]``.
        """
        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(
                _FONT_PREAMBLE + r"\def\n{Y}"
                + r"\setbox0=\vbox{\halign{#\cr a\cr\noalign{\def\n{Z}}b\cr}}\bye"
            ),
            DviDevice(),
        )
        macro = interp._expander._macros["n"]
        assert "".join(t.char for t in macro.replacement) == "Y"

    def test_multi_cell_rows_still_group_per_cell(self) -> None:
        r"""Only the row's FIRST cell reuses the pre-opened group.

        Cells after ``&`` open their own, so a ``\def`` leading the *second*
        cell is rolled back at that cell's end just the same.
        """
        vlist = _halign_result(
            r"#&#\cr a&\def\g{Z}b\cr \g&x\cr", preamble_prefix=r"\def\g{Y}",
        )
        assert _row_texts(vlist) == ["ab", "Yx"]

    def test_group_depth_is_unchanged_at_row_breaks(self) -> None:
        r"""The pre-opened group must not deepen the nesting seen between rows.

        Guards the balance directly: if the speculative group were left open on
        any classification branch, the depth sampled at successive row breaks
        would climb.
        """
        from aspose_tex._engine import alignment

        depths: list[int] = []
        original = alignment._fire_everycr

        def _spy(interpreter, state):
            depths.append(interpreter._group_stack.depth)
            return original(interpreter, state)

        alignment._fire_everycr = _spy
        try:
            _halign_result(r"#\cr a\cr\noalign{\kern1pt}b\cr c\cr")
        finally:
            alignment._fire_everycr = original

        assert depths, "expected to sample the group depth at a row break"
        assert len(set(depths)) == 1, f"group depth drifts across rows: {depths}"


# ---------------------------------------------------------------------------
# — a blank line / \par inside an alignment is a no-op, as in TeX
# ---------------------------------------------------------------------------

def _shape(node) -> tuple:
    """Return a hashable recursive (type, dims, chars) shape of *node*."""
    if isinstance(node, (HlistNode, VlistNode)):
        return (
            type(node).__name__, node.width, node.height, node.depth,
            tuple(_shape(child) for child in node.list),
        )
    if hasattr(node, "char"):
        return ("char", node.char)
    if isinstance(node, GlueNode):
        return ("glue", node.glue.width)
    return (type(node).__name__,)


def _box0(tex: str):
    """Run *tex* (font selected) and return box register 0."""
    interp = TeXInterpreter()
    interp.run_with_device(
        StringInputSource(_FONT_PREAMBLE + tex + r"\bye"), DviDevice(),
    )
    return interp._box_regs.getbox(0)


class TestParInAlignmentIsANoOp:
    r"""A blank line (``\par``) inside an ``\halign`` is legal and vanishes.

    TeX §785 ``align_peek`` does **not** skip ``\par``: it skips only spaces,
    so a ``\par`` at a row boundary starts a new row and becomes the first
    token of its cell.  There it is a no-op, because §1094 ``hmode+par_end``
    calls ``end_graf``, which acts only when ``mode=hmode`` — never in the
    *restricted* horizontal mode of a cell.  We rejected it outright
    (``Unexpected token in hbox: \par``).

    Every expectation is MiKTeX 24.4 ``\showbox`` ground truth: the three
    task cases are row-for-row identical to the alignment written without the
    blank line (``[CASE1-OK] [CASE2-OK] [CASE3-OK]``), ``\hbox{a\par b}`` is
    ``ab``, and a blank line *before the closing* ``}`` is
    ``! Missing \cr inserted`` — the proof that the discard is not a
    row-boundary skip.
    """

    def test_blank_line_between_rows_matches_the_unbroken_alignment(
        self,
    ) -> None:
        """AC-1 / AC-5: the readable form builds the very same box."""
        broken = _halign_result(r"#\cr a\cr" "\n\n" r"b\cr")
        unbroken = _halign_result(r"#\cr a\cr b\cr")
        assert _row_texts(broken) == ["a", "b"]
        assert _shape(broken) == _shape(unbroken)

    def test_explicit_par_at_a_row_boundary_is_discarded(self) -> None:
        """AC-2 (MiKTeX ``[CASE2-OK]``)."""
        broken = _halign_result(r"#\cr a\cr\par b\cr")
        assert _shape(broken) == _shape(_halign_result(r"#\cr a\cr b\cr"))

    def test_blank_line_with_a_u_template_matches(self) -> None:
        r"""The ``\par`` follows the u-template, so ``\hfil`` still leads."""
        broken = _halign_result(r"\hfil#\cr a\cr" "\n\n" r"b\cr")
        unbroken = _halign_result(r"\hfil#\cr a\cr b\cr")
        assert _shape(broken) == _shape(unbroken)

    def test_blank_line_inside_a_cell_keeps_only_the_line_end_space(
        self,
    ) -> None:
        r"""AC-3: ``a`` + blank line + ``c`` is ``a␣c`` (MiKTeX ``[CASE3-OK]``).

        MiKTeX ``\showbox``: ``\tenrm a``, ``\glue 3.33333 plus 1.66666 minus
        1.11111``, ``\tenrm c`` in a 12.77779 pt cell — the space comes from the
        end of the ``a`` line, and the ``\par`` from the blank line adds nothing.
        """
        vlist = _halign_result(r"#\cr a" "\n\n" r"c\cr b\cr")
        assert _row_texts(vlist) == ["ac", "b"]
        cell = _row_hboxes(vlist)[0].list[1]
        assert [type(n).__name__ for n in cell.list] == [
            "CharNode", "GlueNode", "CharNode",
        ]
        assert cell.width == round(12.77779 * 65536)

    def test_par_in_a_later_cell_is_discarded(self) -> None:
        r"""Not only the row's first cell: ``a&\par b`` is ``a&b``.

        Written with an explicit ``\par``; the ``a&`` + blank line form also
        carries the line-end *space* after ``&`` (TeX §791 skips it —,
        see :class:`TestSpacesAfterTabAreSkipped`).
        """
        broken = _halign_result(r"#&#\cr a&\par b\cr")
        assert _shape(broken) == _shape(_halign_result(r"#&#\cr a&b\cr"))

    def test_par_in_a_restricted_hbox_is_a_no_op(self) -> None:
        r"""``\hbox{a\par b}`` is ``ab`` — the same §1094 rule outside alignments."""
        box = _box0(r"\setbox0=\hbox{a\par b}")
        assert [chr(n.char) for n in box.list] == ["a", "b"]

    def test_let_alias_of_par_is_also_a_no_op(self) -> None:
        r"""plain.tex's ``\let\endgraf=\par`` has ``\par``'s meaning."""
        box = _box0(r"\let\endgraf=\par \setbox0=\hbox{a\endgraf b}")
        assert [chr(n.char) for n in box.list] == ["a", "b"]

    def test_par_still_ends_a_paragraph_in_a_vbox(self) -> None:
        r"""AC-4: where TeX genuinely ends a paragraph, ``\par`` still does."""
        box = _box0(r"\setbox0=\vbox{\hsize=100pt a\par b}")
        lines = [n for n in box.list if isinstance(n, HlistNode)]
        assert len(lines) == 2

    def test_par_still_ends_a_paragraph_in_a_vbox_inside_a_cell(self) -> None:
        r"""AC-4: the no-op does not leak into a paragraph nested in a cell."""
        vlist = _halign_result(r"#\cr \vbox{\hsize=100pt a\par b}\cr")
        cell = _row_hboxes(vlist)[0].list[1]
        inner = next(n for n in cell.list if isinstance(n, VlistNode))
        lines = [n for n in inner.list if isinstance(n, HlistNode)]
        assert len(lines) == 2


def _code_array_state(tex: str) -> TeXInterpreter:
    """Run *tex* (font selected) and return the interpreter for inspection."""
    interp = TeXInterpreter()
    interp.run_with_device(
        StringInputSource(_FONT_PREAMBLE + tex + r"\bye"), DviDevice(),
    )
    return interp


# (primitive, assignment, value read back after a local assignment, after a
# \global one).  Every pair is MiKTeX 24.4 ground truth (\message{\the…}).
_CODE_ARRAY_CASES = [
    ("catcode", r"\catcode`\@=11 ", 12, 11),
    ("mathcode", r'\mathcode`\a="7141 ', 0x7161, 0x7141),
    ("sfcode", r"\sfcode`\a=999 ", 1000, 999),
    ("lccode", r"\lccode`\a=98 ", 97, 98),
    ("uccode", r"\uccode`\a=66 ", 65, 66),
    ("delcode", r'\delcode`\a="161300 ', -1, 0x161300),
]


def _read_code(interp: TeXInterpreter, prim: str) -> int:
    if prim == "catcode":
        return int(interp._catcodes.get("@"))
    return getattr(interp._code_arrays, f"get_{prim}")(ord("a"))


class TestCodeArrayAssignmentInBoxScanners:
    r"""``\catcode`` and the other code arrays execute inside box scanners.

    : the shared restricted-horizontal dispatcher, and both vbox
    scanners, had no arm for the code-array primitives, so
    ``\halign{#\cr \catcode`\@=11 a\cr}`` raised "Unexpected token in hbox" —
    and so did a plain ``\hbox{\catcode`\@=11 }`` (the cell symptom is the
    hbox gap; AC-4).  MiKTeX 24.4 builds all of these, runs the assignment,
    and rolls it back at the end of the enclosing group.
    """

    def test_catcode_in_a_cell_builds_and_is_rolled_back(self) -> None:
        """AC-1 + AC-2: the task's reproducer, both rows built, ``@`` back at 12."""
        interp = _code_array_state(
            r"\setbox0=\vbox{\halign{#\cr \catcode`\@=11 a\cr b\cr}}",
        )
        assert _row_texts(interp._box_regs.getbox(0)) == ["a", "b"]
        assert int(interp._catcodes.get("@")) == 12

    def test_catcode_takes_effect_inside_the_cell(self) -> None:
        r"""The assignment really runs: ``\a@b`` tokenizes as one name.

        MiKTeX ``\showbox``: rows ``Q`` then ``Y`` — the cell sees ``@`` as a
        letter, the next row (after the cell group closed) does not need to.
        """
        vlist = _halign_result(
            r"#\cr \catcode`\@=11 \def\a@b{Q}\a@b\cr \q\cr",
            preamble_prefix=r"\def\q{Y}",
        )
        assert _row_texts(vlist) == ["Q", "Y"]

    def test_lccode_takes_effect_inside_the_cell(self) -> None:
        r"""MiKTeX ``\showbox``: ``z`` then ``a`` — rolled back for row 2."""
        vlist = _halign_result(r"#\cr \lccode`\a=`\z \lowercase{a}\cr a\cr")
        assert _row_texts(vlist) == ["z", "a"]

    @pytest.mark.parametrize(("prim", "assign", "local", "global_"), _CODE_ARRAY_CASES)
    def test_every_code_array_in_a_cell(
        self, prim: str, assign: str, local: int, global_: int,
    ) -> None:
        r"""AC-2 + AC-3 + AC-5: local is rolled back, ``\global`` escapes."""
        def cell(assignment: str) -> str:
            return r"\setbox0=\vbox{\halign{#\cr " + assignment + r"a\cr b\cr}}"

        interp = _code_array_state(cell(assign))
        assert _read_code(interp, prim) == local
        interp = _code_array_state(cell(r"\global" + assign))
        assert _read_code(interp, prim) == global_

    @pytest.mark.parametrize(("prim", "assign", "local", "global_"), _CODE_ARRAY_CASES)
    @pytest.mark.parametrize("box", ["hbox", "vbox"])
    def test_every_code_array_in_a_plain_box(
        self, box: str, prim: str, assign: str, local: int, global_: int,
    ) -> None:
        r"""AC-4: the same gap existed in ``\hbox`` and ``\vbox`` themselves."""
        def plain_box(assignment: str) -> str:
            return r"\setbox0=" + "\\" + box + "{" + assignment + "a}"

        interp = _code_array_state(plain_box(assign))
        assert _read_code(interp, prim) == local
        interp = _code_array_state(plain_box(r"\global" + assign))
        assert _read_code(interp, prim) == global_

    def test_catcode_in_vbox_text_line(self) -> None:
        r"""The third scanner: an assignment after text opened a vbox line."""
        interp = _code_array_state(r"\setbox0=\vbox{a\catcode`\@=11 b}")
        assert int(interp._catcodes.get("@")) == 12

    def test_out_of_range_catcode_still_raises(self) -> None:
        """The interpreter's own range check runs — no second, laxer path."""
        with pytest.raises(EngineError, match="out of range"):
            _code_array_state(r"\setbox0=\hbox{\catcode`\@=16 a}")


# ---------------------------------------------------------------------------
# — spaces after & / \span are skipped before the cell starts (§791)
# ---------------------------------------------------------------------------

_SP = 65536


def _cell_chars(cell: HlistNode) -> list[str]:
    """Node kinds of *cell*, with glyphs spelled out (``GlueNode`` / ``b``)."""
    return [
        chr(n.char) if hasattr(n, "char") else type(n).__name__
        for n in cell.list
    ]


class TestSpacesAfterTabAreSkipped:
    r"""TeX §791 ``fin_col`` skips spaces, with expansion, after ``&``.

    ``repeat get_x_or_protected until cur_cmd<>spacer`` runs before §788
    ``init_col`` looks for ``\omit`` and inserts the u-template, so a space
    after ``&`` is neither cell glue nor a mask over ``\omit``.  We kept it as
    a leading 3.33333 pt interword glue and raised ``Unexpected token in hbox:
    \omit`` on ``a& \omit b``.

    Every expectation is MiKTeX 24.4 ``\showbox`` ground truth
    (``\showboxdepth=10 \showboxbreadth=100``).
    """

    def test_space_after_tab_is_not_cell_glue(self) -> None:
        r"""AC-1: ``a& b`` — cell 2 is ``\tenrm b`` alone, 5.55557 pt."""
        cells = _cell_hboxes(_row_hboxes(_halign_result(r"#&#\cr a& b\cr"))[0])
        assert _cell_chars(cells[1]) == ["b"]
        assert cells[1].width == round(5.55557 * _SP)

    def test_space_before_omit_still_omits(self) -> None:
        r"""AC-2: ``a& \omit b`` suppresses the ``[#]`` template."""
        cells = _cell_hboxes(
            _row_hboxes(_halign_result(r"#&[#]\cr a& \omit b\cr"))[0]
        )
        assert _cell_chars(cells[1]) == ["b"]
        assert cells[1].width == round(5.55557 * _SP)

    def test_spaced_and_unspaced_rows_build_the_same_box(self) -> None:
        """How plain-TeX tables are written: ``a & b`` equals ``a&b``."""
        spaced = _halign_result(r"#&#&#\cr a&  b& c\cr")
        assert _shape(spaced) == _shape(_halign_result(r"#&#&#\cr a&b&c\cr"))

    def test_space_after_tab_precedes_the_u_template(self) -> None:
        r""": the u-template still leads — ``\hfil`` first, then ``b``."""
        spaced = _halign_result(r"#&\hfil#\cr a& b\cr")
        assert _shape(spaced) == _shape(_halign_result(r"#&\hfil#\cr a&b\cr"))

    def test_macros_expanding_to_nothing_or_a_space_are_skipped(self) -> None:
        r"""AC-3: the skip expands, so ``\e`` (empty) and ``\s`` (a space) vanish.

        MiKTeX: ``a& \e \s\omit b`` gives cell 2 = ``\tenrm b``, 5.55557 pt.
        """
        cells = _cell_hboxes(_row_hboxes(_halign_result(
            r"#&[#]\cr a& \e \s\omit b\cr",
            preamble_prefix=r"\def\e{}\def\s{ }",
        ))[0])
        assert _cell_chars(cells[1]) == ["b"]
        assert cells[1].width == round(5.55557 * _SP)

    def test_space_after_span_is_skipped(self) -> None:
        r"""§791 runs after ``\span`` too; the space *before* it stays in the cell.

        MiKTeX: the spanned cell is ``\tenrm b``, ``\glue 3.33333…``,
        ``\tenrm c`` — one glue, from ``b␣``, none from ``\span␣``.
        """
        vlist = _halign_result(r"#&#&#\cr a& b \span c\cr")
        cells = _cell_hboxes(_row_hboxes(vlist)[0])
        assert _cell_chars(cells[1]) == ["b", "GlueNode", "c"]

    def test_space_then_blank_line_after_tab(self) -> None:
        r"""``a&`` + blank line + ``b``: the line-end space skips, ``\par`` no-ops."""
        broken = _halign_result(r"#&#\cr a&" "\n\n" r"b\cr")
        assert _shape(broken) == _shape(_halign_result(r"#&#\cr a&b\cr"))

    def test_space_before_omit_in_a_math_alignment(self) -> None:
        r"""AC-3: the raw peek path (a ``$#$`` preamble) skips raw spaces.

        MiKTeX: ``\halign{$#$&$#$\cr a& \omit b\cr}`` — cell 2 is ``\tenrm b``
        (template and math both suppressed), 5.55557 pt.
        """
        cells = _cell_hboxes(
            _row_hboxes(_halign_result(r"$#$&$#$\cr a& \omit b\cr"))[0]
        )
        assert _cell_chars(cells[1]) == ["b"]
        assert cells[1].width == round(5.55557 * _SP)

    def test_spaced_table_dvi_matches_unspaced_through_public_api(self) -> None:
        r"""Integration: plain.tex + ``TeXJob`` — ``a& b`` ships ``a&b``'s DVI.

        The space after ``&`` is skipped by §791 before the ``\quad`` u-template
        and before ``\omit`` is recognised, so both forms are byte-identical.
        """
        def dvi(rows: str) -> bytes:
            job = TeXJob(
                StringInputSource(r"\halign{#\hfil&\quad#\hfil\cr " + rows + r"}\bye"),
                DviDevice(),
                options=TeXOptions(load_format="plain"),
            )
            out = job.run()
            assert out is not None
            return out

        assert dvi(r"one& two\cr three& \omit four\cr") == dvi(
            r"one&two\cr three&\omit four\cr"
        )
