r""" Parity layout pack — accents, ``\noalign`` rules, ``\mag`` in output.

Every expected value is a MiKTeX 24.4 plain measurement of the same input: DVI
glyphs ``(code, h, v)`` and rules ``(h, v, height, width)`` from
``tests/_verification/dvi_walker``, page 1, with ``\nopagenumbers``.
"""

from __future__ import annotations

import re
import warnings

import pytest

from aspose_tex import DviDevice, PdfDevice, StringInputSource, SvgDevice, TeXJob, TeXOptions
from tests._verification.dvi_walker import walk_chars_with_positions, walk_rules
from tests.test_plain_tie import _tfm_width


def _dvi(source: str) -> bytes:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return TeXJob(StringInputSource(source), DviDevice()).run()


def _page(source: str) -> tuple[list, list]:
    """Return page 1's ``(glyphs, rules)`` for *source*."""
    data = _dvi(source)
    return walk_chars_with_positions(data, _tfm_width())[0], walk_rules(data)[0]


# ---------------------------------------------------------------------------
# a one-Ord {…} field is its char (§1186), so accents see the skew
# ---------------------------------------------------------------------------

_ACCENTS = [
    (r"\hat{x}", [(94, 1352363, 655360), (120, 1310720, 655360)], []),
    (r"\widehat{x}", [(98, 1334158, 655360), (120, 1310720, 655360)], []),
    (r"\vec{v}", [(126, 1285272, 655360), (118, 1310720, 655360)], []),
    (r"\bar{f}", [(22, 1451809, 482417), (102, 1310720, 655360)], []),
    (r"\hat{\hat{x}}",
     [(94, 1334158, 482417), (94, 1352363, 655360), (120, 1310720, 655360)], []),
    (r"\hat{\cal A}", [(94, 1535958, 489700), (65, 1310720, 655360)], []),
    (r"x_{\hat{x}}",
     [(120, 1310720, 655360), (94, 1717361, 753663), (120, 1685276, 753663)], []),
]

# §742: scripts of an accent over a char are set inside the accented box, and
# §1186 turns `{\hat x}` into the accent noad itself.
_SCRIPTED_ACCENTS = [
    (r"\hat{x}^2",
     [(94, 1352363, 655360), (120, 1310720, 655360), (50, 1685276, 417535)], []),
    (r"\hat x^2",
     [(94, 1352363, 655360), (120, 1310720, 655360), (50, 1685276, 417535)], []),
    (r"{\hat x}^2",
     [(94, 1352363, 655360), (120, 1310720, 655360), (50, 1685276, 417535)], []),
    (r"\mathord{\hat x}^2",
     [(94, 1352363, 655360), (120, 1310720, 655360), (50, 1685276, 417535)], []),
    (r"\hat{f}_1^2",
     [(94, 1451809, 482417), (102, 1310720, 655360), (50, 1702118, 417535),
      (49, 1631575, 818027)], []),
    (r"\bar{g}_a^b",
     [(22, 1333134, 655360), (103, 1310720, 655360), (98, 1646819, 417535),
      (97, 1623306, 817376)], []),
    (r"\widehat{f}_1",
     [(98, 1433604, 482417), (102, 1310720, 655360), (49, 1631575, 753663)], []),
]

