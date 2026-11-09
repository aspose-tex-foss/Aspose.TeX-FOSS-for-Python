"""MiKTeX 24.4 measured context regressions."""

import pytest

from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _run, _tfm_width

CASES = [
    ("adjust_empty", "\\noindent o \\vadjust{} o", [[111, 0, 655360], [111, 764587, 655360]], []),
    (
        "adjust_kern",
        "\\noindent a\\vadjust{\\kern5pt}b\\par c",
        [[97, 0, 655360], [98, 327681, 655360], [99, 1310720, 1769472]],
        [],
    ),
    (
        "adjust_box",
        "\\noindent a\\vadjust{\\hbox{X}}b\\par c",
        [[97, 0, 655360], [98, 327681, 655360], [88, 0, 1103188], [99, 1310720, 1889620]],
        [],
    ),
    (
        "adjust_hbox",
        "\\noindent\\hbox{a\\vadjust{\\kern5pt}b}\\par c",
        [[97, 0, 655360], [98, 327681, 655360], [99, 1310720, 1441792]],
        [],
    ),
    (
        "adjust_vbox",
        "\\vbox{\\noindent a\\vadjust{\\hbox{X}}b\\par c}",
        [[97, 0, 455111], [98, 327681, 455111], [88, 0, 902939], [99, 1310720, 1689371]],
        [],
    ),
    (
        "adjust_math",
        "\\noindent$a\\vadjust{\\kern5pt}b$\\par c",
        [[97, 0, 655360], [98, 346416, 655360], [99, 1310720, 1769472]],
        [],
    ),
    (
        "adjust_edef",
        "\\edef\\x{\\vadjust{\\kern5pt}}\\message{[defined]}\\noindent a\\x b\\par c",
        [[97, 0, 655360], [98, 327681, 655360], [99, 1310720, 1769472]],
        ["[defined]"],
    ),
    (
        "adjust_multi",
        "\\noindent a\\vadjust{\\kern2pt}\\vadjust{\\hbox{X}}b\\par c",
        [[97, 0, 655360], [98, 327681, 655360], [88, 0, 1234260], [99, 1310720, 2020692]],
        [],
    ),
    (
        "adjust_wrap",
        "\\hsize=50pt\\noindent one\\vadjust{\\hbox{X}} two three four five six seven eight\\par y",
        [
            [111, 0, 655360],
            [110, 327681, 655360],
            [101, 691771, 655360],
            [116, 1128677, 655360],
            [119, 1365335, 655360],
            [111, 1820446, 655360],
            [116, 2293762, 655360],
            [104, 2548625, 655360],
            [114, 2912715, 655360],
            [101, 3169398, 655360],
            [101, 3460669, 655360],
            [88, 0, 1103188],
            [102, 0, 1889620],
            [111, 200250, 1889620],
            [117, 527931, 1889620],
            [114, 892021, 1889620],
            [12, 1328014, 1889620],
            [118, 1692104, 1889620],
            [101, 2019785, 1889620],
            [115, 2490366, 1889620],
            [105, 2748869, 1889620],
            [120, 2930914, 1889620],
            [115, 0, 2676052],
            [101, 258503, 2676052],
            [118, 549774, 2676052],
            [101, 877455, 2676052],
            [110, 1168726, 2676052],
            [101, 1751269, 2676052],
            [105, 2042540, 2676052],
            [103, 2224585, 2676052],
            [104, 2552266, 2676052],
            [116, 2898151, 2676052],
            [121, 1310720, 3462484],
        ],
        [],
    ),
    (
        "adjust_display",
        "\\noindent a$$x\\vadjust{\\hbox{X}}+y$$b",
        [
            [97, 0, 655360],
            [120, 14632747, 1441792],
            [43, 15152935, 1441792],
            [121, 15808293, 1441792],
            [88, 0, 2017051],
            [98, 0, 3134804],
        ],
        [],
    ),
    (
        "adjust_halign",
        "\\halign{#\\cr a\\vadjust{\\hbox{X}}b\\cr c\\cr}",
        [[97, 0, 655360], [98, 327681, 655360], [88, 0, 1103188], [99, 0, 1889620]],
        [],
    ),
    ("adjust_only", "\\noindent\\vadjust{\\kern5pt}\\par c", [[99, 1310720, 1769472]], []),
    (
        "adjust_math_empty",
        "\\noindent$a+\\vadjust{}b$\\par c",
        [[97, 0, 655360], [43, 492048, 655360], [98, 1147406, 655360], [99, 1310720, 1441792]],
        [],
    ),
]


@pytest.mark.parametrize("name,body,expected,messages", CASES, ids=[x[0] for x in CASES])
def test_miktex_positions(name, body, expected, messages):
    job = _run(body)
    pages = walk_chars_with_positions(job._dvi, _tfm_width()) if job._dvi else []
    actual = pages[0][:-1] if pages else []
    assert len(actual) == len(expected)
    for (c, h, v), (ec, eh, ev) in zip(actual, expected, strict=True):
        assert c == ec
        assert abs(h - eh) <= (1 if name == "adjust_display" else 0)
        assert v == ev
    assert [m for m in job.messages if m.startswith("[")] == messages
