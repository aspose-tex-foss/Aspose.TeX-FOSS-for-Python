r""": page-state ownership pinned to MiKTeX 24.4 ``tex``.

Each row is one line of the context probe: the plain-TeX source, the
``\message`` output and every glyph ``(code, h, v)`` per page as MiKTeX sets
them (``tex`` + ``dvi_walker``). All positions match exactly after.
"""
from __future__ import annotations

import warnings

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _tfm_width

_CASES = [
    pytest.param(  # A/B/C/D \pagefilstretch
        (
            '\\vskip0pt plus1fil\\message{[A\\the\\pagefilstretch]}\\hbox{}\\vskip0pt plus1fil\\mess'
            'age{[B\\the\\pagefilstretch]}\\hbox{}\\message{[C\\the\\pagefilstretch]}\\penalty0\\mess'
            'age{[D\\the\\pagefilstretch]}\\bye'
        ),
        ['[A0.0pt]', '[B0.0pt]', '[C1.0pt]', '[D1.0pt]'],
        [
            [
                (49, 15229091, 43725786),
            ],
        ],
        id='page_fil',
    ),
    pytest.param(  # finite total/stretch/shrink
        (
            '\\vskip3pt plus2pt minus1pt\\message{[A\\the\\pagetotal/\\the\\pagestretch/\\the\\pagesh'
            'rink]}\\hbox{}\\vskip3pt plus2pt minus1pt\\message{[B\\the\\pagetotal/\\the\\pagestretc'
            'h/\\the\\pageshrink]}\\hbox{}\\message{[C\\the\\pagetotal/\\the\\pagestretch/\\the\\pagesh'
            'rink]}\\bye'
        ),
        ['[A0.0pt/0.0pt/0.0pt]', '[B10.0pt/0.0pt/0.0pt]', '[C25.0pt/2.0pt/1.0pt]'],
        [
            [
                (49, 15229091, 43725786),
            ],
        ],
        id='page_finite',
    ),
    pytest.param(  # fill stretch moves on the penalty trigger
        (
            '\\hbox{}\\vskip0pt plus1fill\\message{[A\\the\\pagefillstretch]}\\penalty0\\message{[B\\'
            'the\\pagefillstretch]}\\bye'
        ),
        ['[A0.0pt]', '[B1.0pt]'],
        [
            [
                (49, 15229091, 43725786),
            ],
        ],
        id='page_fill',
    ),
    pytest.param(  # filll stretch moves on the box trigger
        (
            '\\hbox{}\\vskip0pt plus1filll\\message{[A\\the\\pagefilllstretch]}\\hbox{}\\message{[B\\'
            'the\\pagefilllstretch]}\\bye'
        ),
        ['[A0.0pt]', '[B1.0pt]'],
        [
            [
                (49, 15229091, 43725786),
            ],
        ],
        id='page_filll',
    ),
    pytest.param(  # leading \vskip discarded at the page top
        (
            '\\vskip20pt\\noindent o\\bye'
        ),
        [],
        [
            [
                (111, 0, 655360), (49, 15229091, 43725786),
            ],
        ],
        id='page_visible',
    ),
    pytest.param(  # rule-first page
        (
            '\\vskip20pt\\hrule\\message{[A\\the\\pagetotal]}\\hbox{o}\\bye'
        ),
        ['[A0.0pt]'],
        [
            [
                (111, 0, 937528), (49, 15229091, 43725786),
            ],
        ],
        id='page_rule',
    ),
    pytest.param(  # last depth before \vfil
        (
            'x\\par\\vfil y\\par\\vfil\\eject z\\bye'
        ),
        [],
        [
            [
                (120, 1310720, 655360), (121, 1310720, 21733642), (49, 15229091, 43725786),
            ],
            [
                (122, 1310720, 655360), (50, 15229091, 43725786),
            ],
        ],
        id='tex332_vfil',
    ),
    pytest.param(  # \parskip fil
        (
            '\\parskip=0pt plus 1fil x\\par y\\par\\vskip 0pt plus 1fil\\eject z\\bye'
        ),
        [],
        [
            [
                (120, 1310720, 655360), (121, 1310720, 21733642), (49, 15229091, 43725786),
            ],
            [
                (122, 1310720, 655360), (50, 15229091, 43725786),
            ],
        ],
        id='tex332_parskip',
    ),
    pytest.param(  # \parskip 5pt plus 1fil
        (
            '\\parskip=5pt plus 1fil x\\par y\\vfil\\eject z\\bye'
        ),
        [],
        [
            [
                (120, 1310720, 655360), (121, 1310720, 21897482), (49, 15229091, 43725786),
            ],
            [
                (122, 1310720, 655360), (50, 15229091, 43725786),
            ],
        ],
        id='tex332_parskip5',
    ),
    pytest.param(  # \box255 packed to the insertion-adjusted goal
        (
            '\\output{\\message{[\\number\\ht\\footins,\\number\\dp\\footins,\\number\\ht255,\\number\\dp'
            '255]}\\plainoutput}\\noindent x\\insert\\footins{\\hbox{\\strut a}\\kern2pt} y\\bye'
        ),
        ['[917504,0,40448986,0]'],
        [
            [
                (120, 0, 655360), (121, 564339, 655360), (97, 0, 41792475),
                (49, 15229091, 43725786),
            ],
        ],
        id='tex373_ins',
    ),
    pytest.param(  # \pageinsert floats to the next page
        (
            'x\\par\\pageinsert a\\endinsert y\\par z\\bye'
        ),
        [],
        [
            [
                (120, 1310720, 655360), (121, 1310720, 1441792), (122, 1310720, 2228224),
                (49, 15229091, 43725786),
            ],
            [
                (97, 1310720, 282168), (50, 15229091, 43725786),
            ],
        ],
        id='tex379_pageinsert',
    ),
    pytest.param(  # \eject on a box-less page ships nothing
        (
            '\\vsize=2in a\\par\\eject\\eject b\\par\\vfill\\eject\\eject c\\bye'
        ),
        [],
        [
            [
                (97, 1310720, 655360), (49, 15229091, 11045437),
            ],
            [
                (98, 1310720, 655360), (50, 15229091, 11045437),
            ],
            [
                (99, 1310720, 655360), (51, 15229091, 11045437),
            ],
        ],
        id='tex397_eject',
    ),
    pytest.param(  # \lastskip reads the last moved glue
        (
            '\\hbox{a}\\vskip 5pt\\par\\message{[\\the\\lastskip]}\\bye'
        ),
        ['[5.0pt]'],
        [
            [
                (97, 0, 655360), (49, 15229091, 43725786),
            ],
        ],
        id='ctx_lastskip_par',
    ),
    pytest.param(  # \unskip cannot remove glue from the page
        (
            '\\hbox{a}\\vskip5pt\\par\\unskip\\hbox{b}\\bye'
        ),
        [],
        [
            [
                (97, 0, 655360), (98, 0, 1769472), (49, 15229091, 43725786),
            ],
        ],
        id='ctx_unskip_par',
    ),
    pytest.param(  # \unskip removes glue still on the contribution list
        (
            '\\hbox{a}\\vskip5pt\\unskip\\hbox{b}\\bye'
        ),
        [],
        [
            [
                (97, 0, 655360), (98, 0, 1441792), (49, 15229091, 43725786),
            ],
        ],
        id='ctx_unskip_contrib',
    ),
    pytest.param(  # \pagegoal is \maxdimen on an empty page
        (
            '\\message{[\\the\\pagegoal]}\\hbox{}\\message{[\\the\\pagegoal]}\\bye'
        ),
        ['[16383.99998pt]', '[643.20255pt]'],
        [
            [
                (49, 15229091, 43725786),
            ],
        ],
        id='ctx_pagegoal',
    ),
    pytest.param(  # \output material goes before the leftover
        (
            '\\vsize=20pt \\output={\\shipout\\box255 \\global\\output={\\shipout\\box255}\\hbox{O}}\\h'
            'box{a}\\hbox{b}\\hbox{c}\\bye'
        ),
        [],
        [
            [
                (97, 0, 655360),
            ],
            [
                (79, 0, 655360),
            ],
            [
                (98, 0, 655360),
            ],
            [
                (99, 0, 655360),
            ],
        ],
        id='ctx_output_order',
    ),
    pytest.param(  # \parskip reaches the page when the paragraph starts
        (
            '\\hbox{}\\parskip=7pt \\noindent\\message{[\\the\\pagetotal]}x\\bye'
        ),
        ['[17.0pt]'],
        [
            [
                (120, 0, 1900544), (49, 15229091, 43725786),
            ],
        ],
        id='ctx_parskip_total',
    ),
    pytest.param(  # \prevdepth does not change \pagedepth
        (
            '\\hbox{a}\\prevdepth=20pt\\message{[\\the\\pagedepth]}\\bye'
        ),
        ['[0.0pt]'],
        [
            [
                (97, 0, 655360), (49, 15229091, 43725786),
            ],
        ],
        id='ctx_prevdepth',
    ),
    pytest.param(  # insertion in a paragraph follows its line
        (
            '\\noindent x\\insert100{\\hbox{I}} y\\par\\message{[\\the\\pagegoal]}\\bye'
        ),
        ['[643.20255pt]'],
        [
            [
                (120, 0, 655360), (121, 564339, 655360), (49, 15229091, 43725786),
            ],
        ],
        id='ctx_insert_order',
    ),
    pytest.param(  # \lastpenalty reads the last moved penalty
        (
            '\\hbox{a}\\penalty7 \\message{[\\the\\lastpenalty]}\\bye'
        ),
        ['[7]'],
        [
            [
                (97, 0, 655360), (49, 15229091, 43725786),
            ],
        ],
        id='ctx_lastpenalty_page',
    ),
    pytest.param(  # \insert in a paragraph keeps the space factor
        (
            '\\noindent a.\\insert100{\\hbox{b}}\\message{[\\the\\spacefactor]} c\\bye'
        ),
        ['[3000]'],
        [
            [
                (97, 0, 655360), (46, 327681, 655360), (99, 800997, 655360),
                (49, 15229091, 43725786),
            ],
        ],
        id='ctx_ins_sf',
    ),
    pytest.param(  # a mark-only page never fires
        (
            '\\mark{A}\\eject\\message{[\\topmark]}\\bye'
        ),
        ['[]'],
        [
            [
                (49, 15229091, 43725786),
            ],
        ],
        id='ctx_topmark_empty',
    ),
    pytest.param(  # \insertpenalties counts held-over insertions in \output
        (
            '\\output{\\message{[\\the\\insertpenalties]}\\plainoutput}x\\par\\pageinsert a\\endinser'
            't y\\par z\\bye'
        ),
        ['[1]', '[0]'],
        [
            [
                (120, 1310720, 655360), (121, 1310720, 1441792), (122, 1310720, 2228224),
                (49, 15229091, 43725786),
            ],
            [
                (97, 1310720, 282168), (50, 15229091, 43725786),
            ],
        ],
        id='ctx_inspen',
    ),
]


@pytest.mark.parametrize(("source", "messages", "pages"), _CASES)
def test_page_state_matches_miktex(source: str, messages: list, pages: list) -> None:
    job = TeXJob(StringInputSource(source), DviDevice())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = job.run()
    assert [m for m in job.messages if m.startswith("[")] == messages
    ours = walk_chars_with_positions(dvi, _tfm_width())
    assert [len(page) for page in ours] == [len(page) for page in pages]
    for got_page, want_page in zip(ours, pages, strict=True):
        for (code, h, v), (want_code, want_h, want_v) in zip(got_page, want_page, strict=True):
            assert (code, v) == (want_code, want_v)
            assert h == want_h
