""": MiKTeX 24.4 measured context regressions."""

import pytest

from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _run, _tfm_width

CASES = [
    (
        "valign",
        "\\noindent\\valign{#&#\\cr\\hbox{a}\\vskip5pt\\hbox{b}&\\hbox{c}\\vfil\\cr}",
        [[97, 0, 282168], [98, 0, 1396280], [99, 0, 1678448]],
        [],
    ),
    (
        "valign_text",
        "\\noindent\\valign{\\hsize=50pt#&\\hsize=50pt#\\cr one two three four\\par&\\noindent a\\par b\\cr}",
        [
            [111, 1310720, 403098],
            [110, 1638401, 403098],
            [101, 2002491, 403098],
            [116, 2439397, 403098],
            [119, 2676055, 403098],
            [111, 3131166, 403098],
            [116, 0, 1189530],
            [104, 254863, 1189530],
            [114, 618953, 1189530],
            [101, 875636, 1189530],
            [101, 1166907, 1189530],
            [102, 1676631, 1189530],
            [111, 1876881, 1189530],
            [117, 2204562, 1189530],
            [114, 2568652, 1189530],
            [97, 0, 1471698],
            [98, 1310720, 2258130],
        ],
        # MiKTeX's paragraph-line report (§8, re-measured 2026-10-21 for).
        ["[]\\tenrm one two|"],
    ),
    (
        "valign_tabskip",
        "\\tabskip=5pt\\noindent\\valign{#&#\\cr\\hbox{a}&\\hbox{b}\\cr\\hbox{c}&\\hbox{d}\\cr}",
        [[97, 0, 609848], [98, 0, 1392639], [99, 364090, 609848], [100, 364090, 1392639]],
        [],
    ),
    (
        "valign_span",
        "\\noindent\\valign{\\hsize=100pt#&#\\cr\\noindent a\\span b\\cr}",
        [[97, 0, 282168], [98, 1310720, 1068600]],
        [],
    ),
    (
        "valign_span_scope",
        "\\noindent\\valign{#&#\\cr\\def\\z{X}\\hbox{a}\\span\\hbox{\\z}\\cr}\\message{[\\meaning\\z]}",
        [[97, 0, 282168], [88, 0, 1068600]],
        ["[undefined]"],
    ),
    (
        "valign_to",
        "\\noindent\\valign to50pt{#\\vfil&#\\cr\\hbox{a}&\\hbox{b}\\cr}",
        [[97, 0, 282168], [98, 0, 737279]],
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
