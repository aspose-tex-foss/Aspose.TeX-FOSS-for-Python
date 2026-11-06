r""" — the expander reads meanings, and prints them as TeX does.

*: ``\if``/``\ifcat`` compare a token's meaning (§506), so an alias of
  ``\relax`` is code 256 / category 16 like any other non-character, and
  ``\the`` and the number/dimension/glue scanners read a ``\let`` alias of a
  primitive as that primitive (``\let\cnt=\count``).
*: ``\let`` skips a space it means, not only a typed one (§1221).
*: ``\futurelet`` is a ``\let`` assignment: local unless ``\global``,
  ``\afterassignment`` fires, an active character may be the target.
*: ``\show`` and ``\showthe`` log TeX's text and processing goes on.
*: ``\meaning`` of a character names its category (§298):
  ``blank space``, ``begin-group character`` ...
*: token-list text puts a space after a control word (§262), doubles
  a macro parameter character, prints ``\escapechar`` and a macro's
  parameter text (§294) in ``\meaning``, ``\message`` and ``\write``.

Every expected value is MiKTeX 24.4 plain output (``\message`` text and the
``> …`` lines of ``\show`` in the log; probe a reference probe,
2026-10-14).
"""

from __future__ import annotations

import pytest

from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.macro import PrimitiveMeaning
from aspose_tex._input import CatcodeTable, InputReader, StringInputSource, Tokenizer
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken, PrimitiveRefToken
from tests.test_plain_tie import _run


def _log(body: str) -> list[str]:
    """``\\message`` texts, then ``\\show`` texts, of plain ``<body>\\bye``."""
    messages = _run(body).messages
    return ([m for m in messages if m.startswith("[")]
            + [m for m in messages if m.startswith("> ")])


