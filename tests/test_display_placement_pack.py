r"""MiKTeX 24.4 plain measurements, glyph positions in sp.

Vertical assertions intentionally leave the separately owned horizontal
leqalignno placement to its full-coordinate tests; covers fil centring.
"""

from __future__ import annotations

import pytest

from tests.test_paragraph_start_pack import _page1
from tests.test_plain_tie import _messages


@pytest.mark.parametrize(
    ("body", "miktex"),
    [
        ("x\\par$$\\hbox to 6.4in{y\\hfil}$$ x", [(120, 655360), (121, 3014656), (120, 4587520)]),
        ("x\\par$$y$$ x", [(120, 655360), (121, 2228224), (120, 3473408)]),
        ("x\\par$$\\halign{#\\cr a\\cr}$$ x", [(120, 655360), (97, 3014656), (120, 4587520)]),
        ("x\\par$$\\displaylines{a\\cr b\\cr}$$ x", [(120, 655360), (97, 3014656), (98, 3997696), (120, 5570560)]),
        (
            "x\\par$$\\eqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 3014656),
                (61, 3014656),
                (98, 3014656),
                (99, 3997696),
                (61, 3997696),
                (100, 3997696),
                (40, 3997696),
                (49, 3997696),
                (41, 3997696),
                (120, 5570560),
            ],
        ),
        (
            "x\\par$$\\leqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 3014656),
                (61, 3014656),
                (98, 3014656),
                (99, 3997696),
                (61, 3997696),
                (100, 3997696),
                (40, 3997696),
                (49, 3997696),
                (41, 3997696),
                (120, 5570560),
            ],
        ),
        (
            "x\\par$$\\eqalign{a&=b\\cr c&=d\\cr}$$ x",
            [
                (120, 655360),
                (97, 2064384),
                (61, 2064384),
                (98, 2064384),
                (99, 3047424),
                (61, 3047424),
                (100, 3047424),
                (120, 4083256),
            ],
        ),
        ("x\\par\\indent$$\\hbox to 6.4in{y\\hfil}$$ x", [(120, 655360), (121, 3014656), (120, 4587520)]),
        ("x\\par\\indent$$y$$ x", [(120, 655360), (121, 2228224), (120, 3473408)]),
        ("x\\par\\indent$$\\halign{#\\cr a\\cr}$$ x", [(120, 655360), (97, 3014656), (120, 4587520)]),
        (
            "x\\par\\indent$$\\displaylines{a\\cr b\\cr}$$ x",
            [(120, 655360), (97, 3014656), (98, 3997696), (120, 5570560)],
        ),
        (
            "x\\par\\indent$$\\eqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 3014656),
                (61, 3014656),
                (98, 3014656),
                (99, 3997696),
                (61, 3997696),
                (100, 3997696),
                (40, 3997696),
                (49, 3997696),
                (41, 3997696),
                (120, 5570560),
            ],
        ),
        (
            "x\\par\\indent$$\\leqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 3014656),
                (61, 3014656),
                (98, 3014656),
                (99, 3997696),
                (61, 3997696),
                (100, 3997696),
                (40, 3997696),
                (49, 3997696),
                (41, 3997696),
                (120, 5570560),
            ],
        ),
        (
            "x\\par\\indent$$\\eqalign{a&=b\\cr c&=d\\cr}$$ x",
            [
                (120, 655360),
                (97, 2064384),
                (61, 2064384),
                (98, 2064384),
                (99, 3047424),
                (61, 3047424),
                (100, 3047424),
                (120, 4083256),
            ],
        ),
        ("x\\par\\noindent$$\\hbox to 6.4in{y\\hfil}$$ x", [(120, 655360), (121, 1441792), (120, 2686976)]),
        ("x\\par\\noindent$$y$$ x", [(120, 655360), (121, 1441792), (120, 2686976)]),
        ("x\\par\\noindent$$\\halign{#\\cr a\\cr}$$ x", [(120, 655360), (97, 2228224), (120, 3801088)]),
        (
            "x\\par\\noindent$$\\displaylines{a\\cr b\\cr}$$ x",
            [(120, 655360), (97, 2228224), (98, 3211264), (120, 4784128)],
        ),
        (
            "x\\par\\noindent$$\\eqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 2228224),
                (61, 2228224),
                (98, 2228224),
                (99, 3211264),
                (61, 3211264),
                (100, 3211264),
                (40, 3211264),
                (49, 3211264),
                (41, 3211264),
                (120, 4784128),
            ],
        ),
        (
            "x\\par\\noindent$$\\leqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 2228224),
                (61, 2228224),
                (98, 2228224),
                (99, 3211264),
                (61, 3211264),
                (100, 3211264),
                (40, 3211264),
                (49, 3211264),
                (41, 3211264),
                (120, 4784128),
            ],
        ),
        (
            "x\\par\\noindent$$\\eqalign{a&=b\\cr c&=d\\cr}$$ x",
            [
                (120, 655360),
                (97, 1277952),
                (61, 1277952),
                (98, 1277952),
                (99, 2260992),
                (61, 2260992),
                (100, 2260992),
                (120, 3296824),
            ],
        ),
        ("x\n\n$$\\hbox to 6.4in{y\\hfil}$$ x", [(120, 655360), (121, 3014656), (120, 4587520)]),
        ("x\n\n$$y$$ x", [(120, 655360), (121, 2228224), (120, 3473408)]),
        ("x\n\n$$\\halign{#\\cr a\\cr}$$ x", [(120, 655360), (97, 3014656), (120, 4587520)]),
        ("x\n\n$$\\displaylines{a\\cr b\\cr}$$ x", [(120, 655360), (97, 3014656), (98, 3997696), (120, 5570560)]),
        (
            "x\n\n$$\\eqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 3014656),
                (61, 3014656),
                (98, 3014656),
                (99, 3997696),
                (61, 3997696),
                (100, 3997696),
                (40, 3997696),
                (49, 3997696),
                (41, 3997696),
                (120, 5570560),
            ],
        ),
        (
            "x\n\n$$\\leqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 3014656),
                (61, 3014656),
                (98, 3014656),
                (99, 3997696),
                (61, 3997696),
                (100, 3997696),
                (40, 3997696),
                (49, 3997696),
                (41, 3997696),
                (120, 5570560),
            ],
        ),
        (
            "x\n\n$$\\eqalign{a&=b\\cr c&=d\\cr}$$ x",
            [
                (120, 655360),
                (97, 2064384),
                (61, 2064384),
                (98, 2064384),
                (99, 3047424),
                (61, 3047424),
                (100, 3047424),
                (120, 4083256),
            ],
        ),
        ("\\parskip=5pt x\\par$$\\hbox to 6.4in{y\\hfil}$$ x", [(120, 655360), (121, 3342336), (120, 4915200)]),
        ("\\parskip=5pt x\\par$$y$$ x", [(120, 655360), (121, 2555904), (120, 3801088)]),
        ("\\parskip=5pt x\\par$$\\halign{#\\cr a\\cr}$$ x", [(120, 655360), (97, 3342336), (120, 4915200)]),
        (
            "\\parskip=5pt x\\par$$\\displaylines{a\\cr b\\cr}$$ x",
            [(120, 655360), (97, 3342336), (98, 4325376), (120, 5898240)],
        ),
        (
            "\\parskip=5pt x\\par$$\\eqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 3342336),
                (61, 3342336),
                (98, 3342336),
                (99, 4325376),
                (61, 4325376),
                (100, 4325376),
                (40, 4325376),
                (49, 4325376),
                (41, 4325376),
                (120, 5898240),
            ],
        ),
        (
            "\\parskip=5pt x\\par$$\\leqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 3342336),
                (61, 3342336),
                (98, 3342336),
                (99, 4325376),
                (61, 4325376),
                (100, 4325376),
                (40, 4325376),
                (49, 4325376),
                (41, 4325376),
                (120, 5898240),
            ],
        ),
        (
            "\\parskip=5pt x\\par$$\\eqalign{a&=b\\cr c&=d\\cr}$$ x",
            [
                (120, 655360),
                (97, 2392064),
                (61, 2392064),
                (98, 2392064),
                (99, 3375104),
                (61, 3375104),
                (100, 3375104),
                (120, 4410936),
            ],
        ),
        ("x\\par\\hrule$$\\hbox to 6.4in{y\\hfil}$$ x", [(120, 655360), (121, 2254438), (120, 3827302)]),
        ("x\\par\\hrule$$y$$ x", [(120, 655360), (121, 1468006), (120, 2713190)]),
        ("x\\par\\hrule$$\\halign{#\\cr a\\cr}$$ x", [(120, 655360), (97, 2254438), (120, 3827302)]),
        (
            "x\\par\\hrule$$\\displaylines{a\\cr b\\cr}$$ x",
            [(120, 655360), (97, 2254438), (98, 3237478), (120, 4810342)],
        ),
        (
            "x\\par\\hrule$$\\eqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 2254438),
                (61, 2254438),
                (98, 2254438),
                (99, 3237478),
                (61, 3237478),
                (100, 3237478),
                (40, 3237478),
                (49, 3237478),
                (41, 3237478),
                (120, 4810342),
            ],
        ),
        (
            "x\\par\\hrule$$\\leqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 2254438),
                (61, 2254438),
                (98, 2254438),
                (99, 3237478),
                (61, 3237478),
                (100, 3237478),
                (40, 3237478),
                (49, 3237478),
                (41, 3237478),
                (120, 4810342),
            ],
        ),
        (
            "x\\par\\hrule$$\\eqalign{a&=b\\cr c&=d\\cr}$$ x",
            [
                (120, 655360),
                (97, 1304166),
                (61, 1304166),
                (98, 1304166),
                (99, 2287206),
                (61, 2287206),
                (100, 2287206),
                (120, 3323038),
            ],
        ),
        ("x$$\\hbox to 6.4in{y\\hfil}$$ x", [(120, 655360), (121, 2228224), (120, 3801088)]),
        ("x$$y$$ x", [(120, 655360), (121, 1441792), (120, 2686976)]),
        ("x$$\\halign{#\\cr a\\cr}$$ x", [(120, 655360), (97, 2228224), (120, 3801088)]),
        ("x$$\\displaylines{a\\cr b\\cr}$$ x", [(120, 655360), (97, 2228224), (98, 3211264), (120, 4784128)]),
        (
            "x$$\\eqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 2228224),
                (61, 2228224),
                (98, 2228224),
                (99, 3211264),
                (61, 3211264),
                (100, 3211264),
                (40, 3211264),
                (49, 3211264),
                (41, 3211264),
                (120, 4784128),
            ],
        ),
        (
            "x$$\\leqalignno{a&=b\\cr c&=d&(1)\\cr}$$ x",
            [
                (120, 655360),
                (97, 2228224),
                (61, 2228224),
                (98, 2228224),
                (99, 3211264),
                (61, 3211264),
                (100, 3211264),
                (40, 3211264),
                (49, 3211264),
                (41, 3211264),
                (120, 4784128),
            ],
        ),
        (
            "x$$\\eqalign{a&=b\\cr c&=d\\cr}$$ x",
            [
                (120, 655360),
                (97, 1277952),
                (61, 1277952),
                (98, 1277952),
                (99, 2260992),
                (61, 2260992),
                (100, 2260992),
                (120, 3296824),
            ],
        ),
    ],
)
def test_display_vertical_positions(body: str, miktex: list) -> None:
    assert [(c, v) for c, _h, v in _page1(body)] == miktex


