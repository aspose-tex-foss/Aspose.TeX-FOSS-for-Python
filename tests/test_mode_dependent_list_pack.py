r""" list commands; glyph coordinates measured with MiKTeX 24.4."""
from __future__ import annotations

import pytest

from aspose_tex._engine.interpreter import ModeKind
from aspose_tex._engine.nodes import GlueNode, HlistNode, KernNode, PenaltyNode, RuleNode
from aspose_tex._engine.page_builder import PageBuilder
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex.exceptions import EngineError
from tests.test_page_builder import _default_config, _make_hbox, _NullBackend
from tests.test_paragraph_start_pack import _page1
from tests.test_plain_tie import _messages
from tests.test_vbox_interline import _run


def _glue(width):
    return Glue(width, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)


@pytest.mark.parametrize(('body', 'miktex'), [
    (r'\setbox1\vbox{\hbox{a}}x\par y\par\unvbox1 z',
     [(120,1310720,655360),(121,1310720,1441792),(97,0,1851391),(122,1310720,2510392)]),
    (r'\setbox1\vbox{\hbox{a}}x\par y\unvbox1 z',
     [(120,1310720,655360),(121,1310720,1441792),(97,0,1851391),(122,1310720,2510392)]),
    (r'\setbox1\vbox{\hbox{a}}\unvbox1 z', [(97,0,655360),(122,1310720,937528)]),
    (r'\edef\a{\unvbox1}\setbox1\vbox{\hbox{a}}\a z',
     [(97,0,655360),(122,1310720,937528)]),
    (r'\setbox1\vbox{\hbox{a}}\vbox{\hbox{y}\unvbox1\hbox{z}}',
     [(121,0,282168),(97,0,691767),(122,0,1350768)]),
    (r'\setbox1\vbox{\hbox{a}}\vbox\bgroup\hbox{y}\unvbox1\hbox{z}\egroup',
     [(121,0,282168),(97,0,691767),(122,0,1350768)]),
])
def test_unpackage_measured_positions(body, miktex):
    assert _page1(body) == miktex


@pytest.mark.parametrize('tail', [[], [_make_hbox(30, 40)], [RuleNode(100,30,4)],
                                [GlueNode(_glue(9))], [KernNode(8, True)], [PenaltyNode(100)]])
def test_splice_preserves_logical_depth_and_raw_nodes(tail):
    pb = PageBuilder(_default_config(), _NullBackend())
    pb.contribute(_make_hbox(20, 7))
    pb.build_page()
    before = len(pb._mvl)
    pb.contribute_spliced(tail)
    assert pb._prev_depth == 7
    assert list(pb._contrib) == tail  # §1110: \unvbox calls no build_page
    pb.contribute(_make_hbox(10, 3))
    pb.build_page()
    assert pb._mvl[before:before + len(tail)] == tail
    if tail and isinstance(tail[0], RuleNode):
        # §1002: the rule moves like a box; the next interline
        # glue folds its depth into the total.
        assert pb._page_depth == 3
    assert isinstance(pb._mvl[-2], GlueNode)
    assert pb._mvl[-2].glue.width == 786432 - 7 - 10


def test_splice_page_top_discardables_topskip_and_physical_depth():
    pb = PageBuilder(_default_config(max_depth=5), _NullBackend())
    box = _make_hbox(30, 9)
    pb.contribute_spliced([GlueNode(_glue(90)), KernNode(8, True), PenaltyNode(100), box])
    pb.build_page()
    assert pb._mvl == [GlueNode(_glue(655330)), box]
    assert pb._prev_depth == -65536000
    assert pb._page_total == 655364
    assert pb._page_depth == 5


@pytest.mark.parametrize('mode', [ModeKind.RESTRICTED_HORIZONTAL, ModeKind.MATH, ModeKind.MATH_DISPLAY])
def test_unpackage_wrong_mode_does_not_consume(mode):
    interp = _run(r'\setbox1\vbox{\hbox{a}}\bye')
    source = interp._box_regs.peekbox(1)
    interp._mode_stack.push(mode)
    with pytest.raises(EngineError, match='outside vertical'):
        interp._exec_unvbox_cmd(copy=False)
    assert interp._box_regs.peekbox(1) is source


@pytest.mark.parametrize(('body', 'miktex'), [
    (r'\everypar{A}x\indent y',
     [(65,1310720,655360),(120,1802241,655360),(121,3458847,655360)]),
    (r'\hbox{x\indent y}', [(120,0,655360),(121,1656606,655360)]),
    (r'\vbox{\noindent x\indent y}', [(120,0,655360),(121,1656606,655360)]),
    (r'\hbox\bgroup x\indent y\egroup', [(120,0,655360),(121,1656606,655360)]),
    (r'$x\indent y$', [(120,1310720,655360),(121,2995996,655360)]),
    (r'$$x\indent y$$', [(120,14377882,1441792),(121,16063158,1441792)]),
    (r'\halign{#\cr x\indent y\cr}', [(120,0,655360),(121,1656606,655360)]),
    (r'\edef\a{\indent}\noindent x\a y', [(120,0,655360),(121,1656606,655360)]),
])
def test_indent_measured_positions(body, miktex):
    assert _page1(body) == miktex


