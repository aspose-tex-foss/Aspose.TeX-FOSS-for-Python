r"""``\patterns`` and ``\hyphenation`` and the bundled fast path (§2).

Both commands are reached from the two routing sites of the expander (its
main loop and ``box_primitives._execute_accent_assignment``) when an
interpreter is attached.  Document errors are TeX's recoverable messages:
the ``! …`` line goes to the job messages and, with its help text, to the
``aspose_tex`` logger, and scanning goes on as tex.web recovers.

``try_bundled_hyphen`` is the expander's ``\input`` interceptor: when the
pinned Knuth ``hyphen.tex`` is read under conditions where token-level
execution would store exactly what ``parse_bundled_hyphen`` returns, the
store is filled from the memoised parse and the file is not pushed.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from aspose_tex._engine.box_primitives import _chardef_code
from aspose_tex._engine.dimparser import parse_integer
from aspose_tex._engine.hyphenation import (
    BUNDLED_HYPHEN_SHA256,
    MAX_LETTERS,
    LanguageWhatsit,
    PatternItemBuilder,
    norm_min,
    normalize_language,
    parse_bundled_hyphen,
)
from aspose_tex._engine.nodes import WhatsitNode
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken, PrimitiveRefToken, Token
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
    from aspose_tex._engine.expansion import Expander
    from aspose_tex._engine.interpreter import TeXInterpreter

_LOG: Final = logging.getLogger("aspose_tex")
_APPENDIX_H: Final = "(See Appendix H.)"
_NOT_A_LETTER_HELP: Final = (
    "Letters in \\hyphenation words must have \\lccode>0.\n"
    "Proceed; I'll ignore the character I just read."
)
_IMPROPER_HELP: Final = (
    "Hyphenation exceptions must contain only letters\n"
    "and hyphens. But continue; I'll forgive and forget."
)
_ILLEGAL_CASE_HELP: Final = (  # §1050 report_illegal_case
    "Sorry, but I'm not programmed to handle this case;\n"
    "I'll just pretend that you didn't ask for it.\n"
    "If you're in the wrong mode, you might be able to\n"
    "return to the right one by typing `I}' or `I$' or `I\\par'."
)
_MODE_NAMES: Final = {  # §211 print_mode, for the modes \setlanguage rejects
    "OUTER_VERTICAL": "vertical", "INTERNAL_VERTICAL": "internal vertical",
    "MATH": "math", "MATH_DISPLAY": "display math",
}
_BUNDLED_FILE_SIZE: Final = 27_860
# Precondition 5: the catcodes hyphen.tex is read with in plain.tex.
_BUNDLED_CATCODES: Final = (
    ("\\", Catcode.ESCAPE), ("{", Catcode.BEGIN_GROUP), ("}", Catcode.END_GROUP),
    ("%", Catcode.COMMENT), (" ", Catcode.SPACE), ("\r", Catcode.END_OF_LINE),
    *((chr(c), Catcode.LETTER) for c in range(ord("a"), ord("z") + 1)),
    *((c, Catcode.OTHER) for c in "0123456789.-"),
)
_BUNDLE_CACHE: dict[str, tuple] = {}


def patterns_allowed(interp: TeXInterpreter) -> Literal["ok", "initex", "too-late"]:
    r"""Classify a ``\patterns`` command by TeX's INITEX timing (FR-2).

    The INITEX phase is format loading or a job without a format; there the
    command works until the store is frozen.  A document that follows a
    loaded format is not INITEX.
    """
    if not (interp._is_loading_format or interp._load_format in (False, None)):
        return "initex"
    return "too-late" if interp._hyphenation.frozen else "ok"


def exec_patterns(interp: TeXInterpreter) -> None:
    r"""Execute ``\patterns{…}`` (§960-§965, §1252).

    Outside INITEX, TeX flushes unexpanded tokens up to the first right
    brace and returns without the ``\afterassignment`` token (§1252's
    ``return`` skips ``done``); MiKTeX shows the same.
    """
    expander = interp._expander
    allowed = patterns_allowed(interp)
    if allowed == "initex":
        _report(interp, "Patterns can be loaded only by INITEX")
        _flush_to_right_brace(expander)
        return
    if allowed == "too-late":
        _report(interp, "Too late for \\patterns",
                "All patterns must be given before typesetting begins.")
        expander._scan_left_brace("\\patterns")
        expander._scan_balanced_group()
    else:
        language = normalize_language(interp._get_named_int("language"))
        expander._scan_left_brace("\\patterns")
        _scan_patterns(interp, language)
    expander.fire_after_assignment()


def exec_hyphenation(interp: TeXInterpreter) -> None:
    r"""Execute ``\hyphenation{…}`` in any mode and phase (§934-§939)."""
    expander = interp._expander
    expander._scan_left_brace("\\hyphenation")
    language = normalize_language(interp._get_named_int("language"))
    store = interp._hyphenation
    lccode = interp._code_arrays.get_lccode
    word: list[int] = []
    positions: list[int] = []
    while True:
        tok = expander.get_x_token()
        if tok is None:
            raise EngineError("Unexpected end of input inside \\hyphenation")
        kind = _command_kind(expander, tok)
        if kind == "space" or kind == "right":
            if len(word) > 1:
                store.add_exception(language, tuple(word), frozenset(positions))
            if kind == "right":
                break
            word, positions = [], []
            continue
        code = _hyphenation_char(expander, tok, kind)
        if code is None:
            _report(interp, "Improper \\hyphenation will be flushed", _IMPROPER_HELP)
        elif code == ord("-"):
            if len(word) < MAX_LETTERS:
                positions.append(len(word))
        elif lccode(code) == 0:
            _report(interp, "Not a letter", _NOT_A_LETTER_HELP)
        elif len(word) < MAX_LETTERS:
            word.append(lccode(code))
    expander.fire_after_assignment()


def exec_setlanguage(interp: TeXInterpreter) -> None:
    r"""Execute ``\setlanguage<number>`` (§1377, §7).

    In horizontal or restricted horizontal mode the language whatsit is
    appended with the live minima and becomes the list's current language;
    ``\language`` itself is not changed (P5).  Elsewhere it is TeX's illegal
    case: the message, and the number is left in the input.
    """
    from aspose_tex._engine.interpreter import ModeKind

    mode = interp._mode_stack.current
    if mode not in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
        _report(interp, f"You can't use `\\setlanguage' in {_MODE_NAMES[mode.name]} mode",
                _ILLEGAL_CASE_HELP)
        return
    # §1377 new_whatsit precedes scan_int: \lastpenalty/\lastkern see
    # the new tail while the number is expanded and scanned.
    placeholder = language_whatsit(interp, 0)
    target = interp._par_list._nodes
    index = len(target)
    interp._append_to_hlist(placeholder)
    language = normalize_language(parse_integer(interp._expander))
    completed = language_whatsit(interp, language)
    target[index] = completed
    interp._par_list.current_language = language


def fix_language(interp: TeXInterpreter) -> None:
    r"""§1376 ``fix_language``: record a ``\language`` change before a character.

    Called for a character in unrestricted horizontal mode only (§1034).
    """
    language = normalize_language(interp._get_named_int("language"))
    par_list = interp._par_list
    if language != par_list.current_language:
        par_list.append(language_whatsit(interp, language))
        par_list.current_language = language


def language_whatsit(interp: TeXInterpreter, language: int) -> WhatsitNode:
    r"""A language whatsit for *language* with the live ``norm_min``'d minima."""
    return WhatsitNode(data=LanguageWhatsit(
        language=language,
        left_min=norm_min(interp._get_named_int("lefthyphenmin")),
        right_min=norm_min(interp._get_named_int("righthyphenmin")),
    ))