@pytest.mark.parametrize(
    ("body", "miktex"),
    [
        (
            "x\\par\\noindent$$y\\eqno(1)$$ x",
            [
                (120, 1310720, 655360),
                (121, 15220520, 1441792),
                (40, 29948456, 1441792),
                (49, 30203319, 1441792),
                (41, 30531000, 1441792),
                (120, 0, 2686976),
            ],
        ),
        (
            "\\hsize=300pt x\\par\\noindent$$y\\eqno(1)$$ x",
            [
                (120, 1310720, 655360),
                (121, 9657988, 1441792),
                (40, 18823393, 1441792),
                (49, 19078256, 1441792),
                (41, 19405937, 1441792),
                (120, 0, 2686976),
            ],
        ),
        (
            "x\\par\\noindent$$y\\leqno(1)$$ x",
            [
                (120, 1310720, 655360),
                (40, 0, 2228224),
                (49, 254863, 2228224),
                (41, 582544, 2228224),
                (121, 15220519, 2228224),
                (120, 0, 3801088),
            ],
        ),
        (
            "\\hsize=300pt x\\par\\noindent$$y\\leqno(1)$$ x",
            [
                (120, 1310720, 655360),
                (40, 0, 2228224),
                (49, 254863, 2228224),
                (41, 582544, 2228224),
                (121, 9657988, 2228224),
                (120, 0, 3801088),
            ],
        ),
    ],
)
def test_numbered_display_positions(body: str, miktex: list) -> None:
    # The separate leqno long-skip defect is owned;
    # this member pins centring and both flush equation-number positions.
    assert [(c, h) for c, h, _v in _page1(body)] == [(c, h) for c, h, _v in miktex]