# Controls: fields that must not change — a list or box nucleus keeps §756
# scripts outside the accent; script, radical and over/under fields set as before.
_FIELD_CONTROLS = [
    (r"\hat{xy}^2",
     [(94, 1506570, 655360), (120, 1310720, 655360), (121, 1685276, 655360),
      (50, 2030100, 362267)], []),
    (r"\hat{\hbox{x}}^2",
     [(94, 1319823, 655360), (120, 1310720, 655360), (50, 1656606, 362267)], []),
    (r"x^{a}", [(120, 1310720, 655360), (97, 1685276, 417535)], []),
    (r"f_{a}^{b}",
     [(102, 1310720, 655360), (98, 1702118, 417535), (97, 1631575, 817376)], []),
    (r"x^{\hbox{a}}", [(120, 1310720, 655360), (97, 1685276, 417535)], []),
    (r"\sqrt{x}", [(112, 1310720, 183320), (120, 1856855, 655360)],
     [(1856855, 183320, 26213, 374556)]),
    (r"\sqrt{\hbox{f}}", [(112, 1310720, 96848), (102, 1856855, 655360)],
     [(1856855, 96848, 26213, 200250)]),
    (r"\root 3 \of{x}",
     [(51, 1492760, 434942), (112, 1351688, 183320), (120, 1897823, 655360)],
     [(1897823, 183320, 26213, 374556)]),
    (r"\overline{x}", [(120, 1310720, 655360)], [(1310720, 294553, 26213, 374556)]),
    (r"\underline{f}", [(102, 1310720, 655360)], [(1310720, 887643, 26213, 391398)]),
    (r"\mathop{f}_{a}^{b}",
     [(102, 1310720, 655360), (98, 1702118, 362267), (97, 1631575, 817376)], []),
    (r"a\mathbin{f}b",
     [(97, 1310720, 655360), (102, 1802768, 655360), (98, 2339798, 655360)], []),
]


class TestBracedMathField:
    r"""``\hat{x}`` sets exactly like ``\hat x``."""

    @pytest.mark.parametrize(
        ("formula", "glyphs", "rules"), _ACCENTS + _SCRIPTED_ACCENTS + _FIELD_CONTROLS,
        ids=[row[0] for row in _ACCENTS + _SCRIPTED_ACCENTS + _FIELD_CONTROLS],
    )
    def test_formula_matches_miktex(self, formula, glyphs, rules) -> None:
        assert _page(r"\nopagenumbers $" + formula + r"$\par\bye") == (glyphs, rules)


# ---------------------------------------------------------------------------
# an alignment's own rules take the alignment's width (§806)
# ---------------------------------------------------------------------------

