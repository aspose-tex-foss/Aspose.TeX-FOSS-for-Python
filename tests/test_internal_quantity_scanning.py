"""MiKTeX 24.4 measured witnesses for scanning internal integers, dimensions and glue."""

from __future__ import annotations

import warnings

import pytest

from aspose_tex._input import StringInputSource
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions


def messages(source: str) -> list[str]:
    source = source.replace(r"\message{", r"\message{SCAN:")
    job = TeXJob(StringInputSource(source + r"\bye"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job.run()
    return [message.removeprefix("SCAN:") for message in job.messages if message.startswith("SCAN:")]


@pytest.mark.parametrize(
    "context",
    [
        "{}",
        r"\noindent A {} B\par",
        r"\setbox9\hbox{{{}}}",
        r"\setbox9\vbox{{{}AB\par}}",
        "$a{}b$",
        r"\halign{{#\cr {}AB\cr}}",
    ],
)
def test_integer_box_and_font_contexts(context: str) -> None:
    source = r"\setbox0\hbox{A}\message{\number\wd0,\number\ht0,\number\dp0,\number\fontdimen6\tenrm}"
    assert messages(context.format(source)) == ["491521,447828,0,655361"]


@pytest.mark.parametrize("operand", [r"\skip0", r"\s", r"\baselineskip", r"\muskip0", r"\m", r"\thinmuskip"])
def test_integer_glue_coercion(operand: str) -> None:
    source = (
        r"\skipdef\s=0\muskipdef\m=0\skip0=3pt plus2fil\baselineskip=3pt plus2fil"
        r"\muskip0=3mu plus2fil\thinmuskip=3mu plus2fil"
    )
    assert messages(source + r"\message{\number-" + operand + "}") == ["-196608"]


def test_integer_box_assignment_condition_and_macro() -> None:
    assert messages(
        r"\setbox0\hbox{A}\def\operand{\wd0}\count0=\operand\ifnum\operand>0\message{\number\count0}\fi"
    ) == ["491521"]


def test_integer_void_box_and_font_zero() -> None:
    assert messages(r"\message{\number\wd17,\number\dp17,\number\fontdimen1\tenrm}") == ["0,0,0"]


@pytest.mark.parametrize("operand", [r"\skip3", r"\s", r"\baselineskip"])
@pytest.mark.parametrize("coefficient, expected", [("", "196608"), ("2", "393216"), ("-.5", "-98304")])
def test_glue_as_dimension_and_unit(operand: str, coefficient: str, expected: str) -> None:
    source = r"\skipdef\s=3\skip3=3pt plus2fil minus1pt\baselineskip=\skip3\dimen0="
    assert messages(source + coefficient + operand + r"\message{\number\dimen0}") == [expected]


def test_glue_kern_preserves_following_character_and_source() -> None:
    assert messages(r"\skip0=3pt plus1pt\setbox2\hbox{\kern\skip0 x}\message{\number\wd2;\the\skip0}") == [
        "542494;3.0pt plus 1.0pt"
    ]


@pytest.mark.parametrize("operand", [r"\skip0", r"\s", r"\baselineskip"])
@pytest.mark.parametrize(
    "sign, expected", [("-", "-3.0pt plus -2.0fil minus -1.0fill"), ("- + -", "3.0pt plus 2.0fil minus 1.0fill")]
)
def test_signed_internal_glue_all_components(operand: str, sign: str, expected: str) -> None:
    source = r"\skipdef\s=0\skip0=3pt plus2fil minus1fill\baselineskip=\skip0\skip1="
    assert messages(source + sign + operand + r"\message{\the\skip1;\the\skip0}") == [
        expected + ";3.0pt plus 2.0fil minus 1.0fill"
    ]


def test_signed_literal_glue_sign_only_applies_to_width() -> None:
    assert messages(r"\skip0=-3pt plus2fil minus1fill\message{\the\skip0}") == ["-3.0pt plus 2.0fil minus 1.0fill"]


def test_negated_math_and_horizontal_glue_badness() -> None:
    assert messages(
        r"\thinmuskip=0mu plus1fil\setbox0\hbox to100pt{$a\!b$}\message{\the\badness}"
        r"\skip0=0pt plus1fil\setbox0\hbox to100pt{a\hskip-\skip0 b}\message{\the\badness}"
    ) == ["0", "0"]


def test_negated_muskip_alias_preserves_orders_and_natural_width() -> None:
    assert messages(
        r"\muskipdef\m=0\muskip0=3mu plus2fil minus1fill\muskip1=-\m\message{\the\muskip1}"
        r"\setbox0\hbox{$a\!b$}\message{\number\wd0}"
    ) == ["-3.0mu plus -2.0fil minus -1.0fill", "518450"]


@pytest.mark.parametrize(
    "source, expected",
    [
        (r"\skip0=0pt plus1fil\setbox0\vbox to100pt{\hbox{a}\vskip-\skip0}", "0"),
        (r"\skip0=0pt minus1fill\setbox0\hbox to0pt{a\hskip-\skip0}", "0"),
        (r"\skip0=0pt plus1fil\setbox0\hbox to100pt{a\hskip\skip0\hskip-\skip0}", "10000"),
        (r"\skip0=0pt plus1pt minus1pt\setbox0\hbox to100pt{a\hskip-\skip0}", "10000"),
        (r"\skip0=0pt plus1fil\setbox0\hbox to100pt{a\hskip-\skip0\hskip0pt plus1fill}", "0"),
    ],
)
def test_negative_flex_and_cancellation(source: str, expected: str) -> None:
    assert messages(source + r"\message{\the\badness}") == [expected]


@pytest.mark.parametrize(
    "text, expected",
    [("1,5pt", "98304"), (",5pt", "32768"), ("-,5pt", "-32768"), ("0,123456789pt", "8091"), ("1,9sp", "1")],
)
def test_decimal_comma_dimensions(text: str, expected: str) -> None:
    assert messages(r"\dimen0=" + text + r"\message{\number\dimen0}") == [expected]


@pytest.mark.parametrize("order", ["fil", "fill", "filll"])
def test_decimal_comma_fil_and_normal_fallback(order: str) -> None:
    assert messages(r"\skip0=1,5pt plus2,5" + order + r" minus,5pt\message{\the\skip0}") == [
        "1.5pt plus 2.5" + order + " minus 0.5pt"
    ]


@pytest.mark.parametrize("catcode", [11, 13])
def test_decimal_comma_requires_other_catcode(catcode: int) -> None:
    with pytest.raises(EngineError):
        messages(r"\catcode`\,=" + str(catcode) + r" \dimen0=1,5pt")


def test_macro_decimal_comma_and_next_token() -> None:
    assert messages(
        r"\def\fraction{,5}\dimen0=1\fraction pt\message{\number\dimen0}"
        r"\skip0=0pt plus\fraction fil\message{\the\skip0}"
    ) == ["98304", "0.0pt plus 0.5fil"]


@pytest.mark.parametrize("size, quad", [("at5pt", "334960"), ("at20pt", "1339840"), ("scaled1440", "964684")])
def test_slant_is_unscaled_but_quad_remains_scaled(size: str, quad: str) -> None:
    assert messages(
        r"\font\itfont=cmti10 "
        + size
        + r"\message{\the\fontdimen1\itfont;\number\fontdimen6\itfont}\fontdimen1\itfont=,5pt"
        r"\message{\the\fontdimen1\itfont;\the\fontdimen1\tenit}"
    ) == ["0.25pt;" + quad, "0.5pt;0.25pt"]


def test_edef_combines_scanners_and_preserves_glue_components() -> None:
    assert messages(
        r"\setbox0\hbox{A}\skip0=1,5pt plus2,5fil minus,5pt\skip1=-\skip0"
        r"\edef\value{\number\wd0;\number\skip1;\the\skip1;\the\fontdimen1\tenit}\message{\value}"
    ) == ["491521;-98304;-1.5pt plus -2.5fil minus -0.5pt;0.25pt"]