def try_bundled_hyphen(interp: TeXInterpreter, path: Path) -> bool:
    r"""Apply the pinned ``hyphen.tex`` without reading its tokens (§2).

    Returns ``True`` when the file's effect was applied, so the caller must
    not push it; ``False`` sends the file down the normal token path.  The
    cheap state checks run first, so an ordinary ``\input`` costs no read.
    """
    if not _bundled_state_ok(interp):
        return False
    try:
        if path.stat().st_size != _BUNDLED_FILE_SIZE:
            return False
        data = path.read_bytes()
    except OSError:
        return False
    digest = hashlib.sha256(data).hexdigest()
    if digest != BUNDLED_HYPHEN_SHA256:
        return False
    entries = _BUNDLE_CACHE.get(digest)
    if entries is None:
        entries = _BUNDLE_CACHE[digest] = parse_bundled_hyphen(data.decode("ascii"))
    patterns, exceptions = entries
    language = normalize_language(interp._get_named_int("language"))
    store = interp._hyphenation
    for letters, values in patterns:
        store.add_pattern(language, letters, values)
    for word, positions in exceptions:
        store.add_exception(language, word, positions)
    return True


def _bundled_state_ok(interp: TeXInterpreter) -> bool:
    """Preconditions 2-7 of §2 (precondition 1 is the file hash)."""
    from aspose_tex._engine.interpreter import ModeKind

    expander = interp._expander
    store = interp._hyphenation
    if not interp._is_loading_format or store.frozen:
        return False
    if interp._mode_stack.current not in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
        return False
    if expander._edef_mode or expander._operand_scan_depth:
        return False
    if not store.is_empty(normalize_language(interp._get_named_int("language"))):
        return False
    catcodes = interp._catcodes
    if any(catcodes.get(char) != catcode for char, catcode in _BUNDLED_CATCODES):
        return False
    if interp._get_named_int("endlinechar") != 13:
        return False
    lccode = interp._code_arrays.get_lccode
    if any(lccode(c) != c for c in range(ord("a"), ord("z") + 1)):
        return False
    bindings = expander._bindings
    for name in ("patterns", "hyphenation"):
        if name in expander._macros or (bindings is not None and bindings.binding_of(name) is not None):
            return False
    # A pending prefix or \afterassignment would act on the file's commands.
    group_stack = expander._group_stack
    return not (
        expander._after_assignment_token is not None
        or expander._long_pending or expander._outer_pending
        or (group_stack is not None and group_stack._global_pending)
    )