_ALIGNMENT_RULES = {
    "paragraph": (
        r"\noindent Before\par\halign{#\cr g\cr\noalign{\hrule height2pt}b\cr}\noindent After",
        [
            (66, 0, 655360), (101, 464215, 655360), (102, 755486, 655360), (111, 955736, 655360),
            (114, 1283417, 655360), (101, 1540100, 655360), (103, 0, 1441792), (98, 0, 2155406),
            (65, 0, 2941838), (102, 491521, 2941838), (116, 691771, 2941838),
            (101, 946634, 2941838), (114, 1237905, 2941838),
        ],
        [(0, 1700295, 131072, 364090)],
    ),
    "packed_sibling": (
        r"\setbox0\vbox{\halign{#\cr g\cr\noalign{\hrule height2pt}b\cr}\hbox{M}}\box0",
        [(103, 0, 282168), (98, 0, 995782), (77, 0, 1782214)],
        [(0, 540671, 131072, 364090)],
    ),
    "packed_wide_first": (
        r"\setbox0\vbox{\hbox{MMMMMM}\halign{#\cr g\cr\noalign{\hrule height2pt}b\cr}}\box0",
        [
            (77, 0, 447828), (77, 600748, 447828), (77, 1201496, 447828), (77, 1802244, 447828),
            (77, 2402992, 447828), (77, 3003740, 447828), (103, 0, 1234260), (98, 0, 1947874),
        ],
        [(0, 1492763, 131072, 364090)],
    ),
    "vtop": (
        r"\vtop{\halign{#\cr g\cr\noalign{\hrule height2pt}b\cr}\hbox{MMM}}",
        [
            (103, 0, 655360), (98, 0, 1368974), (77, 0, 2155406), (77, 600748, 2155406),
            (77, 1201496, 2155406),
        ],
        [(0, 913863, 131072, 364090)],
    ),
    "vcenter": (
        r"$$\vcenter{\halign{#\cr g\cr\noalign{\hrule height2pt}b\cr}\hbox{MMM}}$$",
        [
            (103, 14491810, 1003064), (98, 14491810, 1716678), (77, 14491810, 2503110),
            (77, 15092558, 2503110), (77, 15693306, 2503110),
        ],
        [(14491810, 1261567, 131072, 364090)],
    ),
    "unvbox": (
        r"\setbox0\vbox{\halign{#\cr g\cr\noalign{\hrule height2pt}b\cr}}\vbox{\hbox{MMMMMM}\unvbo"
        r"x0}",
        [
            (77, 0, 447828), (77, 600748, 447828), (77, 1201496, 447828), (77, 1802244, 447828),
            (77, 2402992, 447828), (77, 3003740, 447828), (103, 0, 729996), (98, 0, 1443610),
        ],
        [(0, 988499, 131072, 364090)],
    ),
    "display": (
        r"\noindent Before$$\halign{#\cr g\cr\noalign{\hrule height2pt}b\cr}$$\noindent After",
        [
            (66, 0, 655360), (101, 464215, 655360), (102, 755486, 655360), (111, 955736, 655360),
            (114, 1283417, 655360), (101, 1540100, 655360), (103, 0, 2228224), (98, 0, 2941838),
            (65, 0, 4514702), (102, 491521, 4514702), (116, 691771, 4514702),
            (101, 946634, 4514702), (114, 1237905, 4514702),
        ],
        [(0, 2486727, 131072, 364090)],
    ),
    "display_to": (
        r"\noindent Before$$\halign to 100pt{#\tabskip 0pt plus 1fil\cr g\cr\noalign{\hrule height"
        r"2pt}b\cr}$$\noindent After",
        [
            (66, 0, 655360), (101, 464215, 655360), (102, 755486, 655360), (111, 955736, 655360),
            (114, 1283417, 655360), (101, 1540100, 655360), (103, 0, 2228224), (98, 0, 2941838),
            (65, 0, 4514702), (102, 491521, 4514702), (116, 691771, 4514702),
            (101, 946634, 4514702), (114, 1237905, 4514702),
        ],
        [(0, 2486727, 131072, 6553600)],
    ),
    "to_direct": (
        r"\halign to 100pt{#\tabskip 0pt plus 1fil&#\cr g&h\cr\noalign{\hrule height2pt}b&c\cr}",
        [(103, 0, 655360), (104, 3276800, 655360), (98, 0, 1368974), (99, 3276800, 1368974)],
        [(0, 913863, 131072, 6553600)],
    ),
    "spread_direct": (
        r"\halign spread 50pt{#\tabskip 0pt plus 1fil&#\cr g&h\cr\noalign{\hrule height2pt}b&c\cr}",
        [(103, 0, 655360), (104, 2002490, 655360), (98, 0, 1368974), (99, 2002490, 1368974)],
        [(0, 913863, 131072, 4004980)],
    ),
    "to_packed": (
        r"\setbox0\vbox{\halign to 100pt{#\tabskip 0pt plus 1fil&#\cr g&h\cr\noalign{\hrule height"
        r"2pt}b&c\cr}\hbox{MMMMMMMMMMMMMMMMMMMMM}}\box0",
        [
            (103, 0, 455111), (104, 3276800, 455111), (98, 0, 1168725), (99, 3276800, 1168725),
            (77, 0, 1955157), (77, 600748, 1955157), (77, 1201496, 1955157),
            (77, 1802244, 1955157), (77, 2402992, 1955157), (77, 3003740, 1955157),
            (77, 3604488, 1955157), (77, 4205236, 1955157), (77, 4805984, 1955157),
            (77, 5406732, 1955157), (77, 6007480, 1955157), (77, 6608228, 1955157),
            (77, 7208976, 1955157), (77, 7809724, 1955157), (77, 8410472, 1955157),
            (77, 9011220, 1955157), (77, 9611968, 1955157), (77, 10212716, 1955157),
            (77, 10813464, 1955157), (77, 11414212, 1955157), (77, 12014960, 1955157),
        ],
        [(0, 713614, 131072, 6553600)],
    ),
    "spread_packed": (
        r"\setbox0\vbox{\halign spread 20pt{#\tabskip 0pt plus 1fil&#\cr g&h\cr\noalign{\hrule hei"
        r"ght2pt}b&c\cr}\hbox{MMMMMMMMMMMMMMMMMMMMM}}\box0",
        [
            (103, 0, 455111), (104, 1019450, 455111), (98, 0, 1168725), (99, 1019450, 1168725),
            (77, 0, 1955157), (77, 600748, 1955157), (77, 1201496, 1955157),
            (77, 1802244, 1955157), (77, 2402992, 1955157), (77, 3003740, 1955157),
            (77, 3604488, 1955157), (77, 4205236, 1955157), (77, 4805984, 1955157),
            (77, 5406732, 1955157), (77, 6007480, 1955157), (77, 6608228, 1955157),
            (77, 7208976, 1955157), (77, 7809724, 1955157), (77, 8410472, 1955157),
            (77, 9011220, 1955157), (77, 9611968, 1955157), (77, 10212716, 1955157),
            (77, 10813464, 1955157), (77, 11414212, 1955157), (77, 12014960, 1955157),
        ],
        [(0, 713614, 131072, 2038900)],
    ),
    "nested_in_noalign": (
        r"\halign{#\cr MMMM\cr\noalign{\halign{#\cr g\cr\noalign{\hrule}b\cr}}}",
        [
            (77, 0, 655360), (77, 600748, 655360), (77, 1201496, 655360), (77, 1802244, 655360),
            (103, 0, 1441792), (98, 0, 2050548),
        ],
        [(0, 1595437, 26214, 364090)],
    ),
    "explicit": (
        r"\setbox0\vbox{\halign{#\cr g\cr\noalign{\hrule width 50pt height2pt}b\cr}\hbox{MMM}}\box"
        r"0",
        [
            (103, 0, 282168), (98, 0, 995782), (77, 0, 1782214), (77, 600748, 1782214),
            (77, 1201496, 1782214),
        ],
        [(0, 540671, 131072, 3276800)],
    ),
    "box_rule_stays_local": (
        r"\halign{#\cr MMMM\cr\noalign{\vbox{\hsize=10pt\hrule\hbox{x}}}x\cr}",
        [
            (77, 0, 655360), (77, 600748, 655360), (77, 1201496, 655360), (77, 1802244, 655360),
            (120, 0, 1441792), (120, 0, 2228224),
        ],
        [(0, 1159624, 26214, 345886)],
    ),
    "leaders_stay_local": (
        r"\halign{#\cr MMMM\cr\noalign{\leaders\hrule\vskip 3pt}x\cr}",
        [
            (77, 0, 655360), (77, 600748, 655360), (77, 1201496, 655360), (77, 1802244, 655360),
            (120, 0, 1638400),
        ],
        [(0, 851968, 196608, 2402992)],
    ),
    "vadjust_rule": (
        r"\setbox0\vbox{\halign{#\cr MMMM\vadjust{\hrule}\cr b\cr}\hbox{MMMMMMMMMMM}}\box0",
        [
            (77, 0, 447828), (77, 600748, 447828), (77, 1201496, 447828), (77, 1802244, 447828),
            (98, 0, 1260474), (77, 0, 2046906), (77, 600748, 2046906), (77, 1201496, 2046906),
            (77, 1802244, 2046906), (77, 2402992, 2046906), (77, 3003740, 2046906),
            (77, 3604488, 2046906), (77, 4205236, 2046906), (77, 4805984, 2046906),
            (77, 5406732, 2046906), (77, 6007480, 2046906),
        ],
        [(0, 474042, 26214, 2402992)],
    ),
    "unused_tabskip": (
        r"\tabskip 5pt\halign{#&#&#\cr a&b\cr\noalign{\hrule}a\cr}",
        [(97, 327680, 655360), (98, 983041, 655360), (97, 327680, 963742)],
        [(0, 681574, 26214, 1674811)],
    ),
    "indent_shifts_rules": (
        r"\hangindent=20pt\hangafter=-9 \noindent Before$$\halign{#\cr g\cr\noalign{\hrule height2"
        r"pt}\noalign{\hrule width 9pt}b\cr}$$\noindent After",
        [
            (66, 1310720, 655360), (101, 1774935, 655360), (102, 2066206, 655360),
            (111, 2266456, 655360), (114, 2594137, 655360), (101, 2850820, 655360),
            (103, 1310720, 2228224), (98, 1310720, 2968052), (65, 1310720, 4540916),
            (102, 1802241, 4540916), (116, 2002491, 4540916), (101, 2257354, 4540916),
            (114, 2548625, 4540916),
        ],
        [(1310720, 2486727, 131072, 364090), (1310720, 2512941, 26214, 589824)],
    ),
    "indent_keeps_boxes": (
        r"\hangindent=20pt\hangafter=-9 \noindent Before$$\halign{#\cr g\cr\noalign{\hbox{M}\kern3"
        r"pt\hrule}b\cr}$$\noindent After",
        [
            (66, 1310720, 655360), (101, 1774935, 655360), (102, 2066206, 655360),
            (111, 2266456, 655360), (114, 2594137, 655360), (101, 2850820, 655360),
            (103, 1310720, 2228224), (77, 0, 3014656), (98, 1310720, 3692589),
            (65, 1310720, 5265453), (102, 1802241, 5265453), (116, 2002491, 5265453),
            (101, 2257354, 5265453), (114, 2548625, 5265453),
        ],
        [(1310720, 3237478, 26214, 364090)],
    ),
    "indent_vadjust": (
        r"\hangindent=20pt\hangafter=-9 \noindent Before$$\halign{#\cr g\vadjust{\hrule}\cr b\vadj"
        r"ust{\hbox{M}}\cr}$$\noindent After",
        [
            (66, 1310720, 655360), (101, 1774935, 655360), (102, 2066206, 655360),
            (111, 2266456, 655360), (114, 2594137, 655360), (101, 2850820, 655360),
            (103, 1310720, 2228224), (98, 1310720, 3040870), (77, 0, 3488698),
            (65, 1310720, 5061562), (102, 1802241, 5061562), (116, 2002491, 5061562),
            (101, 2257354, 5061562), (114, 2548625, 5061562),
        ],
        [(1310720, 2381869, 26214, 364090)],
    ),
    "indent_final_rule": (
        r"\hangindent=20pt\hangafter=-9 \noindent Before$$\halign{#\cr g\cr\noalign{\hrule}}$$\noi"
        r"ndent After",
        [
            (66, 1310720, 655360), (101, 1774935, 655360), (102, 2066206, 655360),
            (111, 2266456, 655360), (114, 2594137, 655360), (101, 2850820, 655360),
            (103, 1310720, 2228224), (65, 1310720, 2836980), (102, 1802241, 2836980),
            (116, 2002491, 2836980), (101, 2257354, 2836980), (114, 2548625, 2836980),
        ],
        [(1310720, 2381869, 26214, 327681)],
    ),
    "indent_final_kern": (
        r"\hangindent=20pt\hangafter=-9 \noindent Before$$\halign{#\cr g\cr\noalign{\hrule\kern0pt"
        r"}}$$\noindent After",
        [
            (66, 1310720, 655360), (101, 1774935, 655360), (102, 2066206, 655360),
            (111, 2266456, 655360), (114, 2594137, 655360), (101, 2850820, 655360),
            (103, 1310720, 2228224), (65, 1310720, 3623412), (102, 1802241, 3623412),
            (116, 2002491, 3623412), (101, 2257354, 3623412), (114, 2548625, 3623412),
        ],
        [(1310720, 2381869, 26214, 327681)],
    ),
    "no_indent_final_rule": (
        r"\noindent Before$$\halign{#\cr g\cr\noalign{\hrule}}$$\noindent After",
        [
            (66, 0, 655360), (101, 464215, 655360), (102, 755486, 655360), (111, 955736, 655360),
            (114, 1283417, 655360), (101, 1540100, 655360), (103, 0, 2228224), (65, 0, 3623412),
            (102, 491521, 3623412), (116, 691771, 3623412), (101, 946634, 3623412),
            (114, 1237905, 3623412),
        ],
        [(0, 2381869, 26214, 327681)],
    ),
}


