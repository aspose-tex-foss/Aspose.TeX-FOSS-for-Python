r"""Tests for ``\patterns``/``\hyphenation`` and the bundled fast path (§2).

Expected messages and their order are MiKTeX 24.4 (``tex`` and ``tex -ini``,
nonstopmode, 2026-10-21) on the same sources.
"""
from __future__ import annotations

import logging
import warnings
from pathlib import Path

import pytest

from aspose_tex._engine import interpreter as interpreter_module
from aspose_tex._engine.hyphenation import HyphenationStore
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice

_INITEX_BRACES = "\\catcode`\\{=1 \\catcode`\\}=2 \\catcode`\\#=6\n"
_PLAIN_PROGRESS = (
    "Preloading the plain format: codes,", "registers,", "parameters,", "fonts,",
    "more fonts,", "macros,", "math definitions,", "output routines,", "hyphenation",
)


def _codes(word: str) -> tuple[int, ...]:
    return tuple(ord(c) for c in word)


def _run(source: str, load_format: bool | str = False, **kwargs) -> tuple[TeXInterpreter, list[str]]:
    messages: list[str] = []
    interp = TeXInterpreter(load_format=load_format, messages=messages, **kwargs)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(StringInputSource(source), DviDevice())
    return interp, [m for m in messages if m not in _PLAIN_PROGRESS]


@pytest.fixture
def fast_path_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    """Record every ``\\input`` interception as (file name, applied)."""
    calls: list[tuple[str, bool]] = []
    real = interpreter_module.try_bundled_hyphen

    def spy(interp: TeXInterpreter, path: Path) -> bool:
        applied = real(interp, path)
        calls.append((path.name, applied))
        return applied

    monkeypatch.setattr(interpreter_module, "try_bundled_hyphen", spy)
    return calls


@pytest.fixture(scope="module")
def plain_entries() -> tuple[dict, dict]:
    interp, _ = _run(r"\bye", "plain")
    store = interp._hyphenation
    return dict(store.patterns(0)), dict(store.exceptions(0))


# --- diagnostics (§961-§963, §935-§937) ---------------------------------------


def test_pattern_and_exception_diagnostics_recover_as_tex(caplog: pytest.LogCaptureFixture) -> None:
    source = _INITEX_BRACES + r"""\def\x{\message{AFTER}}
\afterassignment\x\patterns{a1b}\message{N1}
\patterns{a2b}\message{N2}
\patterns{a\relax b}\message{N4}
\hyphenation{a\relax b}\message{N6}
\hyphenation{a1b}\message{N7}
\afterassignment\x\global\patterns{c1c}\message{N8}
\patterns{.a1b}\lccode`\z=0 \patterns{z1a1b}\message{N9}
\end"""
    with caplog.at_level(logging.WARNING, logger="aspose_tex"):
        interp, messages = _run(source)
    assert messages == [
        "AFTER", "N1",
        "! Duplicate pattern.", "N2",
        "! Bad \\patterns.", "! Duplicate pattern.", "N4",  # \relax eats the space: item "ab"
        "! Improper \\hyphenation will be flushed.", "N6",
        "! Not a letter.", "N7",
        "AFTER", "N8",
        "! Nonletter.", "! Duplicate pattern.", "N9",  # the nonletter is stored as an edge
    ]
    patterns = interp._hyphenation.patterns(0)
    assert patterns[_codes("ab")] == (0, 0, 0)
    assert patterns[(0, 97, 98)] == (0, 1, 1, 0)
    assert patterns[_codes("cc")] == (0, 1, 0)
    assert dict(interp._hyphenation.exceptions(0)) == {_codes("ab"): frozenset()}
    assert "! Not a letter.\nhelp: Letters in \\hyphenation words must have \\lccode>0." in caplog.text
    assert "! Bad \\patterns.\nhelp: (See Appendix H.)" in caplog.text


def test_hyphenation_accepts_char_and_chardef_and_replaces_words() -> None:
    source = _INITEX_BRACES + (
        "\\chardef\\dash=`\\- \\let\\ee=e\n"
        "\\hyphenation{t\\ee a\\dash pot \\char`\\t\\char`\\-ab x}\n"
        "\\hyphenation{teap-ot}\\end"
    )
    interp, messages = _run(source)
    assert messages == []
    assert dict(interp._hyphenation.exceptions(0)) == {
        _codes("teapot"): frozenset({4}), _codes("tab"): frozenset({1}),
    }


