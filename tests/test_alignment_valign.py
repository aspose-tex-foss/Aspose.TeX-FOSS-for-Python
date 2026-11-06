r""" cascade (b) — \valign execution.

\valign is the vertical mirror of \halign: cells are wrapped as vboxes, the
aligned dimension is natural height, and the result is an *hlist* of column
vboxes (the transpose of \halign's vlist of row hboxes).

Covers AC-11 (\valign → hlist of vboxes), \tabskip between vertical-alignment
columns (AC #4), the \omit / \span surface in vertical mode, ragged columns,
and recursive \valign-in-cell.
"""
from __future__ import annotations

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import (
    CharNode,
    GlueNode,
    HlistNode,
    VlistNode,
)
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice

_FONT_PREAMBLE = r"\font\tenrm=cmr10 \tenrm "


def _valign_result(body: str, *, preamble: str = "") -> HlistNode:
    r"""Run ``\valign{body}`` (font selected) and return the captured hlist."""
    interp = TeXInterpreter()
    captured: list = []
    original = interp._add_box_to_current_list

    def _hook(box):
        captured.append(box)
        return original(box)

    interp._add_box_to_current_list = _hook
    interp.run_with_device(
        StringInputSource(_FONT_PREAMBLE + preamble + r"\valign{" + body + r"}\bye"),
        DviDevice(),
    )
    assert captured, "no alignment box was contributed"
    result = captured[0]
    assert isinstance(result, HlistNode), "\\valign must yield an hlist of vboxes"
    return result


def _column_vboxes(hlist: HlistNode) -> list[VlistNode]:
    return [n for n in hlist.list if isinstance(n, VlistNode)]


def _stacked_cells(column: VlistNode) -> list[VlistNode]:
    """Return the per-cell vboxes stacked inside a column vbox."""
    return [n for n in column.list if isinstance(n, VlistNode)]


def _chars_in(box) -> set[str]:
    out: set[str] = set()
    for node in box.list:
        if isinstance(node, CharNode):
            out.add(chr(node.char))
        elif isinstance(node, (HlistNode, VlistNode)):
            out |= _chars_in(node)
    return out


def _descendants(box, kind):
    """Yield all nodes of *kind* nested anywhere inside *box*."""
    for node in getattr(box, "list", []):
        if isinstance(node, kind):
            yield node
        if isinstance(node, (HlistNode, VlistNode)):
            yield from _descendants(node, kind)


# ---------------------------------------------------------------------------
# AC-11 — \valign → hlist of column vboxes
# ---------------------------------------------------------------------------

class TestValignAlgorithm:
    def test_ac11_single_column_two_rows(self) -> None:
        # \valign{#\cr a\cr b\cr}: one preamble column, two body rows → an hlist
        # of two column vboxes (the transpose).
        hlist = _valign_result(r"#\cr a\cr b\cr")
        cols = _column_vboxes(hlist)
        assert len(cols) == 2

    def test_ac11_result_is_hlist_not_vlist(self) -> None:
        hlist = _valign_result(r"#\cr a\cr b\cr")
        assert isinstance(hlist, HlistNode)

    def test_ac11_columns_share_aligned_height(self) -> None:
        # Each column vbox is repacked to the common aligned height.
        hlist = _valign_result(r"#\cr a\cr b\cr")
        cols = _column_vboxes(hlist)
        assert cols[0].height == cols[1].height

    def test_cells_are_vboxes(self) -> None:
        # A \valign cell is a vbox (the vertical mirror of the \halign hbox).
        hlist = _valign_result(r"#\cr a\cr b\cr")
        for col in _column_vboxes(hlist):
            assert _stacked_cells(col), "column must stack vbox cells"

    def test_multi_column_transpose(self) -> None:
        # 2 preamble columns, 2 body rows. Each body row becomes a column vbox
        # stacking its two cells.
        hlist = _valign_result(r"#&#\cr a&b\cr c&d\cr")
        cols = _column_vboxes(hlist)
        assert len(cols) == 2
        for col in cols:
            assert len(_stacked_cells(col)) == 2

    def test_cell_content_preserved(self) -> None:
        hlist = _valign_result(r"#\cr a\cr b\cr")
        cols = _column_vboxes(hlist)
        assert _chars_in(cols[0]) == {"a"}
        assert _chars_in(cols[1]) == {"b"}

    def test_template_tokens_applied(self) -> None:
        # \kern1pt#\cr applies the u-template to each cell — a kern appears
        # inside the cell box (nested in the cell's horizontal strip).
        from aspose_tex._engine.nodes import KernNode

        hlist = _valign_result(r"\kern1pt#\cr a\cr")
        col = _column_vboxes(hlist)[0]
        cell = _stacked_cells(col)[0]
        kerns = list(_descendants(cell, KernNode))
        assert kerns, "u-template kern must be inside the cell box"


# ---------------------------------------------------------------------------
# \tabskip glue between vertical-alignment columns (AC #4)
# ---------------------------------------------------------------------------

