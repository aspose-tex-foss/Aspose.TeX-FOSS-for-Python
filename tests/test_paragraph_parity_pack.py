r""" regressions; expectations measured with MiKTeX 24.4, 2026-10-21."""
import json
import warnings
from pathlib import Path

import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _tfm_width


def run(source):
    messages = []
    interp = TeXInterpreter(load_format='plain', messages=messages)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        device = DviDevice()
        interp.run_with_device(StringInputSource(source + '\n\\bye\n'), device)
        result = device.get_bytes()
    return interp, messages, result


@pytest.mark.parametrize(('body', 'first', 'excess', 'last'), [
    (r'aaaa\thinspace\ bbbbbbbbbbbb cccccccc', 'aaaa', '21.66687', 'bbbbbbbbbbbb|'),
    (r'a\kern3pt\ bbbbbbbbb', 'a', '20.00015', 'bbbbbbbbb |'),
])
def test_explicit_kern_break(body, first, excess, last):
    width = 45 if first == 'aaaa' else 30
    _, messages, _ = run(fr'\hsize={width}pt\hbadness=-1\tolerance=10000\noindent {body}\par')
    reports = [m for m in messages if 'in paragraph at' in m or m.startswith('\\tenrm')]
    assert reports == [
        'Underfull \\hbox (badness 10000) in paragraph at lines 1--1', '\\tenrm ' + first,
        f'Overfull \\hbox ({excess}pt too wide) in paragraph at lines 1--1', '\\tenrm ' + last,
    ]


@pytest.mark.parametrize('unbox', ['unhcopy', 'unhbox'])
def test_unboxed_ligatures_hyphenate(unbox, monkeypatch):
    import aspose_tex._engine.interpreter as module
    lines = []
    real = module.exec_par
    def capture(*args, **kwargs):
        result = real(*args, **kwargs)
        lines.extend(result)
        return result
    monkeypatch.setattr(module, 'exec_par', capture)
    run(r'\hsize=0.9in\parindent=0pt\setbox0\hbox{x difficulties offices affluent difficulties}'
        + '\\noindent\\' + unbox + r'0\par')
    def text(line):
        return ''.join(''.join(map(chr, n.source or (n.char,))) if isinstance(n, CharNode)
                       else ' ' if hasattr(n, 'glue') and n.glue.width else '' for n in line.list).strip()
    assert [text(line) for line in lines] == ['x difficulties of-', 'fices affluent dif-', 'ficulties']


def test_font_integers_global_and_readable():
    _, messages, _ = run(r'{\hyphenchar\tenrm=1\skewchar\tenrm=2}'
                        r'\message{[\the\hyphenchar\tenrm/\the\skewchar\tenrm]}'
                        r'\count0=-\hyphenchar\font\edef\value{\the\skewchar\font}'
                        r'\message{[\the\count0/\value]}')
    assert '[1/2]' in messages
    assert '[-1/2]' in messages


def test_implicit_font_kern_survives_discretionary_line_start():
    _, _, payload = run(r'\nopagenumbers\parindent=0pt\hsize=90pt'
                        r'\hyphenchar\tenrm=`A\exhyphenpenalty=-10000 AV AV\par')
    glyphs = walk_chars_with_positions(payload, _tfm_width())[0]
    assert [h for c, h, v in glyphs if c == ord('V')] == [-72819, -72819]


@pytest.mark.parametrize('skip', [r'\leftskip=0pt minus1fil', r'\rightskip=0pt minus1fil', ''])
def test_infinite_paragraph_shrink_becomes_finite(skip):
    interior = r'\hskip0pt minus1fil ' if not skip else ''
    _, messages, _ = run(r'\hsize=60pt' + skip + r'\noindent Supercalifragilisticexpialidocious '
                        + interior + r'word\par')
    assert messages.count('! Infinite glue shrinkage found in a paragraph.') == 1
    excess = '80.83368' if skip else '81.83368'
    assert f'Overfull \\hbox ({excess}pt too wide) in paragraph at lines 1--1' in messages


def test_side_skip_finite_replacement_survives_paragraph():
    _, messages, _ = run(r'\rightskip=0pt minus1fil\noindent a\par'
                        r'\message{[RS=\the\rightskip]}')
    assert '[RS=0.0pt minus 1.0pt]' in messages