_TEX290 = [
    pytest.param(
        r'\let\ra=\relax \message{[\ifcat\ra\relax T\else F\fi]}',
        [r'[T]'],
        id='ifcat-ra',
    ),
    pytest.param(
        r'\let\ra=\relax \message{[\if\ra\relax T\else F\fi]}',
        [r'[T]'],
        id='if-ra',
    ),
    pytest.param(
        r'\message{[\ifcat\bgroup{T\else F\fi\iffalse}\fi]}',
        [r'[T]'],
        id='ifcat-bgroup-brace',
    ),
    pytest.param(
        r'\message{[\iffalse{\fi\ifcat\egroup}T\else F\fi]}',
        [r'[T]'],
        id='ifcat-egroup-brace',
    ),
    pytest.param(
        r'\let\lb={ \message{[\if\bgroup\lb T\else F\fi]}',
        [r'[T]'],
        id='if-bgroup-lb',
    ),
    pytest.param(
        r'\message{[\if\bgroup(T\else F\fi]}',
        [r'[F]'],
        id='if-bgroup-paren',
    ),
    pytest.param(
        r'\message{[\ifcat\relax\par T\else F\fi]}',
        [r'[T]'],
        id='ifcat-relax-par',
    ),
    pytest.param(
        r'\let\x=a \message{[\ifcat\x b\if\x a T\else F\fi\else N\fi]}',
        [r'[ T]'],
        id='ifcat-letalias-a',
    ),
    pytest.param(
        r'\message{[\ifcat\noexpand~\relax T\else F\fi]}',
        [r'[F]'],
        id='ifcat-noexpand-active',
    ),
    pytest.param(
        r'\message{[\ifcat\noexpand~\noexpand~T\else F\fi]}',
        [r'[T]'],
        id='ifcat-noexpand-active2',
    ),
    pytest.param(
        r'\message{[\if\noexpand~~T\else F\fi]}',
        [r'[F]'],
        id='if-noexpand-active-char',
    ),
    pytest.param(
        r'\let\ra=\relax \setbox0\hbox{\message{[\ifcat\ra\relax T\else F\fi]}}',
        [r'[T]'],
        id='ifcat-ra-hbox',
    ),
    pytest.param(
        r'\let\ra=\relax $\message{[\ifcat\ra\relax T\else F\fi]}$',
        [r'[T]'],
        id='ifcat-ra-math',
    ),
    pytest.param(
        r'\let\ra=\relax \setbox0\vbox{\message{[\ifcat\ra\relax T\else F\fi]}}',
        [r'[T]'],
        id='ifcat-ra-vbox',
    ),
    pytest.param(
        r'\let\ra=\relax x\message{[\ifcat\ra\relax T\else F\fi]}y',
        [r'[T]'],
        id='ifcat-ra-par',
    ),
    pytest.param(
        r'\let\ra=\relax \edef\r{\ifcat\ra\relax T\else F\fi}\message{[\meaning\r]}',
        [r'[macro:->T]'],
        id='ifcat-ra-edef',
    ),
    pytest.param(
        r'\let\ra=\relax \halign{#\cr\message{[\ifcat\ra\relax T\else F\fi]}x\cr}',
        [r'[T]'],
        id='ifcat-ra-halign',
    ),
    pytest.param(
        r'\let\myfi=\fi \edef\x{\ifnum1=1 A\else B\myfi}\message{[\meaning\x]}',
        [r'[macro:->A]'],
        id='myfi',
    ),
    pytest.param(
        r'\let\myelse=\else \edef\x{\ifnum1=2 A\myelse B\fi}\message{[\meaning\x]}',
        [r'[macro:->B]'],
        id='myelse',
    ),
    pytest.param(
        r'\let\endif=\fi \edef\x{\iffalse a\endif b}\message{[\meaning\x]}',
        [r'[macro:->b]'],
        id='endif',
    ),
    pytest.param(
        r'\let\cnt=\count \count5=7 \edef\x{\the\cnt5}\message{[\meaning\x]}',
        [r'[macro:->7]'],
        id='the-cnt-edef',
    ),
    pytest.param(
        r'\let\hs=\hsize \message{[\the\hs]}',
        [r'[469.75499pt]'],
        id='the-hs',
    ),
    pytest.param(
        r'\let\wdd=\wd \setbox0\hbox{o}\message{[\the\wdd0]}',
        [r'[5.00002pt]'],
        id='the-wdd',
    ),
    pytest.param(
        r'\let\width=\wd\setbox0\hbox{o}\wd0=-1sp\message{[\the\width0]}',
        [r'[-0.00002pt]'],
        id='the-width-1sp',
    ),
    pytest.param(
        r'\let\sk=\skip \skip3=1pt plus 2fil\relax \message{[\the\sk3]}',
        [r'[1.0pt plus 2.0fil]'],
        id='the-skip',
    ),
    pytest.param(
        r'\let\tk=\toks \toks2={ab}\message{[\the\tk2]}',
        [r'[ab]'],
        id='the-toks',
    ),
    pytest.param(
        r'\let\cc=\catcode \message{[\the\cc`\a]}',
        [r'[11]'],
        id='the-catcode',
    ),
    pytest.param(
        r'\let\cnt=\count \cnt5=9 \message{[\the\count5]}',
        [r'[9]'],
        id='the-cnt-assign',
    ),
    pytest.param(
        r'\let\cnt=\count \count5=7 \message{[\number\cnt5]}',
        [r'[7]'],
        id='number-cnt',
    ),
    pytest.param(
        r'\let\cnt=\count \count5=7 \count6=\cnt5 \message{[\the\count6]}',
        [r'[7]'],
        id='count-from-alias',
    ),
    pytest.param(
        r'\let\hs=\hsize \setbox0\hbox{\message{[\the\hs]}}',
        [r'[469.75499pt]'],
        id='the-hs-hbox',
    ),
    pytest.param(
        r'\let\hs=\hsize $\message{[\the\hs]}$',
        [r'[469.75499pt]'],
        id='the-hs-math',
    ),
    pytest.param(
        r'\let\cnt=\count \count5=7 x\message{[\the\cnt5]}y',
        [r'[7]'],
        id='the-cnt-par',
    ),
    pytest.param(
        r'\let\dm=\dimen \dimen4=2pt \message{[\the\dm4]}',
        [r'[2.0pt]'],
        id='the-dimen-alias',
    ),
    pytest.param(
        r'\let\hh=\ht \let\dd=\dp \setbox0\hbox{g}\message{[\the\hh0/\the\dd0]}',
        [r'[4.30554pt/1.94444pt]'],
        id='the-ht-dp-alias',
    ),
    pytest.param(
        r'\let\bs=\baselineskip \message{[\the\bs]}',
        [r'[12.0pt]'],
        id='the-baselineskip',
    ),
    pytest.param(
        r'\let\pa=\parindent \let\pb=\pa \message{[\the\pb]}',
        [r'[20.0pt]'],
        id='the-parindent-alias-chain',
    ),
]

