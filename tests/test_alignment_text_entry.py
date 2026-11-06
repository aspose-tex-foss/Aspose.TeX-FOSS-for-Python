""" alignment entry: expectations measured with MiKTeX 24.4 DVI."""

import pytest

from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _run, _tfm_width


@pytest.mark.parametrize(
    "body, expected",
    [
        ("\\noindent\\halign{#\\cr o\\cr}", [[111, 0, 655360]]),
        ("\\noindent\\halign{#\\cr o\\cr o\\cr}", [[111, 0, 655360], [111, 0, 1441792]]),
        ("\\halign{#\\cr o\\cr o\\cr}", [[111, 0, 655360], [111, 0, 1441792]]),
        ("\\indent\\halign{#\\cr o\\cr o\\cr}", [[111, 0, 1441792], [111, 0, 2228224]]),
        (
            "\\noindent a\\halign{#\\cr o\\cr o\\cr}b",
            [[97, 0, 655360], [111, 0, 1441792], [111, 0, 2228224], [98, 1310720, 3014656]],
        ),
        ("\\vbox{\\noindent\\halign{#\\cr o\\cr o\\cr}}", [[111, 0, 282168], [111, 0, 1068600]]),
    ],
)
def test_halign_paragraph_entry(body, expected):
    actual = walk_chars_with_positions(_run(body)._dvi, _tfm_width())[0][:-1]
    assert [list(glyph) for glyph in actual] == expected


@pytest.mark.parametrize(
    "body, expected",
    [
        (
            "\\settabs\\+\\indent&Long sample&Third\\cr\\+ a&b&c\\cr\\+ d&e&f\\cr",
            [
                [97, 0, 655360],
                [98, 1310720, 655360],
                [99, 4927951, 655360],
                [100, 0, 1441792],
                [101, 1310720, 1441792],
                [102, 4927951, 1441792],
            ],
        ),
        ("\\settabs 4\\columns\\+ a&b\\cr", [[97, 0, 655360], [98, 7696465, 655360]]),
        (
            "\\hsize=80pt\\settabs 2\\columns\\+ a&b&c\\cr",
            [[97, 0, 655360], [98, 2621440, 655360], [99, 5242880, 655360]],
        ),
        (
            "\\vbox{\\hsize=80pt\\settabs 2\\columns\\+ a&b\\cr\\+ c&d\\cr}",
            [[97, 0, 455111], [98, 2621440, 455111], [99, 0, 1241543], [100, 2621440, 1241543]],
        ),
        (
            "\\settabs 3\\columns\\cleartabs\\settabs\\+\\indent&Text\\cr\\+ a&b\\cr",
            [[97, 0, 655360], [98, 1310720, 655360]],
        ),
        ("\\hsize=60pt\\settabs 3\\columns\\+ &b&c\\cr", [[98, 1310720, 655360], [99, 2621440, 655360]]),
        (
            "\\setbox10=\\hbox{\\hbox{a}\\global\\setbox11=\\lastbox b}\\box10\\box11",
            [[98, 0, 655360], [97, 0, 1441792]],
        ),
        ("\\halign{#\\cr\\hbox{a}\\global\\setbox11=\\lastbox b\\cr}\\box11", [[98, 0, 655360], [97, 0, 1441792]]),
        (
            "\\settabs\\+\\indent&Text text\\cr\\+ a b&c d\\cr",
            [[97, 0, 655360], [98, 546134, 655360], [99, 1310720, 655360], [100, 1820444, 655360]],
        ),
        (
            "\\settabs 2\\columns\\+ a b&c d\\cr",
            [[97, 0, 655360], [98, 546134, 655360], [99, 15392931, 655360], [100, 15902655, 655360]],
        ),
        (
            "\\settabs 3\\columns\\+ a&b&c\\cr\\+ d&e&f\\cr",
            [
                [97, 0, 655360],
                [98, 10261954, 655360],
                [99, 20523908, 655360],
                [100, 0, 1441792],
                [101, 10261954, 1441792],
                [102, 20523908, 1441792],
            ],
        ),
        (
            "\\settabs 2\\columns\\noindent X\\+ a&b\\cr Y",
            [[88, 0, 655360], [97, 0, 1441792], [98, 15392931, 1441792], [89, 1310720, 2228224]],
        ),
        ("\\vbox{\\settabs 2\\columns\\+ a&b\\cr}", [[97, 0, 655360], [98, 15392931, 655360]]),
    ],
)
def test_tabs_list_ownership(body, expected):
    actual = walk_chars_with_positions(_run(body)._dvi, _tfm_width())[0][:-1]
    assert [list(glyph) for glyph in actual] == expected


@pytest.mark.parametrize(
    "body, expected",
    [
        (
            "\\vbox{\\everypar{X}\\valign{#&#\\cr\\hbox{a}&\\hbox{g}\\cr}}",
            [[88, 1310720, 691767], [97, 1802241, 282168], [103, 1802241, 564336]],
        ),
        (
            "\\vbox{\\parindent=5pt\\valign{#&#\\cr\\hbox{a}&\\hbox{g}\\cr}}",
            [[97, 327680, 282168], [103, 327680, 564336]],
        ),
        (
            "\\let\\VA=\\valign\\vbox{\\VA{#&#\\cr\\hbox{a}&\\hbox{g}\\cr}}",
            [[97, 1310720, 282168], [103, 1310720, 564336]],
        ),
        ("\\vbox{\\valign{#\\cr\\vbox{\\valign{#\\cr\\hbox{a}\\cr}}\\cr}}", [[97, 2621440, 655360]]),
        ("\\vbox{\\valign{#&#\\cr\\hbox{a}&\\hbox{g}\\cr}}", [[97, 1310720, 282168], [103, 1310720, 564336]]),
        ("\\vbox{\\noindent\\valign{#&#\\cr\\hbox{a}&\\hbox{g}\\cr}}", [[97, 0, 282168], [103, 0, 564336]]),
        ("\\noindent X\\valign{#\\cr\\hbox{a}\\cr}Y", [[88, 0, 655360], [97, 491521, 655360], [89, 819202, 655360]]),
        ("$\\vcenter{\\valign{#&#\\cr\\hbox{a}&\\hbox{g}\\cr}}$", [[97, 2621440, 427804], [103, 2621440, 709972]]),
        ("\\valign{#&#\\cr\\hbox{a}&\\hbox{g}\\cr}", [[97, 1310720, 282168], [103, 1310720, 564336]]),
    ],
)
def test_valign_list_ownership(body, expected):
    actual = walk_chars_with_positions(_run(body)._dvi, _tfm_width())[0][:-1]
    assert [list(glyph) for glyph in actual] == expected