def test_hyphenation_uses_the_current_language_and_lccode() -> None:
    source = _INITEX_BRACES + "\\language=300 \\hyphenation{Ab-c}\\language=7 \\hyphenation{ab-cd}\\end"
    store = _run(source)[0]._hyphenation
    # INITEX \lccode`A = `a; \language 300 counts as 0.
    assert dict(store.exceptions(0)) == {_codes("abc"): frozenset({2})}
    assert dict(store.exceptions(7)) == {_codes("abcd"): frozenset({2})}


def test_global_prefix_is_accepted_and_does_not_leak() -> None:
    source = _INITEX_BRACES + "\\global\\patterns{c1c}{\\count1=7 }\\message{\\the\\count1}\\end"
    interp, messages = _run(source)
    assert messages == ["0"]
    assert interp._hyphenation.patterns(0)[_codes("cc")] == (0, 1, 0)


# --- timing (FR-2, §2) -------------------------------------------------


def test_patterns_after_plain_flush_to_the_first_right_brace(plain_entries) -> None:
    # MiKTeX: the error, then "c" is typeset in the box (P3) and \afterassignment
    # does not fire (§1252 returns before `done`).
    source = (
        r"\setbox0\hbox{\patterns{a{b}c}\message{[\the\wd0]}"
        r"\def\x{\message{AFTER}}\afterassignment\x\patterns{a}\message{NEXT}\bye"
    )
    interp, messages = _run(source, "plain")
    assert messages == [
        "! Patterns can be loaded only by INITEX.", "[4.44444pt]",
        "! Patterns can be loaded only by INITEX.", "NEXT",
    ]
    assert dict(interp._hyphenation.patterns(0)) == plain_entries[0]


def test_hyphenation_works_in_a_plain_document_under_another_language() -> None:
    source = r"\def\x{\message{AFTER}}\language=1 \afterassignment\x\hyphenation{tea-pot}\message{N}\bye"
    interp, messages = _run(source, "plain")
    assert messages == ["AFTER", "N"]
    store = interp._hyphenation
    assert store.hyphen_positions(1, _codes("teapot"), 2, 3) == (3,)
    assert store.patterns(1) == {}


def test_formatless_job_accepts_patterns_until_the_store_freezes(monkeypatch: pytest.MonkeyPatch) -> None:
    interp, messages = _run(_INITEX_BRACES + "\\patterns{a1b}\\end")
    assert messages == []
    assert interp._hyphenation.patterns(0) == {_codes("ab"): (0, 1, 0)}

    def frozen_store() -> HyphenationStore:
        store = HyphenationStore()
        store.freeze()
        return store

    monkeypatch.setattr(interpreter_module, "HyphenationStore", frozen_store)
    source = _INITEX_BRACES + (
        "\\def\\x{\\message{AFTER}}\\afterassignment\\x\\patterns{1c{d}e}\\message{N}"
        "\\hyphenation{ab-c}\\end"
    )
    interp, messages = _run(source)
    assert messages == ["! Too late for \\patterns.", "AFTER", "N"]
    assert interp._hyphenation.patterns(0) == {}
    assert dict(interp._hyphenation.exceptions(0)) == {_codes("abc"): frozenset({2})}


def test_patterns_are_accepted_while_a_format_loads(tmp_path: Path) -> None:
    (tmp_path / "pfmt.tex").write_text(_INITEX_BRACES + "\\patterns{x1y}\\dump\n", encoding="utf-8")
    interp, messages = _run(r"\patterns{q1r}\end", "pfmt", extra_format_paths=[tmp_path])
    assert messages == ["! Patterns can be loaded only by INITEX."]
    assert interp._hyphenation.patterns(0) == {_codes("xy"): (0, 1, 0)}


# --- bundled fast path (§2) -------------------------------------------


def test_plain_load_takes_the_fast_path(fast_path_calls, plain_entries) -> None:
    interp, _ = _run(r"\bye", "plain")
    assert fast_path_calls == [("hyphen.tex", True)]
    assert len(plain_entries[0]) == 4447 and len(plain_entries[1]) == 14
    # The file was not pushed: nothing of it is left on the reader.
    assert len(interp._reader._stack) <= 1