_TEX292 = [
    pytest.param(
        r'\def\:{\let\sptok= }\: \let\q=\sptok\relax \message{[\meaning\q]}',
        [r'[\relax]'],
        id='let-implicit-space-after-eq',
    ),
    pytest.param(
        r'\def\:{\let\sptok= }\: \let\q= \sptok\relax \message{[\meaning\q]}',
        [r'[blank space  ]'],
        id='let-explicit-space-then-sptok',
    ),
    pytest.param(
        r'\def\:{\let\sptok= }\: \let\q\sptok=\relax \message{[\meaning\q]}',
        [r'[\relax]'],
        id='let-implicit-space-before-eq',
    ),
    pytest.param(
        r'\def\:{\let\sptok= }\: \let\q\sptok\relax \message{[\meaning\q]}',
        [r'[\relax]'],
        id='let-implicit-space-noeq',
    ),
]

_TEX288 = [
    pytest.param(
        r'{\futurelet\x\relax\relax}\message{[\meaning\x]}',
        [r'[undefined]'],
        id='futurelet-local',
    ),
    pytest.param(
        r'{\global\futurelet\x\relax\relax}\message{[\meaning\x]}',
        [r'[\relax]'],
        id='futurelet-global',
    ),
    pytest.param(
        r'\def\a{\message{[A]}}\def\b{\message{[B]}}\def\c{\message{[C]}}\afterassignment\a\futurelet\x\b\c',
        [r'[A]', r'[B]', r'[C]'],
        id='futurelet-after',
    ),
    pytest.param(
        r'{\futurelet~\relax\relax\message{[\meaning~]}}\message{[\meaning~]}',
        [r'[\relax]', r'[macro:->\penalty \@M \ ]'],
        id='futurelet-active',
    ),
    pytest.param(
        r'{\futurelet\x\relax\relax\message{[\meaning\x]}}',
        [r'[\relax]'],
        id='futurelet-inner',
    ),
    pytest.param(
        r'\setbox0\hbox{\futurelet\x\relax\relax}\message{[\meaning\x]}',
        [r'[undefined]'],
        id='futurelet-hbox',
    ),
    pytest.param(
        r'\def\:{\let\sptok= }\: \futurelet\x\sptok\relax\message{[\meaning\x]}',
        [r'[\relax]'],
        id='futurelet-space',
    ),
]

_TEX285 = [
    pytest.param(
        r'\def\x{X}\show\x \message{[ok]}',
        [r'[ok]', '> \\x=macro:\n->X.'],
        id='show-macro',
    ),
    pytest.param(
        r'\showthe\count0 \message{[ok]}',
        [r'[ok]', r'> 1.'],
        id='showthe-count',
    ),
    pytest.param(
        r'{\csname par\endcsname}\expandafter\show\csname hbox\endcsname\message{[ok]}',
        [r'[ok]', r'> \hbox=\hbox.'],
        id='show-hbox-csname',
    ),
    pytest.param(
        r'\show a\message{[ok]}',
        [r'[ok]', r'> the letter a.'],
        id='show-letter',
    ),
    pytest.param(
        r'\show~\message{[ok]}',
        [r'[ok]', '> ~=macro:\n->\\penalty \\@M \\ .'],
        id='show-active',
    ),
    pytest.param(
        r'\show\undefinedqq\message{[ok]}',
        [r'[ok]', r'> \undefinedqq=undefined.'],
        id='show-undefined',
    ),
    pytest.param(
        r'\showthe\hsize\message{[ok]}',
        [r'[ok]', r'> 469.75499pt.'],
        id='showthe-hsize',
    ),
    pytest.param(
        r'\toks0={a\relax b}\showthe\toks0\message{[ok]}',
        [r'[ok]', r'> a\relax b.'],
        id='showthe-toks',
    ),
    pytest.param(
        r'\setbox0\hbox{\show\relax}\message{[ok]}',
        [r'[ok]', r'> \relax=\relax.'],
        id='show-in-hbox',
    ),
    pytest.param(
        r'$\showthe\count0$\message{[ok]}',
        [r'[ok]', r'> 1.'],
        id='show-in-math',
    ),
    pytest.param(
        r'\let\cnt=\count \count5=7 \showthe\cnt5\message{[ok]}',
        [r'[ok]', r'> 7.'],
        id='show-alias',
    ),
    pytest.param(
        r'\def\:{\let\sptok= }\: \show\sptok\message{[ok]}',
        [r'[ok]', r'> \sptok=blank space  .'],
        id='show-space',
    ),
    pytest.param(
        r'\show\bgroup\message{[ok]}',
        [r'[ok]', r'> \bgroup=begin-group character {.'],
        id='show-brace',
    ),
    pytest.param(
        r'\edef\x{\show\relax}\message{[\meaning\x]}',
        [r'[macro:->\show \relax ]'],
        id='show-edef',
    ),
]

