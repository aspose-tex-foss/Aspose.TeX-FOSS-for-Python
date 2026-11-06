r""": line/box packing regressions measured with MiKTeX 24.4."""
import warnings

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob
from aspose_tex._engine.box_primitives import OverfullBoxWarning, UnderfullBoxWarning
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_linebreak import TestParagraphBreaksMatchMiktex
from tests.test_plain_tie import _glyph_h, _messages, _run, _tfm_width


@pytest.mark.parametrize('tail', [
    r'\hskip3pt o', r'\ o', r'~o', r'\penalty10000\ o',
    r'\kern3pt\penalty0\hskip2pt o',
])
def test_forced_break_discards_leading_material(tail):
    assert _glyph_h(r'\noindent o\hfil\break' + tail) == [(111, 0), (111, 0)]


def test_post_break_box_stops_discarding():
    assert _glyph_h(r'\noindent o\hfil\break\hbox{}\hskip3pt o') == [(111, 0), (111, 196608)]


def test_restricted_hbox_keeps_break_and_glue():
    assert _glyph_h(r'\noindent\hbox{o\hfil\break\hskip3pt o}') == [(111, 0), (111, 524289)]


@pytest.mark.parametrize('width,expected', [
    (110, ['Thequickbrownfoxjumps', 'overthelazydogwhilethe',
           '\x0cveboxingwizardsjump', "quicklyandawizard'sjob", 'istovexchumpsquickly',
           'infog.Packmyboxwith', '\x0cvedozenliquorjugs,then',
           'sphinxofblackquartzjudge', 'myvow.']),
    (130, ['Thequickbrownfoxjumpsover', 'thelazydogwhilethe\x0cveboxing',
           "wizardsjumpquicklyandawizard's", 'jobistovexchumpsquickly',
           'infog.Packmyboxwith\x0cve', 'dozenliquorjugs,thensphinx',
           'ofblackquartzjudgemyvow.']),
    (170, ['Thequickbrownfoxjumpsoverthe', 'lazydogwhilethe\x0cveboxingwizards',
           "jumpquicklyandawizard'sjobisto", 'vexchumpsquicklyinfog.Packmy',
           'boxwith\x0cvedozenliquorjugs,then', 'sphinxofblackquartzjudgemyvow.']),
])
def test_final_pass_keeps_the_remaining_break_chain(width, expected):
    body = rf'\hsize={width}pt\hyphenpenalty=10000\noindent ' + TestParagraphBreaksMatchMiktex._TEXT
    job = _run(body)
    lines = {}
    for c, _h, v in walk_chars_with_positions(job._dvi, _tfm_width())[0][:-1]:
        lines.setdefault(v, []).append(chr(c))
    assert [''.join(chars) for chars in lines.values()] == expected


@pytest.mark.parametrize('box,expected', [
    (r'\hbox{\raise3pt\hbox{a}}', '[7.30554pt/0.0pt/5.00002pt]'),
    (r'\hbox{\lower1pt\hbox{a}}', '[3.30554pt/1.0pt/5.00002pt]'),
    (r'\hbox{\raise3pt\vbox{\hbox{a}}}', '[7.30554pt/0.0pt/5.00002pt]'),
    (r'\vbox{\moveright3pt\hbox{a}}', '[4.30554pt/0.0pt/8.00002pt]'),
    (r'\vbox{\moveleft3pt\hbox{a}}', '[4.30554pt/0.0pt/2.00002pt]'),
])
def test_shifted_box_dimensions(box, expected):
    body = (r'\setbox0=' + box + r'\dimen0=\ht0\dimen1=\dp0\dimen2=\wd0'
            r'\message{[\the\dimen0/\the\dimen1/\the\dimen2]}')
    assert _messages(body) == [expected]


def _diagnostics(body):
    job = TeXJob(StringInputSource(body + r'\bye'), DviDevice())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        job.run()
    return [str(w.message).split()[0] for w in caught
            if issubclass(w.category, (OverfullBoxWarning, UnderfullBoxWarning))]


@pytest.mark.parametrize('body,expected', [
    (r'\setbox0=\hbox to12pt{\hskip10pt plus1pt}', []),
    (r'\hbadness=800\setbox0=\hbox to12pt{\hskip10pt plus1pt}', []),
    (r'\hbadness=799\setbox0=\hbox to12pt{\hskip10pt plus1pt}', ['Underfull']),
    (r'\hbadness=0\setbox0=\hbox to10.5pt{\hskip10pt plus1pt}', ['Loose']),
    (r'\vbadness=0\setbox0=\vbox to10.5pt{\vskip10pt plus1pt}', ['Loose']),
    (r'\hbadness=99\setbox0=\hbox to9pt{\hskip10pt minus1pt}', ['Tight']),
    (r'\vbadness=99\setbox0=\vbox to9pt{\vskip10pt minus1pt}', ['Tight']),
    (r'\setbox0=\hbox to9.95pt{\hskip10pt}', []),
    (r'\setbox0=\vbox to9.95pt{\vskip10pt}', []),
    (r'\hfuzz=1sp\setbox0=\hbox to8sp{\hskip10sp minus1sp}', []),
    (r'\hfuzz=0sp\setbox0=\hbox to8sp{\hskip10sp minus1sp}', ['Overfull']),
    (r'\vfuzz=1sp\setbox0=\vbox to8sp{\vskip10sp minus1sp}', []),
    (r'\vfuzz=0sp\setbox0=\vbox to8sp{\vskip10sp minus1sp}', ['Overfull']),
    (r'\hbadness=99\hfuzz=1pt\setbox0=\hbox to9.95pt{\hskip10pt}', ['Overfull']),
    (r'\hbadness=-1\setbox0=\hbox to0pt{\hskip10pt minus1fil}', []),
    (r'\hbadness=-1\setbox0=\hbox to10pt{\hskip10pt}', []),
    (r'\hbadness=-1\setbox0=\hbox to10pt{}', []),
    (r'{\hbadness=0\setbox0=\hbox to12pt{\hskip10pt plus1pt}}'
     r'\setbox0=\hbox to12pt{\hskip10pt plus1pt}', ['Underfull']),
    (r'\setbox0=\hbox to12pt{\hbadness=0\hskip10pt plus1pt}', []),
    (r'\hsize=1pt\noindent oo', ['Overfull']),
    (r'\hfuzz=10pt\hsize=1pt\noindent oo', []),
])
def test_box_diagnostics_follow_live_thresholds(body, expected):
    assert _diagnostics(body) == expected


def test_suppressed_warning_does_not_suppress_badness():
    assert _messages(r'\setbox0=\hbox to12pt{\hskip10pt plus1pt}\message{[\the\badness]}') == ['[800]']


@pytest.mark.parametrize('middle', [r'\break', r'\penalty-10000', r'\break\penalty0\hskip2pt'])
def test_consecutive_forced_breaks_keep_the_empty_line(middle):
    body = r'\hsize=25pt\noindent aa\hfil\break' + middle + r'\kern4pt bb\hfil\break cc'
    job = _run(body)
    glyphs = walk_chars_with_positions(job._dvi, _tfm_width())[0][:-1]
    assert [(h, v) for c, h, v in glyphs if c == ord('b')] == [(0, 2228224), (364090, 2228224)]
    assert [(h, v) for c, h, v in glyphs if c == ord('c')] == [(0, 3014656), (291271, 3014656)]
    assert _diagnostics(body) == ['Underfull']
