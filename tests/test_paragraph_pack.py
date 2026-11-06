r""": paragraph/list-tail pins measured with MiKTeX 24.4 tex."""
import pytest

from aspose_tex._engine.nodes import CharNode, DiscretionaryNode
from tests.test_box_vocab import _run_capture
from tests.test_interword_space_after_box import _glyph_h
from tests.test_plain_tie import _messages


@pytest.mark.parametrize("body,expected", [
    (r"\noindent o \ignorespaces o", [(111, 0), (111, 546134)]),
    (r"\def\sp{ }\noindent o \ignorespaces\sp\sp o", [(111, 0), (111, 546134)]),
    (r"\noindent o \- o", [(111, 0), (111, 764587)]),
    (r"\noindent\hbox{o \- o}", [(111, 0), (111, 764587)]),
    (r"\noindent\vbox{\noindent o \- o\par}", [(111, 0), (111, 764587)]),
])
def test_ignorespaces_and_discretionary_hyphen(body, expected):
    assert _glyph_h(body) == expected


@pytest.mark.parametrize("code", [45, 127, -1, 256])
def test_discretionary_uses_current_hyphenchar(code):
    interp = _run_capture(r"\hyphenchar\tenrm=" + str(code) + r" \noindent o\-o\par\bye")
    discs = [n for p in interp.captured_paragraphs for n in p if isinstance(n, DiscretionaryNode)]
    assert len(discs) == 1
    expected = (CharNode(char=code, font_name=interp._font_manager.font_id("tenrm")),) if 0 <= code <= 255 else ()
    assert discs[0].pre == expected
    assert discs[0].post == discs[0].nobreak == ()


@pytest.mark.parametrize("body,expected", [
    (r"\noindent x.\hbox{o} o", [(120, 0), (46, 345886), (111, 527931), (111, 1074065)]),
    (r"\noindent x.$x$ o", [(120, 0), (46, 345886), (120, 527931), (111, 1120940)]),
    (r"\noindent x.$\relax$ o", [(120, 0), (46, 345886), (111, 746384)]),
    (r"\noindent\spaceskip=7pt x.\hbox{o} o", [(120, 0), (46, 345886), (111, 527931), (111, 1314364)]),
    (r"\noindent\xspaceskip=9pt x.\hbox{o} o", [(120, 0), (46, 345886), (111, 527931), (111, 1074065)]),
    (r"\noindent\spaceskip=7pt x.\ o", [(120, 0), (46, 345886), (111, 986683)]),
    (r"\noindent\xspaceskip=9pt x. o", [(120, 0), (46, 345886), (111, 1117755)]),
    (r"\noindent\spaceskip=7pt x. o", [(120, 0), (46, 345886), (111, 1059501)]),
])
def test_spacefactor_and_supplied_glue(body, expected):
    assert _glyph_h(body) == expected


@pytest.mark.parametrize("body,expected", [
    (r"\noindent o \char`o o", [(111, 0), (111, 546134), (111, 892020)]),
    (r"\noindent\char`o o", [(111, 0), (111, 345886)]),
    (r"\noindent o\char`o o", [(111, 0), (111, 345886), (111, 691772)]),
    (r"\noindent f\char`i", [(12, 0)]),
    (r"\noindent\char`f i", [(12, 0)]),
    (r"\noindent\hbox{f\char`i}", [(12, 0)]),
])
def test_char_participates_in_ligature_and_kern(body, expected):
    assert _glyph_h(body) == expected


READ = '\\message{[\\the\\lastskip/\\the\\lastkern/\\the\\lastpenalty]}'

@pytest.mark.parametrize("body,expected", [
    (
        '\\spaceskip=0pt plus1pt\\noindent o ' + READ,
        ['[0.0pt plus 1.0pt/0.0pt/0]'],
    ),
    (
        '\\spaceskip=0pt minus1pt\\noindent o ' + READ,
        ['[0.0pt minus 1.0pt/0.0pt/0]'],
    ),
    (
        '\\spaceskip=0pt plus1fil\\noindent o ' + READ,
        ['[0.0pt plus 1.0fil/0.0pt/0]'],
    ),
    (
        '\\spaceskip=0pt plus1pt minus2pt\\noindent x.\\ ' + READ,
        ['[0.0pt plus 1.0pt minus 2.0pt/0.0pt/0]'],
    ),
    (
        '\\xspaceskip=0pt plus1pt\\noindent x. ' + READ,
        ['[0.0pt plus 1.0pt/0.0pt/0]'],
    ),
    (
        '\\xspaceskip=0pt minus1pt\\noindent x. ' + READ,
        ['[0.0pt minus 1.0pt/0.0pt/0]'],
    ),
    (
        '\\xspaceskip=0pt plus1pt\\noindent x.\\ ' + READ,
        ['[3.33333pt plus 1.66666pt minus 1.11111pt/0.0pt/0]'],
    ),
    (
        '\\spaceskip=0pt plus1pt\\noindent x.\\hbox{o} ' + READ,
        ['[0.0pt plus 1.0pt/0.0pt/0]'],
    ),
    (
        '\\xspaceskip=0pt plus1pt\\noindent x.\\hbox{o} ' + READ,
        ['[3.33333pt plus 1.66666pt minus 1.11111pt/0.0pt/0]'],
    ),
    (
        '\\spaceskip=0pt plus1pt minus2pt\\noindent x. ' + READ,
        ['[1.11111pt plus 3.0pt minus 0.66666pt/0.0pt/0]'],
    ),
    (
        '\\spaceskip=0pt plus1fill\\noindent o ' + READ,
        ['[0.0pt plus 1.0fill/0.0pt/0]'],
    ),
    (
        '\\spaceskip=0pt plus0fil\\noindent o ' + READ,
        ['[3.33333pt plus 1.66666pt minus 1.11111pt/0.0pt/0]'],
    ),
    (
        '\\xspaceskip=0pt plus0fil\\noindent x. ' + READ,
        ['[4.44444pt plus 4.99997pt minus 0.37036pt/0.0pt/0]'],
    ),
    (
        '\\spaceskip=0pt plus1pt\\noindent x.$x$ ' + READ,
        ['[0.0pt plus 1.0pt/0.0pt/0]'],
    ),
])
def test_zero_width_supplied_space_glue(body, expected):
    assert _messages(body) == expected
