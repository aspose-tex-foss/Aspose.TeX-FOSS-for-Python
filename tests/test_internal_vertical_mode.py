"""internal vertical lists; MiKTeX 24.4 measured expectations."""

import pytest

from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _run, _tfm_width

CASES = [
    ("indent", "\\vbox{\\hsize=100pt x\\par y}", [[120, 1310720, 282168], [121, 1310720, 1068600]], []),
    ("tie", "\\vbox{\\noindent o~o}", [[111, 0, 655360], [111, 546134, 655360]], []),
    (
        "wrap",
        "\\vbox{\\hsize=50pt\\noindent one two three four five six seven eight nine ten}",
        [
            [111, 0, 455111],
            [110, 327681, 455111],
            [101, 691771, 455111],
            [116, 1128677, 455111],
            [119, 1365335, 455111],
            [111, 1820446, 455111],
            [116, 2293762, 455111],
            [104, 2548625, 455111],
            [114, 2912715, 455111],
            [101, 3169398, 455111],
            [101, 3460669, 455111],
            [102, 0, 1241543],
            [111, 200250, 1241543],
            [117, 527931, 1241543],
            [114, 892021, 1241543],
            [12, 1328014, 1241543],
            [118, 1692104, 1241543],
            [101, 2019785, 1241543],
            [115, 2490366, 1241543],
            [105, 2748869, 1241543],
            [120, 2930914, 1241543],
            [115, 0, 2027975],
            [101, 258503, 2027975],
            [118, 549774, 2027975],
            [101, 877455, 2027975],
            [110, 1168726, 2027975],
            [101, 1875055, 2027975],
            [105, 2166326, 2027975],
            [103, 2348371, 2027975],
            [104, 2676052, 2027975],
            [116, 3021937, 2027975],
            [110, 0, 2814407],
            [105, 364090, 2814407],
            [110, 546135, 2814407],
            [101, 910225, 2814407],
            [116, 1419949, 2814407],
            [101, 1674812, 2814407],
            [110, 1966083, 2814407],
        ],
        [],
    ),
    ("parskip", "\\parskip=5pt\\vbox{\\hsize=100pt x\\par y}", [[120, 1310720, 282168], [121, 1310720, 1396280]], []),
    (
        "everypar",
        "\\everypar{A}\\vbox{\\hsize=50pt x\\par y}",
        [[65, 1310720, 447828], [120, 1802241, 447828], [65, 1310720, 1234260], [121, 1802241, 1234260]],
        [],
    ),
    ("leavevmode", "\\setbox2\\vbox{\\leavevmode y}\\box2", [[121, 1310720, 655360]], []),
    (
        "prevgraf",
        "x\\par\\setbox2\\vbox{\\message{[in=\\the\\prevgraf]}y\\par\\message{[in2=\\the\\prevgraf]}}\\message{[out=\\the\\prevgraf]}",
        [[120, 1310720, 655360]],
        ["[in=0]", "[in2=1]", "[out=1]"],
    ),
    ("setbox", "\\vbox{\\noindent o\\setbox0\\hbox{}o}", [[111, 0, 655360], [111, 327681, 655360]], []),
    (
        "group",
        "\\vbox{\\noindent a\\begingroup b\\endgroup c}",
        [[97, 0, 655360], [98, 327681, 655360], [99, 691771, 655360]],
        [],
    ),
    ("wd", "\\vbox{\\noindent o\\wd0=0pt o}", [[111, 0, 655360], [111, 327681, 655360]], []),
    ("ht", "\\vbox{\\noindent o\\ht0=0pt o}", [[111, 0, 655360], [111, 327681, 655360]], []),
    ("dp", "\\vbox{\\noindent o\\dp0=0pt o}", [[111, 0, 655360], [111, 327681, 655360]], []),
    (
        "deferred",
        "\\vbox{\\noindent x\\setbox0\\hbox\\bgroup y\\egroup\\box0}",
        [[120, 0, 655360], [121, 345886, 655360]],
        [],
    ),
    (
        "deferred_vtop",
        "\\vbox{\\noindent x.\\setbox0\\vtop\\bgroup\\noindent y\\egroup{} o}",
        [[120, 0, 655360], [46, 345886, 655360], [111, 819202, 655360]],
        [],
    ),
    (
        "frame_implicit",
        "\\vbox\\bgroup\\hsize=100pt x\\par y\\egroup",
        [[120, 1310720, 282168], [121, 1310720, 1068600]],
        [],
    ),
    (
        "lig",
        "\\vbox{\\noindent f{}i f\\chardef\\ii=105 \\ii\\noboundary f\\ii}",
        [[102, 0, 655360], [105, 200250, 655360], [102, 600748, 655360], [105, 800998, 655360], [12, 983043, 655360]],
        [],
    ),
    (
        "footnote",
        "x\\footnote*{f~g\\par h}\\par y",
        [
            [120, 1310720, 655360],
            [42, 1656606, 655360],
            [121, 1310720, 1441792],
            [42, 655359, 41366491],
            [102, 1310720, 41366491],
            [103, 1729423, 41366491],
            [104, 1310720, 42152923],
        ],
        [],
    ),
    (
        "math_vcenter",
        "\\noindent$\\vcenter{\\hsize=100pt\\noindent o~o}$",
        [[111, 0, 632604], [111, 546134, 632604]],
        [],
    ),
    (
        "hbox_vbox",
        "\\noindent\\hbox{x\\vbox{\\hsize=100pt\\noindent o~o}y}",
        [[120, 0, 655360], [111, 345886, 655360], [111, 892020, 655360], [121, 6899486, 655360]],
        [],
    ),
    ("output", "\\output{\\shipout\\vbox{\\noindent A\\box255}}\\noindent x\\par", [[65, 0, 42152922]], []),
    (
        "local_assignment",
        "\\count0=7"
        "\\vbox{\\noindent a\\begingroup\\count0=8\\message{[\\the\\count0]}\\endgroup"
        "\\message{[\\the\\count0]}b}\\message{[\\the\\count0]}",
        [[97, 0, 655360], [98, 327681, 655360]],
        ["[8]", "[7]", "[7]"],
    ),
    (
        "aftergroup",
        "\\vbox{\\noindent a\\begingroup\\aftergroup b\\endgroup c}",
        [[97, 0, 655360], [98, 327681, 655360], [99, 709976, 655360]],
        [],
    ),
    (
        "afterassignment",
        "\\vbox{\\noindent a\\afterassignment b\\setbox0\\hbox{X}c}",
        [[97, 0, 655360], [99, 327681, 655360]],
        [],
    ),
    (
        "local_hsize",
        "\\vbox{\\hsize=50pt\\noindent one two three four five six seven eight}",
        [
            [111, 0, 455111],
            [110, 327681, 455111],
            [101, 691771, 455111],
            [116, 1128677, 455111],
            [119, 1365335, 455111],
            [111, 1820446, 455111],
            [116, 2293762, 455111],
            [104, 2548625, 455111],
            [114, 2912715, 455111],
            [101, 3169398, 455111],
            [101, 3460669, 455111],
            [102, 0, 1241543],
            [111, 200250, 1241543],
            [117, 527931, 1241543],
            [114, 892021, 1241543],
            [12, 1328014, 1241543],
            [118, 1692104, 1241543],
            [101, 2019785, 1241543],
            [115, 2490366, 1241543],
            [105, 2748869, 1241543],
            [120, 2930914, 1241543],
            [115, 0, 2027975],
            [101, 258503, 2027975],
            [118, 549774, 2027975],
            [101, 877455, 2027975],
            [110, 1168726, 2027975],
            [101, 1751269, 2027975],
            [105, 2042540, 2027975],
            [103, 2224585, 2027975],
            [104, 2552266, 2027975],
            [116, 2898151, 2027975],
        ],
        [],
    ),
    (
        "nested_math",
        "\\noindent$\\left(\\vcenter{\\hsize=100pt\\noindent a $x+y$ b}\\right)$",
        [
            [40, 0, 655360],
            [97, 254863, 655360],
            [120, 800997, 655360],
            [43, 1321185, 655360],
            [121, 1976543, 655360],
            [98, 2539820, 655360],
            [41, 6808463, 655360],
        ],
        [],
    ),
]


@pytest.mark.parametrize("name,body,expected,messages", CASES, ids=[x[0] for x in CASES])
def test_internal_vertical_miktex(name, body, expected, messages):
    job = _run(body)
    actual = walk_chars_with_positions(job._dvi, _tfm_width())[0][:-1]
    assert len(actual) == len(expected)
    for (c, h, v), (ec, eh, ev) in zip(actual, expected, strict=True):
        assert (c, h) == (ec, eh)
        assert abs(v - ev) <= (2 if name == "footnote" else 0)
    assert [m for m in job.messages if m.startswith("[")] == messages
