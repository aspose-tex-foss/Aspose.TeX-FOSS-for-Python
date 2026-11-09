r"""Hyphenation stores and Liang word hyphenation (§1).

TeX keeps, per ``\language``, a set of Liang patterns (``\patterns``) and a
list of exception words (``\hyphenation``).  This module holds both, answers
"where may this word break" for the hyphenation pass, and parses the pinned
Knuth ``hyphen.tex`` at character level for the bundled fast path
(``hyph_primitives.try_bundled_hyphen``).

Letters are always ``\lccode`` values: the scanners translate characters
when ``\patterns`` / ``\hyphenation`` run, and the pass translates a word's
characters before asking for positions.

Example::

    store = HyphenationStore()
    store.add_pattern(0, (ord("a"), ord("b")), (0, 1, 0))     # a1b
    store.hyphen_positions(0, [ord(c) for c in "xabx"], 1, 1)  # -> (2,)
"""
from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

# §935/§962: a pattern or an exception word holds at most 63 letters.
MAX_LETTERS: Final = 63

BUNDLED_HYPHEN_SHA256: Final[str] = (
    "2c18acdc04c1a066aeb1759905e7ca449f0616c314b5ed6aebe55b9d4a89b8d4"
)

_EMPTY: Final[Mapping] = MappingProxyType({})


@dataclasses.dataclass(frozen=True, slots=True)
class LanguageWhatsit:
    r"""Payload of TeX's language whatsit (§1341, §1362), in a ``WhatsitNode``.

    The hyphenation pass switches to this language and these minima for the
    words that follow it.

    Example::

        WhatsitNode(data=LanguageWhatsit(language=1, left_min=2, right_min=3))
    """

    language: int
    left_min: int
    right_min: int


def normalize_language(value: int) -> int:
    r"""Return the language TeX uses for ``\language`` = *value* (§1091, §960).

    Example::

        normalize_language(256)  # -> 0
    """
    return 0 if value <= 0 or value > 255 else value


def norm_min(value: int) -> int:
    r"""Clamp a ``\lefthyphenmin``/``\righthyphenmin`` value to 1..63 (§1091).

    Example::

        norm_min(0)  # -> 1
    """
    if value <= 0:
        return 1
    return MAX_LETTERS if value >= MAX_LETTERS else value


class PatternItemBuilder:
    r"""Collect one ``\patterns`` word: letters and inter-letter values (§962-§963).

    Example::

        item = PatternItemBuilder()
        item.letter(0); item.letter(ord("a")); item.digit(1); item.letter(ord("b"))
        item.finish()  # -> ((0, 97, 98), (0, 0, 1, 0))
    """

    __slots__ = ("_digit_sensed", "_letters", "_values")

    def __init__(self) -> None:
        self._letters: list[int] = []
        self._values: list[int] = [0]
        self._digit_sensed = False

    def letter(self, code: int) -> None:
        """Append a letter by its lccode, or 0 for the word edge ``.``."""
        if len(self._letters) < MAX_LETTERS:
            self._letters.append(code)
            self._values.append(0)
            self._digit_sensed = False

    def digit(self, value: int) -> None:
        """Set the value between the last letter and the next one."""
        if len(self._letters) < MAX_LETTERS:
            self._values[-1] = value
            self._digit_sensed = True

    @property
    def length(self) -> int:
        """Number of letters collected so far (TeX's ``k``)."""
        return len(self._letters)

    @property
    def digit_sensed(self) -> bool:
        """Whether the last item read was a digit, so a digit now is a letter."""
        return self._digit_sensed

    def finish(self) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
        """Return ``(letters, values)``, or ``None`` when no letter was read.

        A value next to a word edge is dropped (§965: ``hc[1]=0`` clears
        ``hyf[0]``, ``hc[k]=0`` clears ``hyf[k]``).
        """
        if not self._letters:
            return None
        values = list(self._values)
        if self._letters[0] == 0:
            values[0] = 0
        if self._letters[-1] == 0:
            values[-1] = 0
        return tuple(self._letters), tuple(values)


