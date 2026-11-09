r"""Spaces at the start of a template's u-part (TeX §783).

TeX drops a space token while the u-part is still empty, so a preamble split
over two lines after ``&`` adds nothing to the next column. Every expected
value is a MiKTeX 24.4 measurement of the same input; none is computed.
"""

import pytest

from aspose_tex import DviDevice
from tests._verification.dvi_walker import walk_rules
from tests.test_leaders_shipout import _compile
from tests.test_plain_tie import _messages

_DIMS = r"\message{[\number\wd0,\number\ht0,\number\dp0]}"
_SPTOK = r"\def\:{\let\sptok= } \:  "

_RULED_TABLE = "\n".join([
    r"\nopagenumbers",
    r"$$\vbox{\offinterlineskip \tabskip=0pt",
    r"\halign{\strut\vrule#&\quad\hfil#\hfil\quad&\vrule#&",
    r"        \quad#\hfil\quad&\vrule#&\quad\hfil#\quad&\vrule#\cr",
    r"\noalign{\hrule}",
    r"&\multispan5\hfil\bf Font table\hfil&\cr",
    r"\noalign{\hrule}",
    r"&\bf Name&&\bf Shape&&\bf Size&\cr",
    r"\noalign{\hrule}",
    r"&cmr10&&roman&&10pt&\cr",
    r"&cmbx12&&bold extended&&12pt&\cr",
    r"&cmti10&&text italic&&10pt&\cr",
    r"&cmmi10&&math italic $\alpha\beta$&&10pt&\cr",
    r"&cmex10&&extensions $\displaystyle\sum\int$&&10pt&\cr",
    r"\noalign{\hrule}}}$$",
])


@pytest.mark.parametrize(
    ("body", "miktex"),
    [
        pytest.param("\\setbox0\\vbox{\\halign{#&\n  x#\\cr a&b\\cr}}",
                     "[1037657,455111,0]", id="line-break-after-tab"),
        pytest.param(r"\setbox0\vbox{\halign{ x#\cr a\cr}}",
                     "[673567,282168,0]", id="first-column"),
        pytest.param(r"\setbox0\vbox{\halign{#& #\cr a&b\cr}}",
                     "[691771,455111,0]", id="space-directly-before-hash"),
        pytest.param(r"\setbox0\vbox{\halign{$#$& $x#$\cr a&b\cr}}",
                     "[1002230,455111,0]", id="math-cell"),
        pytest.param(r"\setbox0\vbox{\halign{#& x#\cr a\span b\cr}}",
                     "[1037657,455111,0]", id="spanned-cell"),
        pytest.param(r"\def\p{\halign{##& x##\cr a&b\cr}}\setbox0\vbox{\p}",
                     "[1037657,455111,0]", id="preamble-in-macro"),
        pytest.param(_SPTOK + r"\setbox0\vbox{\halign{#&\sptok\sptok  x#\cr a&b\cr}}",
                     "[1037657,455111,0]", id="implicit-space"),
        pytest.param(r"\setbox0\hbox{\valign{ \vskip1pt#\cr \hbox{a}\cr}}",
                     "[327681,347704,0]", id="valign"),
    ],
)
def test_leading_space_of_a_u_part_is_dropped(body: str, miktex: str) -> None:
    """A space before the u-part's first real token adds nothing to the column."""
    assert _messages(body + _DIMS) == [miktex]


@pytest.mark.parametrize(
    ("body", "miktex"),
    [
        pytest.param(r"\setbox0\vbox{\halign{#&x y#\cr a&b\cr}}",
                     "[1601996,455111,127431]", id="inside-u-part"),
        pytest.param(r"\setbox0\vbox{\halign{#&# y \cr a&b\cr}}",
                     "[1474563,455111,127431]", id="v-part"),
        pytest.param(r"\setbox0\vbox{\halign{#&x# \cr a&b\cr}}",
                     "[1256110,455111,0]", id="right-after-hash"),
        pytest.param(r"\setbox0\vbox{\halign{#& \ x#\cr a&b\cr}}",
                     "[1256110,455111,0]", id="control-space"),
        pytest.param(r"\setbox0\vbox{\halign{#&\space x#\cr a&b\cr}}",
                     "[1256110,455111,0]", id="space-macro"),
    ],
)
def test_other_spaces_of_a_template_stay(body: str, miktex: str) -> None:
    r"""Only the leading spacer goes: ``\ `` and ``\space`` are not spacers there."""
    assert _messages(body + _DIMS) == [miktex]


@pytest.mark.parametrize(
    ("body", "miktex"),
    [
        pytest.param(r"\setbox0\vbox{\halign{#& \tabskip=2pt x#\cr a&b\cr}}",
                     "[1168729,455111,0]", id="space-before"),
        pytest.param(r"\setbox0\vbox{\halign{#&\tabskip=2pt  x#\cr a&b\cr}}",
                     "[1168729,455111,0]", id="space-after"),
        pytest.param(r"\setbox0\vbox{\halign{#& \tabskip=2pt \quad#\cr a&b\cr}}",
                     "[1478204,455111,0]", id="both-sides"),
    ],
)
def test_tabskip_leaves_the_u_part_empty(body: str, miktex: str) -> None:
    r"""A preamble ``\tabskip`` adds no token, so spaces after it are still leading."""
    assert _messages(body + _DIMS) == [miktex]


@pytest.mark.parametrize(
    ("body", "miktex"),
    [
        pytest.param(r"\setbox0\vbox{\halign{x#& &y#&z#\cr a&b&c&d\cr}}",
                     "[2676061,455111,127431]", id="between-tabs"),
        pytest.param(r"\setbox0\vbox{\halign{ &y#&z#\cr a&b&c\cr}}",
                     "[1947880,455111,127431]", id="at-preamble-start"),
        pytest.param(_SPTOK + r"\setbox0\vbox{\halign{x#&\sptok&y#\cr a&b&c\cr}}",
                     "[2020700,455111,127431]", id="implicit-space"),
    ],
)
def test_space_does_not_hide_the_periodic_tab(body: str, miktex: str) -> None:
    """A segment holding only a space is empty, so its ``&`` starts the repeat."""
    assert _messages(body + _DIMS) == [miktex]


def test_ruled_table_with_a_two_line_preamble() -> None:
    r"""The visual check table: every ``\vrule`` column and ``\hrule`` width as MiKTeX."""
    rules = walk_rules(_compile(_RULED_TABLE, DviDevice()))[0]

    assert len(rules) == 30
    assert sorted({h for h, _, _, width in rules if width == 26214}) == [
        9126641, 12684525, 18889335, 21633008,
    ]
    assert {width for _, _, height, width in rules if height == 26214} == {12532581}