class TestAlignmentRules:
    r"""``fin_align`` resolves running rules; display indent boxes them."""

    @pytest.mark.parametrize("name", _ALIGNMENT_RULES)
    def test_page_matches_miktex(self, name) -> None:
        body, glyphs, rules = _ALIGNMENT_RULES[name]
        assert _page(r"\nopagenumbers " + body + r"\bye") == (glyphs, rules)


# ---------------------------------------------------------------------------
# \mag reaches the output (§288, §617)
# ---------------------------------------------------------------------------

_SQUARE = r"\noindent\vrule width 1truein height 1truein depth 0pt "


def _run(device, source: str, **options):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job = TeXJob(StringInputSource(source), device, options=TeXOptions(**options))
        return job, job.run()


def _preamble_mag(dvi: bytes) -> int:
    return int.from_bytes(dvi[10:14], "big")


def _postamble_mag(dvi: bytes) -> int:
    end = len(dvi) - 1
    while dvi[end] == 223:
        end -= 1
    post = int.from_bytes(dvi[end - 4:end], "big")
    return int.from_bytes(dvi[post + 13:post + 17], "big")


def _pdf_content(pdf: bytes) -> bytes:
    return b"".join(re.findall(rb"stream\n(.*?)\nendstream", pdf, re.S)[:1])