@pytest.mark.parametrize(
    ("body", "miktex"),
    [
        (
            '\\setbox0=\\hbox{$\\vcenter{\\hrule height 2sp width 1pt}$}'
            '\\dimen0=\\wd0\\dimen1=\\ht0\\dimen2=\\dp0'
            '\\message{[DIMS:\\number\\dimen0,\\number\\dimen1,\\number\\dimen2]}',
            ["[DIMS:65536,163841,0]"],
        ),
        (
            '\\setbox0=\\hbox{$\\vcenter{\\hrule height 3sp width 1pt}$}'
            '\\dimen0=\\wd0\\dimen1=\\ht0\\dimen2=\\dp0'
            '\\message{[DIMS:\\number\\dimen0,\\number\\dimen1,\\number\\dimen2]}',
            ["[DIMS:65536,163842,0]"],
        ),
        (
            '\\setbox0=\\hbox{$\\vcenter{\\hrule height 4sp width 1pt}$}'
            '\\dimen0=\\wd0\\dimen1=\\ht0\\dimen2=\\dp0'
            '\\message{[DIMS:\\number\\dimen0,\\number\\dimen1,\\number\\dimen2]}',
            ["[DIMS:65536,163842,0]"],
        ),
        (
            '\\setbox0=\\hbox{$\\vcenter{\\hrule height 5sp width 1pt}$}'
            '\\dimen0=\\wd0\\dimen1=\\ht0\\dimen2=\\dp0'
            '\\message{[DIMS:\\number\\dimen0,\\number\\dimen1,\\number\\dimen2]}',
            ["[DIMS:65536,163843,0]"],
        ),
        (
            '\\setbox0=\\hbox{$\\vcenter{\\hrule height 327681sp width 1pt}$}'
            '\\dimen0=\\wd0\\dimen1=\\ht0\\dimen2=\\dp0'
            '\\message{[DIMS:\\number\\dimen0,\\number\\dimen1,\\number\\dimen2]}',
            ["[DIMS:65536,327681,0]"],
        ),
        (
            '\\setbox0=\\hbox{$\\vcenter{\\hrule height 655361sp width 1pt}$}'
            '\\dimen0=\\wd0\\dimen1=\\ht0\\dimen2=\\dp0'
            '\\message{[DIMS:\\number\\dimen0,\\number\\dimen1,\\number\\dimen2]}',
            ["[DIMS:65536,491521,163840]"],
        ),
        (
            '\\setbox0=\\vbox{\\hbox{$\\vcenter{\\hrule height 2sp width 1pt}$}}'
            '\\dimen0=\\wd0\\dimen1=\\ht0\\dimen2=\\dp0'
            '\\message{[DIMS:\\number\\dimen0,\\number\\dimen1,\\number\\dimen2]}',
            ["[DIMS:65536,163841,0]"],
        ),
        (
            '\\setbox0=\\vbox{\\hbox{$\\vcenter{\\hrule height 3sp width 1pt}$}}'
            '\\dimen0=\\wd0\\dimen1=\\ht0\\dimen2=\\dp0'
            '\\message{[DIMS:\\number\\dimen0,\\number\\dimen1,\\number\\dimen2]}',
            ["[DIMS:65536,163842,0]"],
        ),
        (
            '\\setbox0=\\vbox{\\hbox{$\\vcenter{\\hrule height 4sp width 1pt}$}}'
            '\\dimen0=\\wd0\\dimen1=\\ht0\\dimen2=\\dp0'
            '\\message{[DIMS:\\number\\dimen0,\\number\\dimen1,\\number\\dimen2]}',
            ["[DIMS:65536,163842,0]"],
        ),
        (
            '\\setbox0=\\vbox{\\hbox{$\\vcenter{\\hrule height 5sp width 1pt}$}}'
            '\\dimen0=\\wd0\\dimen1=\\ht0\\dimen2=\\dp0'
            '\\message{[DIMS:\\number\\dimen0,\\number\\dimen1,\\number\\dimen2]}',
            ["[DIMS:65536,163843,0]"],
        ),
        (
            '\\setbox0=\\vbox{\\hbox{$\\vcenter{\\hrule height 327681sp width 1pt}$}}'
            '\\dimen0=\\wd0\\dimen1=\\ht0\\dimen2=\\dp0'
            '\\message{[DIMS:\\number\\dimen0,\\number\\dimen1,\\number\\dimen2]}',
            ["[DIMS:65536,327681,0]"],
        ),
        (
            '\\setbox0=\\vbox{\\hbox{$\\vcenter{\\hrule height 655361sp width 1pt}$}}'
            '\\dimen0=\\wd0\\dimen1=\\ht0\\dimen2=\\dp0'
            '\\message{[DIMS:\\number\\dimen0,\\number\\dimen1,\\number\\dimen2]}',
            ["[DIMS:65536,491521,163840]"],
        ),
    ],
)
def test_vcenter_dimensions(body: str, miktex: list) -> None:
    assert _messages(body) == miktex