_TEX291 = [
    pytest.param(
        r'\message{[\expandafter\meaning\space]}',
        [r'[blank space  ]'],
        id='meaning-space',
    ),
    pytest.param(
        r'\def\:{\let\sptok= }\: \message{[\meaning\sptok]}',
        [r'[blank space  ]'],
        id='meaning-sptok',
    ),
    pytest.param(
        r'\message{[\meaning\bgroup/\meaning\egroup]}',
        [r'[begin-group character {/end-group character }]'],
        id='meaning-bgroup',
    ),
    pytest.param(
        r'\message{[\meaning$/\meaning&/\meaning^/\meaning_]}',
        [r'[math shift character $/alignment tab character &/superscript character ^/subscript character _]'],
        id='meaning-chars',
    ),
    pytest.param(
        r'\let\h=# \message{[\meaning\h]}',
        [r'[macro parameter character #]'],
        id='meaning-hash',
    ),
]

_TEX289 = [
    pytest.param(
        r'\message{[\meaning~]}',
        [r'[macro:->\penalty \@M \ ]'],
        id='meaning-tie',
    ),
    pytest.param(
        r'\def\a{\penalty \@M \ x\par}\message{[\meaning\a]}',
        [r'[macro:->\penalty \@M \ x\par ]'],
        id='meaning-penalty',
    ),
    pytest.param(
        r'\let\x=\relax \edef\r{\x}\message{[\meaning\r]}',
        [r'[macro:->\x ]'],
        id='meaning-edef-relax',
    ),
    pytest.param(
        r'\def\a{\b c}\message{[\meaning\a]}',
        [r'[macro:->\b c]'],
        id='meaning-b-c',
    ),
    pytest.param(
        r'\edef\a{\leavevmode}\message{[a=\meaning\a]}x',
        [r'[a=macro:->\unhbox \voidb@x ]'],
        id='meaning-leavevmode',
    ),
    pytest.param(
        r'\def\a#1#2{x#1y#2}\message{[\meaning\a]}',
        [r'[macro:#1#2->x#1y#2]'],
        id='meaning-params',
    ),
    pytest.param(
        r'\def\a#1.{<#1>}\message{[\meaning\a]}',
        [r'[macro:#1.-><#1>]'],
        id='meaning-delim',
    ),
    pytest.param(
        r'\long\def\a{x}\message{[\meaning\a]}',
        [r'[\long macro:->x]'],
        id='meaning-long',
    ),
    pytest.param(
        r'\def\a{\x\1\%}\message{[\meaning\a]}',
        [r'[macro:->\x \1\%]'],
        id='meaning-single-letter-cs',
    ),
    pytest.param(
        r'\def\a{\def\b##1{##1}}\message{[\meaning\a]}',
        [r'[macro:->\def \b ##1{##1}]'],
        id='meaning-hashhash',
    ),
    pytest.param(
        r'\def\a{\b c}{\escapechar=`! \message{[\meaning\a]}}',
        [r'[macro:->!b c]'],
        id='meaning-escapechar',
    ),
    pytest.param(
        r'\def\a{\b c}{\escapechar=-1 \message{[\meaning\a]}}',
        [r'[macro:->b c]'],
        id='meaning-escape-neg',
    ),
    pytest.param(
        r'\message{[\relax]}',
        [r'[\relax ]'],
        id='message-relax',
    ),
    pytest.param(
        r'\message{[\noexpand\foo\noexpand\x a]}',
        [r'[\foo \x a]'],
        id='message-cs-seq',
    ),
    pytest.param(
        r'\toks0={#}\message{[\the\toks0]}',
        [r'[##]'],
        id='message-hash',
    ),
    pytest.param(
        r'\immediate\write16{[\noexpand\foo b]}',
        [r'[\foo b]'],
        id='write-relax',
    ),
    pytest.param(
        r'\def\a{~x}\message{[\meaning\a]}',
        [r'[macro:->~x]'],
        id='meaning-active-in-body',
    ),
    pytest.param(
        r'\def\a{\b c}\setbox0\hbox{\message{[\meaning\a]}}',
        [r'[macro:->\b c]'],
        id='meaning-hbox-ctx',
    ),
]


@pytest.mark.parametrize(("body", "miktex"), _TEX290)
def test_conditionals_and_the_read_meanings(body: str, miktex: list[str]) -> None:
    """: §506 operands and ``\\the``/scanner aliases, in several modes."""
    assert _log(body) == miktex


@pytest.mark.parametrize(("body", "miktex"), _TEX292)
def test_let_skips_an_implicit_space(body: str, miktex: list[str]) -> None:
    """: both skip loops of ``\\let`` test ``cur_cmd = spacer``."""
    assert _log(body) == miktex