def test_token_path_load_equals_the_fast_path_load(fast_path_calls, plain_entries) -> None:
    interp, messages = _run(_INITEX_BRACES + "\\input hyphen \\end")
    assert fast_path_calls == [("hyphen.tex", False)]  # format-less: not the INITEX format phase
    assert messages == []
    store = interp._hyphenation
    assert (dict(store.patterns(0)), dict(store.exceptions(0))) == plain_entries


def test_other_files_are_not_intercepted(fast_path_calls, tmp_path: Path) -> None:
    (tmp_path / "hyphen2.tex").write_text("\\def\\foo{Z}", encoding="utf-8")
    (tmp_path / "f.tex").write_text(_INITEX_BRACES + "\\input hyphen2 \\dump\n", encoding="utf-8")
    interp, _ = _run(r"\end", "f", extra_format_paths=[tmp_path])
    assert fast_path_calls == [("hyphen2.tex", False)]
    assert "foo" in interp._expander.macros


@pytest.mark.parametrize(("setup", "load"), [
    ("", "\\input hyphen"),
    # 3: horizontal mode
    ("", "\\indent\\input hyphen \\par"),
    # 4: the language already has entries
    ("\\hyphenation{foo-bar}", "\\input hyphen"),
    # 5: catcodes
    ("\\catcode`\\.=11", "\\input hyphen"),
    # 6: lccodes
    ("\\lccode`\\q=`\\Q\\relax", "\\input hyphen"),
    # 7: a binding of \hyphenation, a pending \afterassignment or prefix
    ("\\let\\hyphenation=\\hyphenation", "\\input hyphen"),
    ("\\def\\x{}\\afterassignment\\x", "\\input hyphen"),
    ("", "\\global\\input hyphen"),
], ids=["ok", "hmode", "store", "catcode", "lccode", "binding", "afterassignment", "global"])
def test_each_violated_precondition_takes_the_token_path(
        fast_path_calls, plain_entries, tmp_path: Path, setup: str, load: str) -> None:
    (tmp_path / "hfmt.tex").write_text(f"{_INITEX_BRACES}{setup}\n{load}\n\\dump\n", encoding="utf-8")
    interp, messages = _run(r"\end", "hfmt", extra_format_paths=[tmp_path])
    assert fast_path_calls == [("hyphen.tex", not setup and load == "\\input hyphen")]
    assert messages == []
    patterns, exceptions = plain_entries
    store = interp._hyphenation
    assert len(store.patterns(0)) == len(patterns)
    if setup.startswith("\\lccode"):
        assert store.patterns(0) != patterns  # q is stored as Q
    else:
        assert store.patterns(0) == patterns
    expected = dict(exceptions)
    if "foo-bar" in setup:
        expected[_codes("foobar")] = frozenset({3})
    assert dict(store.exceptions(0)) == expected


def test_internal_vertical_mode_takes_the_fast_path(fast_path_calls, plain_entries, tmp_path: Path) -> None:
    (tmp_path / "vfmt.tex").write_text(f"{_INITEX_BRACES}\\setbox0\\vbox{{\\input hyphen }}\\dump\n",
                                       encoding="utf-8")
    interp, _ = _run(r"\end", "vfmt", extra_format_paths=[tmp_path])
    assert fast_path_calls == [("hyphen.tex", True)]
    assert dict(interp._hyphenation.patterns(0)) == plain_entries[0]


def test_input_inside_an_operand_scan_takes_the_token_path(
        fast_path_calls, plain_entries, tmp_path: Path) -> None:
    # The optional space after `\Q expands \input; TeX completes the \lccode
    # assignment before \patterns runs, so the token path stores q as Q.
    (tmp_path / "sfmt.tex").write_text(f"{_INITEX_BRACES}\\lccode`\\q=`\\Q\n\\input hyphen\n\\dump\n",
                                       encoding="utf-8")
    interp, _ = _run(r"\end", "sfmt", extra_format_paths=[tmp_path])
    assert fast_path_calls == []
    patterns = interp._hyphenation.patterns(0)
    assert len(patterns) == len(plain_entries[0])
    assert patterns != plain_entries[0]
    assert any(ord("Q") in key for key in patterns)