def test_math_off_break_keeps_closing_dollar():
    _, messages, _ = run(r'\hsize=40pt\hbadness=-1\tolerance=10000'
                        r'\noindent a $x$ bbbbbbbbbbbbbbbbbbbbbbb\par')
    assert r'\tenrm a $\teni x$' in messages


def test_setlanguage_inserts_tail_before_scanning(monkeypatch):
    from tests.test_language_whatsits import _paragraphs
    paragraphs, _, _ = _paragraphs(r'\noindent a\penalty7\setlanguage\lastpenalty b\par', monkeypatch)
    assert paragraphs == ['a <L0 2,3> b']


def test_terminal_leaders_removed_before_display():
    _, messages, payload = run(r'\nopagenumbers\parindent20pt'
        r'\everydisplay{\message{[PRE=\the\predisplaysize]}}'
        r'\noindent\leaders\hbox{x}\hskip8pt$$y$$ x\par')
    assert '[PRE=-16383.99998pt]' in messages
    assert walk_chars_with_positions(payload, _tfm_width()) == [
        [(121, 15220520, 1441792), (120, 0, 2686976)]]


def test_nonterminal_leaders_unchanged():
    _, _, payload = run(r'\nopagenumbers\noindent\leaders\hbox{x}\hskip8pt y\par')
    assert [c for c, _, _ in walk_chars_with_positions(payload, _tfm_width())[0]] == [120, 121]


_REFERENCE = json.loads((Path(__file__).parents[1] / 'testdata/reference/paragraph_parity/reference.json').read_text())


@pytest.mark.parametrize('name', _REFERENCE)
def test_context_glyph_oracle(name):
    case = _REFERENCE[name]
    _, _, payload = run(case['source'].replace(r'\showbox0', ''))
    glyphs = walk_chars_with_positions(payload, _tfm_width()) if payload else []
    assert json.loads(json.dumps(glyphs)) == case['glyphs']


_REWORK_REFERENCE = json.loads(
    (Path(__file__).parents[1] / 'testdata/reference/paragraph_parity/extended_reference.json').read_text())


@pytest.mark.parametrize('name', _REWORK_REFERENCE)
def test_leaders_boundary_oracle(name):
    """Review return: leaders are glue at break and discard boundaries."""
    case = _REWORK_REFERENCE[name]
    _, messages, payload = run(case['source'])
    glyphs = walk_chars_with_positions(payload, _tfm_width()) if payload else []
    assert json.loads(json.dumps(glyphs)) == case['glyphs']
    if name == 'kern_leaders':
        assert r'\tenrm a' in messages
        assert 'Overfull \\hbox (20.00015pt too wide) in paragraph at lines 1--1' in messages
    if name == 'math_leaders':
        assert r'\tenrm a $\teni x$' in messages


_DISC = r'\nopagenumbers\hsize=30pt\hbadness=-1\tolerance=10000\noindent \hyphenpenalty=-10000 '


@pytest.mark.parametrize(('body', 'glyphs', 'reports'), [
    # repro (a reference probe post_kern): the
    # nonempty post-break kern keeps the leaders from the discard sweep.
    (_DISC + r'a\discretionary{-}{\kern2pt}{}\leaders\hbox{.}\hskip8pt b\par',
     [[97, 0, 655360], [45, 327681, 655360], [46, 182045, 1441792], [46, 364090, 1441792], [98, 655360, 1441792]],
     ['Underfull \\hbox (badness 10000) in paragraph at lines 1--1', '\\tenrm a-']),
    (_DISC + r'a\discretionary{\kern2pt-}{}{}\leaders\hbox{.}\hskip8pt b\par',
     [[97, 0, 655360], [45, 458753, 655360], [98, 0, 1441792]],
     ['Underfull \\hbox (badness 10000) in paragraph at lines 1--1', '\\tenrm a-']),
    (r'\nopagenumbers\hsize=100pt\noindent a\discretionary{-}{}{\kern5pt}b\par',
     [[97, 0, 655360], [98, 655361, 655360]], []),
])
def test_explicit_kern_in_discretionary_branches(body, glyphs, reports):
    """Expected glyphs and line reports: MiKTeX 24.4 plain, 2026-10-29."""
    _, messages, payload = run(body)
    assert [list(g) for g in walk_chars_with_positions(payload, _tfm_width())[0]] == glyphs
    assert [m for m in messages if 'in paragraph at' in m or m.startswith('\\tenrm')] == reports