def _numbers(text: bytes) -> list[float]:
    return [float(n) for n in re.findall(rb"-?\d+(?:\.\d+)?", text)]


class TestMagnificationInDvi:
    r"""The preamble and postamble carry the job's ``\mag``, as MiKTeX's DVI does."""

    @pytest.mark.parametrize(("source", "expected"), [
        (r"\magnification=1200 \nopagenumbers \noindent x \bye", 1200),
        (r"\magnification=\magstep2 \nopagenumbers Hello world.\par\bye", 1440),
        (r"\mag=32768 \nopagenumbers x\bye", 32768),
        (r"\mag=1300 \shipout\hbox{x}\end", 1300),
        (r"{\mag=1400 \shipout\hbox{x}}\end", 1400),
        (r"{\mag=1400 }\shipout\hbox{x}\end", 1000),
        (r"\nopagenumbers x\bye", 1000),
        (r"\mag=1200 \nopagenumbers x\vfill\eject\mag=1500 y\bye", 1200),
        (r"\nopagenumbers x\vfill\eject\mag=1500 y\bye", 1000),
        (r"\mag=0 \nopagenumbers x\bye", 1000),
        (r"\mag=-5 \nopagenumbers x\bye", 1000),
        (r"\mag=40000 \nopagenumbers x\bye", 1000),
    ])
    def test_first_shipout_fixes_mag(self, source, expected) -> None:
        _, dvi = _run(DviDevice(), source)
        assert (_preamble_mag(dvi), _postamble_mag(dvi)) == (expected, expected)

    def test_illegal_mag_is_reported(self) -> None:
        job, _ = _run(DviDevice(), r"\mag=0 \nopagenumbers x\bye")
        assert "! Illegal magnification has been changed to 1000 (0)." in job.messages

    def test_page_positions_stay_unmagnified(self) -> None:
        # DVI coordinates are unmagnified: `1truein` at \mag=1200 is 5/6in.
        glyphs, rules = _page(r"\magnification=1200 \nopagenumbers " + _SQUARE + r"x\bye")
        assert rules == [(0, 3946881, 3946881, 3946881)]
        assert glyphs[0][1] == 0

    def test_explicit_option_overrides_the_document(self) -> None:
        _, dvi = _run(DviDevice(), r"\mag=1200 \nopagenumbers x\bye", magnification=1500)
        assert _preamble_mag(dvi) == 1500

    def test_explicit_option_applies_without_a_document_mag(self) -> None:
        _, dvi = _run(DviDevice(), r"\nopagenumbers x\bye", magnification=1500)
        assert _preamble_mag(dvi) == 1500


