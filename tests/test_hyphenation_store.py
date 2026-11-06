"""Tests for the hyphenation stores and Liang word hyphenation (§1)."""
from __future__ import annotations

import hashlib
import warnings
from pathlib import Path

import pytest

from aspose_tex._engine.hyphenation import (
    BUNDLED_HYPHEN_SHA256,
    HyphenationStore,
    PatternItemBuilder,
    norm_min,
    normalize_language,
    parse_bundled_hyphen,
)
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice

_HYPHEN_TEX = Path(__file__).resolve().parents[1] / "src" / "aspose_tex" / "data" / "format" / "hyphen.tex"


def _codes(word: str) -> tuple[int, ...]:
    return tuple(ord(c) for c in word)


def _pattern(text: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    builder = PatternItemBuilder()
    for char in text:
        if char.isdigit() and not builder.digit_sensed:
            builder.digit(int(char))
        else:
            builder.letter(0 if char == "." else ord(char))
    finished = builder.finish()
    assert finished is not None
    return finished


def _store(*patterns: str, language: int = 0) -> HyphenationStore:
    store = HyphenationStore()
    for text in patterns:
        store.add_pattern(language, *_pattern(text))
    return store


def _hyphenated(store: HyphenationStore, word: str, language: int = 0, left: int = 2, right: int = 3) -> str:
    positions = store.hyphen_positions(language, _codes(word.lower()), left, right)
    return "".join(c + ("-" if i + 1 in positions else "") for i, c in enumerate(word))


@pytest.mark.parametrize(("value", "expected"), [(-1, 0), (0, 0), (1, 1), (255, 255), (256, 0)])
def test_normalize_language(value: int, expected: int) -> None:
    assert normalize_language(value) == expected


@pytest.mark.parametrize(("value", "expected"), [(-5, 1), (0, 1), (2, 2), (62, 62), (63, 63), (99, 63)])
def test_norm_min(value: int, expected: int) -> None:
    assert norm_min(value) == expected


def test_builder_collects_letters_values_and_zeroes_edge_values() -> None:
    assert _pattern("a1b") == (_codes("ab"), (0, 1, 0))
    # §965: a value next to a word edge is dropped.
    assert _pattern("1.ab3.4") == ((0, 97, 98, 0), (0, 0, 0, 3, 0))


def test_builder_digit_after_digit_is_a_letter_and_empty_item_is_none() -> None:
    builder = PatternItemBuilder()
    builder.digit(1)
    assert builder.digit_sensed
    assert builder.finish() is None
    assert _pattern("a12") == ((97, ord("2")), (0, 1, 0))


def test_builder_caps_at_63_letters() -> None:
    builder = PatternItemBuilder()
    for _ in range(70):
        builder.letter(97)
    builder.digit(5)
    assert builder.length == 63
    letters, values = builder.finish()  # type: ignore[misc]
    assert len(letters) == 63 and values == (0,) * 64


def test_liang_takes_the_maximum_of_overlapping_patterns_and_odd_values_break() -> None:
    store = _store("a1b", "2bcd", "b3c", "c4d")
    # After a: max(a1b, 2bcd) = 2, even; after b: 3, odd; after c: 4, even.
    assert store.hyphen_positions(0, _codes("abcd"), 1, 1) == (2,)
    assert _store("a1b").hyphen_positions(0, _codes("abcd"), 1, 1) == (1,)


def test_liang_word_edges_match_only_at_the_ends() -> None:
    store = _store(".a1b", "b1c.")
    assert store.hyphen_positions(0, _codes("abc"), 1, 1) == (1, 2)
    assert store.hyphen_positions(0, _codes("xabcx"), 1, 1) == ()


def test_minima_clip_positions() -> None:
    store = _store("1a", "1b", "1c", "1d", "1e")
    word = _codes("xabcde")
    assert store.hyphen_positions(0, word, 1, 1) == (1, 2, 3, 4, 5)
    assert store.hyphen_positions(0, word, 2, 3) == (2, 3)
    assert store.hyphen_positions(0, word, 4, 3) == ()


def test_exception_wins_over_patterns_and_later_entry_replaces() -> None:
    store = _store("e1a")
    word = _codes("teapot")
    assert store.hyphen_positions(0, word, 1, 1) == (2,)
    store.add_exception(0, word, frozenset({3}))
    assert store.hyphen_positions(0, word, 1, 1) == (3,)
    store.add_exception(0, word, frozenset({1, 4}))
    assert store.hyphen_positions(0, word, 2, 2) == (4,)


def test_exception_works_in_a_language_without_patterns_and_languages_are_separate() -> None:
    store = _store("e1a")
    store.add_exception(1, _codes("teapot"), frozenset({3}))
    assert store.hyphen_positions(1, _codes("teapot"), 2, 3) == (3,)
    assert store.hyphen_positions(1, _codes("tea"), 1, 1) == ()
    assert store.hyphen_positions(2, _codes("teapot"), 1, 1) == ()
    assert store.is_empty(2) and not store.is_empty(1) and not store.is_empty(0)


def test_duplicate_is_reported_only_over_a_valued_entry_and_values_replace() -> None:
    store = HyphenationStore()
    assert store.add_pattern(0, *_pattern("m1n"))
    assert not store.add_pattern(0, *_pattern("m0n"))
    assert store.patterns(0)[_codes("mn")] == (0, 0, 0)
    assert store.add_pattern(0, *_pattern("m1n"))  # previous entry had no value


def test_store_rejects_malformed_entries() -> None:
    store = HyphenationStore()
    with pytest.raises(ValueError):
        store.add_pattern(0, (), (0,))
    with pytest.raises(ValueError):
        store.add_pattern(0, (97,), (0,))
    with pytest.raises(ValueError):
        store.add_pattern(256, (97,), (0, 0))
    with pytest.raises(ValueError):
        store.add_exception(0, (97,), frozenset())


def test_views_are_read_only_and_freeze_is_idempotent() -> None:
    store = _store("a1b")
    with pytest.raises(TypeError):
        store.patterns(0)[(1,)] = (0, 0)  # type: ignore[index]
    assert dict(store.exceptions(0)) == {}
    assert not store.frozen
    store.freeze()
    store.freeze()
    assert store.frozen


def test_parse_bundled_hyphen_reads_patterns_and_exceptions() -> None:
    patterns, exceptions = parse_bundled_hyphen("% c\n\\patterns{ % x\n.a1b\nc2\n}\n\\hyphenation{ %\nta-ble\nx\n}\n")
    assert patterns == (((0, 97, 98), (0, 0, 1, 0)), ((99,), (0, 2)))
    assert exceptions == ((_codes("table"), frozenset({2})),)
    with pytest.raises(ValueError):
        parse_bundled_hyphen("\\patterns{A1b}\\hyphenation{}")
    with pytest.raises(ValueError):
        parse_bundled_hyphen("\\hyphenation{}")


def test_bundled_file_is_pinned_and_parses_to_4447_patterns_and_14_exceptions() -> None:
    data = _HYPHEN_TEX.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert len(data) == 27_860 and b"\r" not in data
    assert digest == BUNDLED_HYPHEN_SHA256
    patterns, exceptions = parse_bundled_hyphen(data.decode("ascii"))
    assert len(patterns) == 4447 and len(exceptions) == 14


@pytest.fixture(scope="module")
def plain_store() -> HyphenationStore:
    interp = TeXInterpreter(load_format="plain")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(StringInputSource(r"\bye"), DviDevice())
    return interp._hyphenation


# word-level oracle: MiKTeX \showhyphens under plain (\lefthyphenmin=2,
# \righthyphenmin=3), letters only.
_ORACLE = [
    "Rep-re-sen-ta-tives", "in-ter-na-tional", "or-ga-ni-za-tions", "dis-cussed",
    "ex-traor-di-nar-ily", "com-pli-cated", "ad-min-is-tra-tive", "re-spon-si-bil-i-ties",
    "con-cern-ing", "en-vi-ron-men-tal", "con-sid-er-a-tions", "un-ques-tion-ably",
    "char-ac-ter-is-tic", "dif-fi-cul-ties", "af-flu-ent", "of-fices", "of-fice", "congress",
    "deriva-tive", "ethy-lene", "eu-ler", "chap-ters", "ta-ble", "project",
]


@pytest.mark.parametrize("expected", _ORACLE)
def test_plain_store_reproduces_the_miktex_oracle(plain_store: HyphenationStore, expected: str) -> None:
    assert _hyphenated(plain_store, expected.replace("-", "")) == expected


def test_plain_store_holds_language_zero_only(plain_store: HyphenationStore) -> None:
    assert len(plain_store.patterns(0)) == 4447
    assert len(plain_store.exceptions(0)) == 14
    assert plain_store.is_empty(1)
    assert not plain_store.frozen