@pytest.mark.parametrize('width', [-3, 0, 7])
@pytest.mark.parametrize('opening,closing', [(r'\hbox{','}'), (r'\hbox\bgroup',r'\egroup')])
def test_indent_live_scoped_null_box(width, opening, closing):
    interp = _run(r'\let\bgroup={\let\egroup=}\parindent=20pt\setbox0' + opening +
                  rf'\parindent={width}pt\indent' + closing + r'\bye')
    box = interp._box_regs.peekbox(0)
    assert len(box.list) == 1
    null = box.list[0]
    assert isinstance(null, HlistNode)
    assert (null.width, null.height, null.depth, null.list) == (width*65536, 0, 0, [])
    assert interp._get_named_dimen('parindent') == 20*65536


def test_indent_everypar_once_spacefactor_and_noindent():
    assert _messages(r'\everypar{\message{[ep]}}x.\indent\message{[sf=\the\spacefactor]}y') == ['[ep]', '[sf=1000]']
    assert _page1(r'\hbox{x\noindent y}') == _page1(r'\hbox{xy}')


@pytest.mark.parametrize('payload,preceding', [(r'\hrule','g'), (r'\hbox{a}','y')])
def test_unpack_receiving_depth_messages_measured(payload, preceding):
    body = (r'\setbox0\vbox{' + payload + r'}\vbox{\hbox{' + preceding +
            r'}\message{[before=\the\prevdepth]}\unvbox0\message{[after=\the\prevdepth]}\hbox{z}}')
    assert _messages(body) == ['[before=1.94444pt]', '[after=1.94444pt]']


def test_unpack_pagebreak_inside_splice_measured():
    from aspose_tex import DviDevice, StringInputSource, TeXJob, TeXOptions
    from tests._verification.dvi_walker import walk_chars_with_positions
    from tests.test_plain_tie import _tfm_width
    body = r'\vsize=24pt\setbox0\vbox{\hbox{A}\penalty-10000\hbox{B}}\hbox{X}\unvbox0\hbox{Z}\bye'
    data = TeXJob(StringInputSource(body), DviDevice(), options=TeXOptions()).run()
    assert walk_chars_with_positions(data, _tfm_width()) == [
        [(88,0,655360),(65,0,1103188),(49,15229091,3145728)],
        [(66,0,655360),(90,0,1441792),(50,15229091,3145728)],
    ]


@pytest.mark.parametrize('copy', [False,True])
def test_unpack_copy_consumption(copy):
    command = r'\unvcopy' if copy else r'\unvbox'
    interp = _run(r'\setbox0\vbox{\hbox{}}' + command + r'0\bye')
    assert (interp._box_regs.peekbox(0) is not None) == copy


@pytest.mark.parametrize('body', [r'\setbox0\hbox{}\unvbox0',
                                r'\leaders\hbox{}\hskip1pt',
                                r'\hbox{\leaders\hbox{}\vskip1pt}',
                                r'\vbox{\leaders\hbox{}\hskip1pt}',
                                r'\leaders\copy99\vskip1pt'])
def test_list_commands_invalid_operands(body):
    with pytest.raises(EngineError):
        _run(body+r'\bye')


@pytest.mark.parametrize('body', [
    r'\vbox{\leaders\hbox{A}\vskip5pt\message{[last=\the\lastskip]}\unskip\message{[last=\the\lastskip]}\hbox{Z}}',
    r'\hbox{\leaders\hbox{A}\hskip5pt\message{[last=\the\lastskip]}\unskip\message{[last=\the\lastskip]}Z}',
])
def test_leader_lastskip_unskip_measured(body):
    assert _messages(body) == ['[last=5.0pt]', '[last=0.0pt]']



def test_unpack_multiple_output_cycles_receiving_depth_measured():
    from aspose_tex import DviDevice, StringInputSource, TeXJob, TeXOptions
    from tests._verification.dvi_walker import walk_chars_with_positions
    from tests.test_plain_tie import _tfm_width
    body = r"\vsize=24pt\setbox0\vbox{\hbox{A}\penalty-10000\hbox{B}\penalty-10000\hbox{C}}\hbox{g}\unvbox0\hbox{Z}\bye"
    data = TeXJob(StringInputSource(body), DviDevice(), options=TeXOptions()).run()
    assert walk_chars_with_positions(data, _tfm_width()) == [
        [(103,0,655360),(65,0,1230619),(49,15229091,3145728)],
        [(66,0,655360),(50,15229091,3145728)],
        [(67,0,655360),(90,0,1314361),(51,15229091,3145728)],
    ]