class TestMagnificationInPdfAndSvg:
    r"""Content scales by ``\mag/1000`` around a physical 1in origin (US Letter).

    pdfTeX with a Letter page and a ``true`` origin paints this square at
    device ``72 648`` sized ``72``; dvisvgm measures 71.999551bp, the exact
    value of the rounded ``1truein``, and dvipdfmx uses the same origin.
    """

    @pytest.mark.parametrize("mag", [500, 1200, 2000])
    def test_pdf_square_is_a_true_inch(self, mag) -> None:
        source = rf"\mag={mag} \nopagenumbers " + _SQUARE + r"\bye"
        _, pdf = _run(PdfDevice(), source)
        rect = re.search(rb"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re", _pdf_content(pdf))
        assert _numbers(rect.group(0)) == pytest.approx([72, 648, 72, 72], abs=0.001)

    @pytest.mark.parametrize("mag", [500, 1200, 2000])
    def test_svg_square_is_a_true_inch(self, mag) -> None:
        source = rf"\mag={mag} \nopagenumbers " + _SQUARE + r"\bye"
        _, svg = _run(SvgDevice(), source)
        rect = re.search(rb"<rect [^>]*>", svg).group(0)
        assert _numbers(rect) == pytest.approx([72, 72, 72, 72], abs=0.001)

    def test_pdf_font_size_is_magnified(self) -> None:
        _, pdf = _run(PdfDevice(), r"\magnification=1200 \nopagenumbers \noindent x \bye")
        size = re.search(rb"/F1 ([\d.]+) Tf", _pdf_content(pdf)).group(1)
        assert float(size) == pytest.approx(9.9626 * 1.2, abs=0.001)

    def test_svg_glyph_positions_are_magnified(self) -> None:
        plain = r"\nopagenumbers \noindent\kern1in x\bye"
        _, normal = _run(SvgDevice(), plain)
        _, doubled = _run(SvgDevice(), r"\mag=2000 " + plain)
        x_normal = _numbers(re.search(rb'<use [^>]*x="[\d.]+"', normal).group(0).split(b"x=")[-1])
        x_doubled = _numbers(re.search(rb'<use [^>]*x="[\d.]+"', doubled).group(0).split(b"x=")[-1])
        assert x_doubled[0] - 72 == pytest.approx(2 * (x_normal[0] - 72), abs=0.001)

    def test_mag_is_fixed_by_the_first_page(self) -> None:
        body = r"\nopagenumbers \noindent\vrule width 72.27pt height 1pt depth 0pt \par"
        _, pdf = _run(PdfDevice(), r"\mag=2000 " + body + r"\vfill\eject\mag=1000 " + body + r"\bye")
        widths = [_numbers(m)[2] for m in re.findall(rb"[\d.]+ [\d.]+ [\d.]+ [\d.]+ re", pdf)]
        assert widths == pytest.approx([144, 144], abs=0.001)

    def test_document_without_mag_is_unscaled(self) -> None:
        _, pdf = _run(PdfDevice(), r"\nopagenumbers " + _SQUARE + r"\bye")
        assert b"72 648 72 72 re" in _pdf_content(pdf)
        _, svg = _run(SvgDevice(), r"\nopagenumbers " + _SQUARE + r"\bye")
        assert b'<rect x="72" y="72" width="72" height="72"' in svg

    def test_explicit_option_scales_pdf_too(self) -> None:
        source = r"\nopagenumbers \noindent\vrule width 72.27pt height 1pt depth 0pt \bye"
        _, pdf = _run(PdfDevice(), source, magnification=2000)
        rect = re.search(rb"[\d.]+ [\d.]+ [\d.]+ [\d.]+ re", _pdf_content(pdf)).group(0)
        assert _numbers(rect)[2] == pytest.approx(144, abs=0.001)