class HyphenationStore:
    r"""Per-language patterns and exceptions of one job (§1).

    Stores are global: TeX never saves or restores them at group ends.

    Example::

        store = HyphenationStore()
        store.add_exception(1, tuple(map(ord, "teapot")), frozenset({3}))
        store.hyphen_positions(1, tuple(map(ord, "teapot")), 2, 3)  # -> (3,)
    """

    __slots__ = ("_exceptions", "_frozen", "_max_length", "_patterns")

    def __init__(self) -> None:
        self._patterns: dict[int, dict[tuple[int, ...], tuple[int, ...]]] = {}
        self._max_length: dict[int, int] = {}
        self._exceptions: dict[int, dict[tuple[int, ...], frozenset[int]]] = {}
        self._frozen = False

    def add_pattern(self, language: int, letters: tuple[int, ...], values: tuple[int, ...]) -> bool:
        """Store a pattern; return ``False`` when it duplicates a valued one.

        The new values replace an existing entry either way (§963): TeX
        reports ``Duplicate pattern`` only when the earlier entry had a
        non-zero value.

        Raises:
            ValueError: If the language, the letter count or the value count
                is out of range (a programming error, not a document error).
        """
        _check_language(language)
        if not 1 <= len(letters) <= MAX_LETTERS or len(values) != len(letters) + 1:
            raise ValueError(f"malformed pattern: {len(letters)} letters, {len(values)} values")
        table = self._patterns.setdefault(language, {})
        previous = table.get(letters)
        table[letters] = values
        if len(letters) > self._max_length.get(language, 0):
            self._max_length[language] = len(letters)
        return previous is None or not any(previous)

    def add_exception(self, language: int, word: tuple[int, ...], positions: frozenset[int]) -> None:
        """Store an exception word; position *j* allows a break after letter *j*.

        A later entry for the same word replaces the earlier one (§940).

        Raises:
            ValueError: If the language or the word length is out of range.
        """
        _check_language(language)
        if not 2 <= len(word) <= MAX_LETTERS:
            raise ValueError(f"exception word of {len(word)} letters")
        self._exceptions.setdefault(language, {})[word] = positions

    def hyphen_positions(
        self, language: int, word: Sequence[int], left_min: int, right_min: int,
    ) -> tuple[int, ...]:
        """Return the sorted break positions of *word* (lccodes) in *language*.

        Position *j* lies between letters *j* and *j + 1*; only
        ``left_min <= j <= len(word) - right_min`` is returned (§902, §923).
        An exception of the language wins (§930-§931); otherwise Liang's
        patterns give the positions with an odd value.
        """
        n = len(word)
        low, high = left_min, n - right_min
        if low > high:
            return ()
        key = tuple(word)
        listed = self._exceptions.get(language, _EMPTY).get(key)
        if listed is not None:
            return tuple(sorted(j for j in listed if low <= j <= high))
        table = self._patterns.get(language)
        if not table:
            return ()
        padded = (0, *key, 0)
        size = len(padded)
        longest = self._max_length[language]
        hyf = [0] * (n + 1)
        for start in range(size):
            for end in range(start + 1, min(size, start + longest) + 1):
                values = table.get(padded[start:end])
                if values is None:
                    continue
                # values[i] sits before padded[start + i], i.e. after letter start + i - 1.
                for i, value in enumerate(values):
                    position = start + i - 1
                    if value > 0 and 0 <= position <= n and value > hyf[position]:
                        hyf[position] = value
        return tuple(j for j in range(low, high + 1) if hyf[j] & 1)

    def patterns(self, language: int) -> Mapping[tuple[int, ...], tuple[int, ...]]:
        """Read-only view of *language*'s patterns, letters -> values."""
        table = self._patterns.get(language)
        return _EMPTY if table is None else MappingProxyType(table)

    def exceptions(self, language: int) -> Mapping[tuple[int, ...], frozenset[int]]:
        """Read-only view of *language*'s exception words, word -> positions."""
        table = self._exceptions.get(language)
        return _EMPTY if table is None else MappingProxyType(table)

    def is_empty(self, language: int) -> bool:
        """Whether *language* has neither patterns nor exceptions."""
        return not self._patterns.get(language) and not self._exceptions.get(language)

    @property
    def frozen(self) -> bool:
        r"""Whether ``\patterns`` is too late (TeX's ``not trie_not_ready``)."""
        return self._frozen

    def freeze(self) -> None:
        """Close the pattern store for the rest of the job; idempotent."""
        self._frozen = True


def _check_language(language: int) -> None:
    if not 0 <= language <= 255:
        raise ValueError(f"language {language} out of range 0-255")


def parse_bundled_hyphen(text: str) -> tuple[
    tuple[tuple[tuple[int, ...], tuple[int, ...]], ...],
    tuple[tuple[tuple[int, ...], frozenset[int]], ...],
]:
    r"""Parse Knuth's ``hyphen.tex`` at character level (§1).

    Valid only under the fast-path preconditions of §2 (plain
    catcodes, ``\lccode`` of ``a``-``z`` the letter itself), where it yields
    exactly what token-level execution of the file stores: the patterns in
    file order, then the exception words.

    Raises:
        ValueError: If *text* is not shaped like the pinned file.

    Example::

        patterns, exceptions = parse_bundled_hyphen(r"\patterns{.a1b}\hyphenation{ta-ble}")
        patterns    # -> (((0, 97, 98), (0, 0, 1, 0)),)
        exceptions  # -> (((116, 97, 98, 108, 101), frozenset({2})),)
    """
    body = " ".join(line.split("%", 1)[0] for line in text.split("\n"))
    pattern_text, rest = _braced_after(body, "\\patterns")
    exception_text, rest = _braced_after(rest, "\\hyphenation")
    if rest.strip():
        raise ValueError("unexpected text after \\hyphenation")
    patterns = []
    for item in pattern_text.split():
        builder = PatternItemBuilder()
        for char in item:
            if char.isdigit() and not builder.digit_sensed:
                builder.digit(int(char))
            elif char == ".":
                builder.letter(0)
            else:
                builder.letter(_letter(char))
        finished = builder.finish()
        if finished is not None:
            patterns.append(finished)
    exceptions = []
    for item in exception_text.split():
        letters: list[int] = []
        positions: list[int] = []
        for char in item:
            if char == "-":
                positions.append(len(letters))
            else:
                letters.append(_letter(char))
        if len(letters) > 1:
            exceptions.append((tuple(letters), frozenset(positions)))
    return tuple(patterns), tuple(exceptions)


def _braced_after(text: str, command: str) -> tuple[str, str]:
    head, found, tail = text.partition(command + "{")
    if not found or head.strip():
        raise ValueError(f"expected {command}{{ in the bundled file")
    inner, closed, rest = tail.partition("}")
    if not closed or "{" in inner or "\\" in inner:
        raise ValueError(f"unbalanced {command} in the bundled file")
    return inner, rest


def _letter(char: str) -> int:
    if not "a" <= char <= "z":
        raise ValueError(f"unexpected character {char!r} in the bundled file")
    return ord(char)
