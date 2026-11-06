r"""``\csname`` of an undefined name defines it as ``\relax`` (TeX §372) —.

Every expected line is MiKTeX 24.4 plain ``\message`` output of the same input.
"""
from __future__ import annotations

import pytest

from tests.test_expansion import cs_names, expand
from tests.test_expansion_ifx import _plain_messages

_WIDTH = r"\dimen0=\wd0 \message{[\the\dimen0]}"
_IS_RELAX = r"\ifx\zzq\relax T\else F\fi"


class TestUndefinedNameBecomesRelax:
    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            (r"\csname zzq\endcsname\message{[ok]}", ["[ok]"]),
            (r"\csname zzq\endcsname\message{[\meaning\zzq]}", [r"[\relax]"]),
            (r"\count1=7\csname zzq\endcsname\message{[\the\count1]}", ["[7]"]),
            (r"x\csname zzq\endcsname y\par\message{[\meaning\zzq]}", [r"[\relax]"]),
            (
                r"\expandafter\ifx\csname zzr\endcsname\relax\message{[T]}\fi"
                r"\message{[\meaning\zzr]}",
                ["[T]", r"[\relax]"],
            ),
            (
                r"\expandafter\let\expandafter\x\csname zzs\endcsname"
                r"\message{[\meaning\x][\meaning\zzs]}",
                [r"[\relax][\relax]"],
            ),
        ],
        ids=["executed", "meaning", "count-assignment", "paragraph", "ifx", "let"],
    )
    def test_matches_miktex(self, body: str, expected: list[str]) -> None:
        assert _plain_messages(body) == expected

    def test_in_hbox(self) -> None:
        assert _plain_messages(r"\setbox0\hbox{\csname zzq\endcsname x}" + _WIDTH) == ["[5.2778pt]"]

    def test_defined_names_keep_their_meaning(self) -> None:
        assert _plain_messages(
            r"\def\zzu{Q}\csname zzu\endcsname"
            r"{\csname par\endcsname}\message{[\meaning\zzu][\meaning\par]}"
        ) == [r"[macro:->Q][\par]"]

    def test_newif_builds_its_switches(self) -> None:
        # \newif builds \footrue/\foofalse through \csname inside \expandafter chains
        assert _plain_messages(r"\newif\iffoo \footrue\message{[\iffoo T\else F\fi]}") == ["[T]"]


class TestRelaxMeaningIsLocal:
    """``eq_define``: the ``\\relax`` meaning ends with the group (§372)."""

    def test_group_ends_the_definition(self) -> None:
        assert _plain_messages(
            r"{\csname zzq\endcsname\message{[" + _IS_RELAX + "]}}"
            r"\message{[" + _IS_RELAX + r"][\ifx\zzq\undefinedqq T\else F\fi]}"
        ) == ["[T]", "[F][T]"]

    def test_local_redefinition_is_undone_too(self) -> None:
        assert _plain_messages(
            r"{\csname zzq\endcsname\def\zzq{A}}\message{[\ifx\zzq\undefinedqq T\else F\fi]}"
        ) == ["[T]"]

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            (r"{\expandafter\gdef\csname zzx\endcsname{Y}}\message{[\meaning\zzx]}", "[macro:->Y]"),
            (r"{\expandafter\xdef\csname zzy\endcsname{Y}}\message{[\meaning\zzy]}", "[macro:->Y]"),
            (
                r"{\global\expandafter\let\csname zzw\endcsname\relax}\message{[\meaning\zzw]}",
                r"[\relax]",
            ),
            (r"{{\csname zzq\endcsname\global\let\zzq=\par}}\message{[\meaning\zzq]}", r"[\par]"),
            (r"{\csname zzq\endcsname\gdef\zzq{G}\def\zzq{L}}\message{[\meaning\zzq]}", "[macro:->G]"),
        ],
        ids=["gdef", "xdef", "global-let", "nested-global", "local-global-local"],
    )
    def test_a_later_global_assignment_survives(self, body: str, expected: str) -> None:
        assert _plain_messages(body) == [expected]


class TestGlobalMacroAssignmentIsRetained:
    """TeX §283 keeps a global value over a local save of the same group."""

    @pytest.mark.parametrize(
        "body",
        [
            r"{\def\a{1}\gdef\a{2}}\message{[\meaning\a]}",
            r"{\def\a{1}{\gdef\a{2}}}\message{[\meaning\a]}",
            r"{\def\a{1}\gdef\a{2}\def\a{3}}\message{[\meaning\a]}",
        ],
        ids=["same-group", "nested", "local-again"],
    )
    def test_matches_miktex(self, body: str) -> None:
        assert _plain_messages(body) == ["[macro:->2]"]


def test_bare_expander_keeps_the_name() -> None:
    # Without an interpreter no name is known to be undefined.
    assert cs_names(expand(r"\csname hello\endcsname")) == ["hello"]