@pytest.mark.parametrize(("body", "miktex"), _TEX288)
def test_futurelet_is_a_let_assignment(body: str, miktex: list[str]) -> None:
    """: grouping, ``\\global``, ``\\afterassignment``, active target."""
    assert _log(body) == miktex


@pytest.mark.parametrize(("body", "miktex"), _TEX285)
def test_show_and_showthe_log_and_continue(body: str, miktex: list[str]) -> None:
    """: the ``> …`` text of the log, and the ``[ok]`` after it."""
    assert _log(body) == miktex


@pytest.mark.parametrize(("body", "miktex"), _TEX291)
def test_meaning_of_a_character_names_its_category(body: str, miktex: list[str]) -> None:
    """: §298 ``print_cmd_chr`` for character tokens."""
    assert _log(body) == miktex


@pytest.mark.parametrize(("body", "miktex"), _TEX289)
def test_token_list_text(body: str, miktex: list[str]) -> None:
    """: §262/§294 spacing, parameters and escape character."""
    assert _log(body) == miktex


@pytest.mark.parametrize(("body", "miktex"), [
    (r"\expandafter\def\csname\endcsname{X}\def\saved{\csname\endcsname}"
     r"\message{[\meaning\saved/\expandafter\string\csname\endcsname]}",
     ["[macro:->\\csname \\endcsname /\\csname\\endcsname]"]),
    (r"\escapechar=`\! \message{[\expandafter\string\csname\endcsname]}", ["[!csname!endcsname]"]),
    (r"\escapechar=-1 \message{[\expandafter\string\csname\endcsname]}", ["[csnameendcsname]"]),
    (r"\edef\x{\expandafter\string\csname\endcsname}\message{[\meaning\x]}",
     ["[macro:->\\csname\\endcsname]"]),
    # control: a font selector still prints its identifier
    (r"\message{[\expandafter\string\the\font]}", ["[\\tenrm]"]),
])
def test_string_of_the_null_control_sequence(body: str, miktex: list[str]) -> None:
    """: §263 ``sprint_cs`` prints ``null_cs`` as ``\\csname\\endcsname``.

    MiKTeX 24.4 plain, measured 2026-10-29.
    """
    assert _log(body) == miktex


def _bare(text: str = "") -> Expander:
    reader = InputReader(StringInputSource(text))
    catcodes = CatcodeTable()
    return Expander(reader, Tokenizer(reader, catcodes), catcodes)


class TestTokenListText:
    """Unit tests of :meth:`Expander.token_list_text` (§262 ``print_cs``)."""

    def test_control_word_is_followed_by_a_space(self) -> None:
        tokens = [ControlSequenceToken("b"), CharToken("c", Catcode.LETTER)]
        assert _bare().token_list_text(tokens) == "\\b c"

    def test_control_symbol_of_a_non_letter_is_not(self) -> None:
        tokens = [ControlSequenceToken("%"), ControlSequenceToken(" "), CharToken("x", Catcode.LETTER)]
        assert _bare().token_list_text(tokens) == "\\%\\ x"

    def test_single_letter_follows_the_current_catcode(self) -> None:
        expander = _bare()
        expander._catcodes.set("@", Catcode.LETTER)
        tokens = [ControlSequenceToken("@"), CharToken("x", Catcode.LETTER)]
        assert expander.token_list_text(tokens) == "\\@ x"

    def test_parameter_character_doubles_and_numbers_print_with_hash(self) -> None:
        tokens = [CharToken("#", Catcode.PARAMETER), 1, CharToken("x", Catcode.LETTER)]
        assert _bare().token_list_text(tokens) == "###1x"

    def test_empty_name_prints_csname_endcsname(self) -> None:
        assert _bare().token_list_text([ControlSequenceToken("")]) == "\\csname\\endcsname "


class TestPrimitiveToken:
    """Unit tests of :meth:`Expander.primitive_token` ( D3 aliases)."""

    def test_alias_of_a_primitive_becomes_its_reference(self) -> None:
        expander = _bare()
        expander.define("wdd", PrimitiveMeaning("wd"))
        assert expander.primitive_token(ControlSequenceToken("wdd")) == PrimitiveRefToken("wd")

    def test_other_tokens_are_unchanged(self) -> None:
        expander = _bare(r"\def\m{x}")
        list(expander)
        letter = CharToken("a", Catcode.LETTER)
        assert expander.primitive_token(letter) is letter
        assert expander.primitive_token(ControlSequenceToken("m")) == ControlSequenceToken("m")
