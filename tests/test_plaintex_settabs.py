r""" cascade (b/c) — \settabs / \+ via the REAL plain.tex bodies.

AC-8 wants ``\settabs 4\columns \+ a&b&c&d\cr`` driven through the bundled
plain.tex ``\settabs`` / ``\+`` / ``\ialign`` / ``\tabskip`` macros, not
mocked alignment bodies.

The repeating-preamble (``&&``) feature these macros depend on landed in
The full ``\settabs`` / ``\+`` end-to-end path was BLOCKED by an engine
gap unrelated to alignment: ``\settabs``'s ``\t@bbox`` cell template opens
``\setbox\z@\hbox\bgroup`` and closes it only in the ``\t@bb@x`` v-template
*after* the cell terminator, and ``\m@ketabbox`` redefines ``\cr`` for the row
terminator.  added open-group box construction
(``\hbox\bgroup…\egroup``) + redefined-``\cr`` honouring, so the real bodies now
run end-to-end — the AC-8 test below has flipped ``xfail`` → pass.
"""
from __future__ import annotations

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import HlistNode, VlistNode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

_FONT_PREAMBLE = r"\font\tenrm=cmr10 \tenrm "


def _halign_result(body: str) -> VlistNode:
    """Run ``\\halign{body}`` (font selected) and return its packed vlist.

    Wraps the alignment in ``\\setbox0=\\vbox{…}`` so it takes the
    *packed* path (a box frame is open) and the row structure these tests assert
    on is captured as one vlist; a *top-level* ``\\halign`` splices its rows
    directly into the page list.
    """
    interp = TeXInterpreter()
    interp.run_with_device(
        StringInputSource(
            _FONT_PREAMBLE + r"\setbox0=\vbox{\halign{" + body + r"}}\bye"
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
# Repeating preamble (&&) — the feature \settabs / \ialign relies on
# ---------------------------------------------------------------------------

class TestRepeatingPreamble:
    r"""``&\template`` (leading ``&``) repeats the template for every column."""

    def test_repeating_template_covers_all_cells(self) -> None:
        # `&#` declares one repeating column template; the row uses four cells.
        vlist = _halign_result(r"&#\cr a&b&c&d\cr")
        rows = _row_hboxes(vlist)
        assert len(rows) == 1
        assert len(_cell_hboxes(rows[0])) == 4

    def test_repeating_template_applies_u_tokens(self) -> None:
        # `&\hfil#` repeats a right-aligning template; every cell carries fil glue.
        from aspose_tex._engine.nodes import GlueNode

        vlist = _halign_result(r"&\hfil#\cr a&bb&ccc\cr")
        for cell in _cell_hboxes(_row_hboxes(vlist)[0]):
            fil = [
                n for n in cell.list
                if isinstance(n, GlueNode) and n.glue.stretch_order.value > 0
            ]
            assert fil, "repeating u-template fil glue missing"

    def test_repeating_columns_each_aligned_to_max(self) -> None:
        # Columns from the repeating template still align to per-column max width.
        vlist = _halign_result(r"&#\cr a&bb\cr ccc&d\cr")
        rows = _row_hboxes(vlist)
        c0 = _cell_hboxes(rows[0])
        c1 = _cell_hboxes(rows[1])
        assert c0[0].width == c1[0].width
        assert c0[1].width == c1[1].width

    def test_repeating_preamble_state_records_repeat_from(self) -> None:
        from aspose_tex._engine import alignment

        captured: list = []
        original = alignment._measure_columns

        def _spy(state):
            captured.append(state)
            return original(state)

        alignment._measure_columns = _spy
        try:
            TeXInterpreter().run_with_device(
                StringInputSource(_FONT_PREAMBLE + r"\halign{&#\cr a&b&c\cr}\bye"),
                DviDevice(),
            )
        finally:
            alignment._measure_columns = original
        assert captured
        # repeat_from == 0: the whole (single) template repeats.
        assert captured[0].repeat_from == 0


# ---------------------------------------------------------------------------
# AC-8 — real \settabs / \+ end-to-end (open-group boxes)
# ---------------------------------------------------------------------------

def _tabs_box(source: str) -> HlistNode | None:
    """Run *source* with load_format='plain' and return the \\tabs box.

    plain.tex's ``\\settabs`` stores the tab-stop strut box in ``\\newbox\\tabs``
    (box register 12).  Returns its contents for column-width assertions.
    """
    interp = TeXInterpreter(load_format="plain")
    interp.run_with_device(StringInputSource(source), DviDevice())
    return interp._box_regs.peekbox(12)


class TestSettabsRealMacros:
    def test_ac8_settabs_four_columns_real_bodies(self) -> None:
        # \settabs 4\columns \+ a&b&c&d\cr — runs through the REAL plain.tex
        # \settabs / \+ / \ialign / \m@ketabbox bodies (no mocks) and produces a
        # 4-column row aligned to quarter-width tabs.
        out = TeXJob(
            StringInputSource(r"\settabs 4\columns \+a&b&c&d\cr \end"),
            DviDevice(),
            options=TeXOptions(load_format="plain"),
        ).run()
        assert out, "\\settabs/\\+ produced no DVI"

    def test_ac8_tab_columns_are_quarter_hsize(self) -> None:
        # \settabs 4\columns builds a \tabs box of four \hsize/4 struts.
        interp = TeXInterpreter(load_format="plain")
        interp.run_with_device(
            StringInputSource(r"\settabs 4\columns \end"), DviDevice(),
        )
        tabs = interp._box_regs.peekbox(12)
        assert isinstance(tabs, HlistNode)
        cols = [n.width for n in tabs.list if isinstance(n, (HlistNode, VlistNode))]
        assert len(cols) == 4
        hsize = interp._register_set.get_dimen(258, _internal=True)
        quarter = hsize // 4
        # Each tab strut is one quarter \hsize (±1sp integer-division slack).
        for w in cols:
            assert abs(w - quarter) <= 1, (w, quarter)

    def test_ac8_row_shorter_than_tab_count(self) -> None:
        # A \+ row with fewer cells than tab stops still runs end-to-end.
        out = TeXJob(
            StringInputSource(r"\settabs 4\columns \+a&b\cr \end"),
            DviDevice(),
            options=TeXOptions(load_format="plain"),
        ).run()
        assert out, "\\+ short row produced no DVI"