class TestValignTabskip:
    def test_tabskip_glue_around_columns(self) -> None:
        # default tabskip 0: before col0, between col0/col1, after col1.
        hlist = _valign_result(r"#\cr a\cr b\cr")
        for col in _column_vboxes(hlist):
            assert len([n for n in col.list if isinstance(n, GlueNode)]) == 2

    def test_tabskip_value_is_live(self) -> None:
        hlist = _valign_result(r"#\cr a\cr b\cr", preamble=r"\tabskip=5pt")
        for col in _column_vboxes(hlist):
            glues = [n.glue.width for n in col.list if isinstance(n, GlueNode)]
            assert glues == [327680, 327680]


# ---------------------------------------------------------------------------
# \omit / \span surface in vertical mode + FR-11 \multispan
# ---------------------------------------------------------------------------

class TestValignOmitSpan:
    def test_omit_suppresses_template(self) -> None:
        from aspose_tex._engine.nodes import KernNode

        # \kern1pt#: the template adds a kern; \omit suppresses it for that cell.
        hlist = _valign_result(r"\kern1pt#\cr \omit a\cr b\cr")
        omitted = _stacked_cells(_column_vboxes(hlist)[0])[0]
        kerns = list(_descendants(omitted, KernNode))
        assert kerns == []

    def test_span_merges_cells_vertically(self) -> None:
        # \span fuses two cells of one column into one taller vbox.
        hlist = _valign_result(r"#&#\cr a\span b\cr")
        col = _column_vboxes(hlist)[0]
        cells = _stacked_cells(col)
        assert len(cells) == 1
        assert _chars_in(cells[0]) == {"a", "b"}

    def test_span_records_span_count(self) -> None:
        from aspose_tex._engine import alignment

        captured: list = []
        original = alignment._measure_columns

        def _spy(state):
            captured.append(state)
            return original(state)

        alignment._measure_columns = _spy
        try:
            TeXInterpreter().run_with_device(
                StringInputSource(
                    _FONT_PREAMBLE + r"\valign{#&#\cr a\span b\cr}\bye"
                ),
                DviDevice(),
            )
        finally:
            alignment._measure_columns = original
        assert captured
        spans = [
            cell.span_count
            for row in captured[0].rows
            if isinstance(row, list)
            for cell in row
        ]
        assert 2 in spans

    def test_multispan_via_plain_tex_macro(self) -> None:
        # FR-11: \multispan is the REAL plain.tex macro expanding to
        # \omit\span\omit…\omit. It works end-to-end once \omit/\span execute —
        # no new primitive. Drive it through the bundled plain format and spy on
        # the algorithm state to confirm the spanned cell merged.
        from aspose_tex._engine import alignment
        from aspose_tex.presentation import TeXJob, TeXOptions

        captured: list = []
        original = alignment._measure_columns

        def _spy(state):
            captured.append(state)
            return original(state)

        alignment._measure_columns = _spy
        try:
            TeXJob(
                StringInputSource(r"\valign{#&#&#\cr \multispan2 a&b\cr}\end"),
                DviDevice(),
                options=TeXOptions(load_format="plain"),
            ).run()
        finally:
            alignment._measure_columns = original

        assert captured, "\\multispan valign did not reach _measure_columns"
        vertical_states = [s for s in captured if s.vertical]
        assert vertical_states, "no \\valign state captured"
        spans = [
            cell.span_count
            for row in vertical_states[-1].rows
            if isinstance(row, list)
            for cell in row
        ]
        # \multispan2 expands to \omit\span\omit → the first cell spans 2 columns.
        assert 2 in spans


# ---------------------------------------------------------------------------
# Ragged columns + recursive \valign (Q6)
# ---------------------------------------------------------------------------

class TestValignRaggedRecursive:
    def test_ragged_columns_fewer_cells(self) -> None:
        hlist = _valign_result(r"#&#&#\cr a\cr b&c\cr")
        cols = _column_vboxes(hlist)
        assert len(cols) == 2
        assert len(_stacked_cells(cols[0])) == 1
        assert len(_stacked_cells(cols[1])) == 2

    def test_recursive_valign_in_cell(self) -> None:
        # A nested \valign inside a cell builds its own hlist and is added as a
        # box node within the enclosing cell (which is a vbox wrapping the
        # cell's horizontal strip).
        hlist = _valign_result(r"#\cr \valign{#\cr p\cr}\cr q\cr")
        first_cell = _stacked_cells(_column_vboxes(hlist)[0])[0]
        nested = list(_descendants(first_cell, HlistNode))
        # The nested \valign yields an hlist; q's cell carries one.
        assert nested, "nested \\valign hlist must appear inside the cell"
        assert _chars_in(first_cell) == {"p"}

    def test_halign_inside_valign_cell(self) -> None:
        # Mixed nesting: an \halign vlist inside a \valign cell.
        hlist = _valign_result(r"#\cr \halign{#\cr p\cr}\cr q\cr")
        first_cell = _stacked_cells(_column_vboxes(hlist)[0])[0]
        assert "p" in _chars_in(first_cell), "nested \\halign rows must be spliced into the cell"
        assert _chars_in(first_cell) == {"p"}