class TestFullExpansionKeepsUnexpandableAliases:
    r"""``\edef``, ``\message`` and ``\write`` keep an alias of an unexpandable meaning (§478).

    , fixed in: a name ``\csname`` has made ``\relax`` stays
    that name.  A control word is printed with a space after it (§262,
    ); the expected text is MiKTeX 24.4 output.
    """

    def test_name_built_before_its_definition(self) -> None:
        assert _plain_messages(
            r"\xdef\x{\csname zzz\endcsname}\expandafter\def\csname zzz\endcsname{Q}"
            r"\setbox0\hbox{\x}" + _WIDTH
        ) == ["[7.7778pt]"]

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            (r"\message{[\csname zzz\endcsname]}", r"[\zzz ]"),
            (r"\immediate\write16{[\csname zzz\endcsname]}", r"[\zzz ]"),
            (r"\edef\x{\noexpand\foo\csname zzz\endcsname}\message{[\meaning\x]}", r"[macro:->\foo \zzz ]"),
            (r"\let\y=\relax \message{[\y]}", r"[\y ]"),
            (r"\let\y=a \edef\x{\y b}\message{[\meaning\x]}", r"[macro:->\y b]"),
            (r"\edef\x{\bgroup x\egroup}\message{[\meaning\x]}", r"[macro:->\bgroup x\egroup ]"),
        ],
        ids=["message", "write", "edef-noexpand", "message-let-relax", "edef-let-char", "edef-bgroup"],
    )
    def test_alias_text(self, body: str, expected: str) -> None:
        assert _plain_messages(body) == [expected]

    def test_expandable_alias_still_expands(self) -> None:
        assert _plain_messages(
            r"\let\ea=\expandafter \def\b{B}\edef\x{\ea\noexpand\b}\message{[\meaning\x]}"
        ) == ["[macro:->B]"]

    @pytest.mark.parametrize(
        ("body", "width"),
        [
            (r"\edef\x{\bgroup x\egroup}\setbox0\hbox{\x}", "[5.2778pt]"),
            (r"\let\y=\hfil \edef\x{\hbox to 20pt{\y x}}\setbox0\x", "[20.0pt]"),
            (r"\edef\x{\csname zzz\endcsname y}\setbox0\hbox{\x}", "[5.2778pt]"),
        ],
        ids=["bgroup", "hfil", "csname-relax"],
    )
    def test_stored_alias_executes_as_its_target(self, body: str, width: str) -> None:
        assert _plain_messages(body + _WIDTH) == [width]


def test_name_let_to_itself_while_undefined_stays_undefined() -> None:
    assert _plain_messages(
        r"\let\zzx=\zzx \message{[\meaning\zzx][\ifx\zzx\undefinedqq T\else F\fi]}"
    ) == ["[undefined][T]"]


class TestFullExpansionResolvesAliasesItReads:
    r"""Inside ``\edef``/``\message`` only output tokens keep their alias (second review).

    ``\if``/``\ifcat`` operands, ``\csname`` and the number scanner look at the
    meaning, as in TeX; every expected line is MiKTeX 24.4 plain output.
    """

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            (r"\let\a=a \message{[\if\a aT\else F\fi][\ifcat\a bT\else F\fi]}", ["[T][T]"]),
            (r"\let\sp=^ \edef\x{\if\sp^T\else F\fi}\message{[\meaning\x]}", ["[macro:->T]"]),
            (r"\let\b=\bgroup \edef\x{\ifcat\b\bgroup T\else F\fi}\message{[\meaning\x]}", ["[macro:->T]"]),
            (r"\catcode`\!=13 \let!=a \edef\x{\if!aT\else F\fi}\message{[\meaning\x]}", ["[macro:->T]"]),
            (r"\let\ec=\endcsname \def\zq{Q}\message{[\csname zq\ec]}", ["[Q]"]),
            (r"\let\ec=\endcsname \def\zq{Q}\edef\x{\csname zq\ec}\message{[\meaning\x]}", ["[macro:->Q]"]),
        ],
        ids=["if-ifcat-let-char", "if-implicit-sup", "ifcat-implicit-bgroup", "if-active-let",
             "csname-implicit-endcsname-message", "csname-implicit-endcsname-edef"],
    )
    def test_matches_miktex(self, body: str, expected: list[str]) -> None:
        assert _plain_messages(body) == expected

    def test_width_of_a_conditional_in_edef(self) -> None:
        assert _plain_messages(
            r"\let\a=a \edef\x{\if\a aT\else F\fi}\setbox0\hbox{\x}" + _WIDTH
        ) == ["[7.22223pt]"]

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            (r"\def\:{\let\sptok= }\: \message{[\number 12\sptok x]}", "[12x]"),
            (r"\def\:{\let\sptok= }\: \edef\x{\number 12\sptok x}\message{[\meaning\x]}", "[macro:->12x]"),
            (r"\catcode`\!=13 \def\:{\let!= }\: \message{[\number 12!x]}", "[12x]"),
        ],
        ids=["message", "edef", "active-char"],
    )
    def test_number_absorbs_an_implicit_space(self, body: str, expected: str) -> None:
        assert _plain_messages(body) == [expected]