def _scan_patterns(interp: TeXInterpreter, language: int) -> None:
    """Read pattern items up to the closing brace (§961-§963)."""
    expander = interp._expander
    store = interp._hyphenation
    lccode = interp._code_arrays.get_lccode
    builder = PatternItemBuilder()
    while True:
        tok = expander.get_x_token()
        if tok is None:
            raise EngineError("Unexpected end of input inside \\patterns")
        kind = _command_kind(expander, tok)
        if kind == "char":
            code = ord(_meaning_char(expander, tok))
            if not builder.digit_sensed and ord("0") <= code <= ord("9"):
                builder.digit(code - ord("0"))
                continue
            if code == ord("."):
                code = 0
            else:
                code = lccode(code)
                # §962: the nonletter still enters the pattern, as code 0.
                if code == 0:
                    _report(interp, "Nonletter", _APPENDIX_H)
            builder.letter(code)
        elif kind == "space" or kind == "right":
            item = builder.finish()
            if item is not None and not store.add_pattern(language, *item):
                _report(interp, "Duplicate pattern", _APPENDIX_H)
            if kind == "right":
                return
            builder = PatternItemBuilder()
        else:
            _report(interp, "Bad \\patterns", _APPENDIX_H)


def _meaning_char(expander: Expander, tok: Token) -> str:
    """The character of a token whose :func:`_command_kind` is ``char``."""
    meaning = tok if isinstance(tok, CharToken) else expander._let_meaning(tok)
    return meaning.char  # type: ignore[union-attr]


def _command_kind(expander: Expander, tok: Token) -> str:
    """TeX's command class of *tok*: ``char``, ``space``, ``right`` or ``other``.

    A ``\\let`` alias of a character token has that token's class (§1221).
    """
    meaning = tok if isinstance(tok, CharToken) else expander._let_meaning(tok)
    if isinstance(meaning, CharToken):
        if meaning.catcode in (Catcode.LETTER, Catcode.OTHER):
            return "char"
        if meaning.catcode == Catcode.SPACE:
            return "space"
        if meaning.catcode == Catcode.END_GROUP:
            return "right"
    return "other"


def _hyphenation_char(expander: Expander, tok: Token, kind: str) -> int | None:
    r"""The character code of a letter, ``\chardef`` constant or ``\char`` (§935)."""
    if kind == "char":
        return ord(_meaning_char(expander, tok))
    if not isinstance(tok, ControlSequenceToken):
        return None
    if not isinstance(tok, PrimitiveRefToken):
        code = _chardef_code(expander, tok.name)
        if code is not None:
            return code
    if expander.primitive_token(tok).name == "char":
        code = parse_integer(expander)
        if not 0 <= code <= 255:
            raise EngineError(f"\\char: code {code} out of range 0-255")
        return code
    return None


def _flush_to_right_brace(expander: Expander) -> None:
    """Read unexpanded tokens up to and including the first right brace (§1252)."""
    while True:
        tok = expander._next_raw()
        if tok is None or _command_kind(expander, tok) == "right":
            return


def _report(interp: TeXInterpreter, text: str, help_text: str = "") -> None:
    message = f"! {text}."
    _LOG.warning(f"{message}\nhelp: {help_text}" if help_text else message)
    interp._messages.append(message)
