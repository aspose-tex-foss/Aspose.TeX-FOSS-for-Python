""" measured branch selection and stored-box output ownership."""
import json
import warnings
from dataclasses import replace
from pathlib import Path

import pytest

from aspose_tex import DviDevice, PdfDevice, StringInputSource, SvgDevice, TeXJob
from aspose_tex._engine.linebreak import break_paragraph
from aspose_tex._engine.nodes import (
    CharNode,
    DiscretionaryNode,
    GlueNode,
    HlistNode,
    KernNode,
    PenaltyNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._output.pdf_writer import PdfWriter
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_linebreak_math_and_hyphen import _params, _run
from tests.test_plain_tie import _tfm_width

ROOT = Path(__file__).parents[1]
REFERENCE = json.loads((ROOT / 'testdata/reference/discretionary_line_material/results.json').read_text())


@pytest.mark.parametrize('name', REFERENCE)
def test_measured_context(name):
    case = REFERENCE[name]
    job = TeXJob(StringInputSource(case['source'].replace(r'\showbox0', '')), DviDevice())
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        payload = job.run()
    actual = walk_chars_with_positions(payload, _tfm_width())
    expected = case['ref']['glyphs']
    # The reference holds only these \message lines (probe.py's regex), not line reports.
    assert ([m for m in job.messages if m.startswith(('[saved=', '[literal='))]
            == case['ref']['messages'])
    assert len(actual) == len(expected)
    for page, reference in zip(actual, expected, strict=True):
        assert len(page) == len(reference)
        for (code, h, v), (rc, rh, rv) in zip(page, reference, strict=True):
            assert code == rc and h == rh and v == rv


@pytest.mark.parametrize('device', [DviDevice, PdfDevice, SvgDevice])
@pytest.mark.parametrize(('alternative', 'ordinary'), [
    (r'a\discretionary{P}{Q}{N}b', 'aNb'),
    (r'a\discretionary{\hbox{\bf P}}{\hbox{\it Q}}{N}b', 'aNb'),
    (r'a\discretionary{P}{Q}{\hbox{NN}}b', r'a\hbox{NN}b'),
    (r'a\discretionary{P}{Q}{\hbox{\bf N}}b', r'a\hbox{\bf N}b'),
    (r'a\discretionary{P}{Q}{\hbox{\kern-2pt N\kern3pt}}b', r'a\hbox{\kern-2pt N\kern3pt}b'),
])
def test_stored_and_copied_outputs_equal_materialized_nobreak(device, alternative, ordinary, monkeypatch):
    monkeypatch.setattr(PdfWriter, '_now_pdf_date', staticmethod(lambda: b'D:20261019000000Z'))
    def render(body):
        source = r'\nopagenumbers\setbox0\hbox{' + body + r'}\copy0\box0\bye'
        return TeXJob(StringInputSource(source), device()).run()
    assert render(alternative) == render(ordinary)


def test_stored_alternatives_remain_available_after_copy_and_unhbox():
    from aspose_tex._engine.nodes import iter_nobreak_nodes
    interp = _run(r'\setbox0\hbox{a\discretionary{P}{Q}{N}b}\setbox1\copy0')
    original = interp._box_regs.getbox(0).list
    copied = interp._box_regs.getbox(1).list
    assert original == copied
    assert any(isinstance(n, DiscretionaryNode) for n in original)
    assert ''.join(chr(n.char) for n in iter_nobreak_nodes(original) if hasattr(n, 'char')) == 'aNb'


def test_nonempty_post_protects_signed_discardables():
    from aspose_tex._engine.linebreak import _line_start, _line_starts
    kern = KernNode(-65536, explicit=True)
    glue = GlueNode(Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
    for post, start in [((), 4), ((kern,), 1)]:
        nodes = [DiscretionaryNode((), post, ()), glue, kern, PenaltyNode(50),
                 DiscretionaryNode((), (), ())]
        assert _line_start(nodes, 0, _line_starts(nodes)) == (start, post)


def test_signed_branch_nodes_and_break_flags_match_measured_boxed_alternatives():
    interp = _run('')
    def char(code):
        return CharNode(ord(code), 'tenrm')
    disc = DiscretionaryNode(
        (KernNode(-2 * 65536, True), char('P'), KernNode(3 * 65536, True)),
        (KernNode(4 * 65536, True), char('Q'), KernNode(-65536, True)),
        (KernNode(-3 * 65536, True), char('N')),
    )
    params = replace(_params(), hsize=100 * 65536, hyphenpenalty=-10000)
    nodes = [char('a'), disc, char('b'), PenaltyNode(10000),
             GlueNode(params.parfillskip), PenaltyNode(-10000)]
    flags = []
    lines = break_paragraph(nodes, params, interp._font_manager, disc_breaks=flags)
    assert flags == [True, False]
    assert [''.join(chr(n.char) for n in line.list if isinstance(n, CharNode))
            for line in lines] == ['aP', 'Qb']
    assert [n.width for n in lines[0].list if isinstance(n, KernNode)] == [-131072, 196608]
    assert [n.width for n in lines[1].list if isinstance(n, KernNode)] == [262144, -65536]
    assert all(line.width == params.hsize for line in lines)


def test_brokenpenalty_one_per_selected_disc_line():
    interp = _run(r'\setbox0\vbox{\hyphenpenalty=-10000\brokenpenalty=123'
                  r'\interlinepenalty=0\clubpenalty=0\widowpenalty=0'
                  r'\noindent a\discretionary{P}{Q}{N}b\discretionary{R}{S}{T}c\par}')
    nodes = interp._box_regs.getbox(0).list
    assert sum(isinstance(n, HlistNode) for n in nodes) == 3
    assert [n.penalty for n in nodes if isinstance(n, PenaltyNode)] == [123, 123]
