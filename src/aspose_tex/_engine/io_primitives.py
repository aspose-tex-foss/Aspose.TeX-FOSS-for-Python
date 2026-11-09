r"""TeX I/O primitives.

This module houses the I/O surface: message logging, write-stream dispatch,
the file-stream commands, ``\ifeof``, ``\immediate``, and ``\dump``.  File
streams are not implemented: the file-stream commands parse their operands and
raise ``NotImplementedError``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken, Token
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
    from aspose_tex._engine.expansion import Expander
    from aspose_tex._engine.interpreter import TeXInterpreter

_LOG: Final = logging.getLogger("aspose_tex")
_FILE_STREAM_MESSAGE: Final = "is not supported: file streams are not implemented"


def exec_message(interp: TeXInterpreter) -> None:
    r"""Execute ``\message{<balanced text>}``."""
    text = _read_balanced_text(interp._expander)
    _LOG.info(text)
    interp._messages.append(text)


def exec_write(interp: TeXInterpreter, *, immediate: bool = False) -> None:
    r"""Execute ``\write<n>{<balanced text>}``.

    The ``immediate`` flag is accepted for compatibility;
    it has no observable effect.
    """
    del immediate
    stream = _read_stream_number(interp, minimum=-1, maximum=16)
    text = _read_balanced_text(interp._expander)
    if stream == -1:
        _LOG.info(text)
        return
    if stream == 16:
        _LOG.info(text)
        interp._messages.append(text)
        return
    raise NotImplementedError(
        f"\\write to stream {stream} is not supported: file streams are not implemented"
    )


def exec_errmessage(interp: TeXInterpreter) -> None:
    r"""Execute ``\errmessage{<text>}`` in batch-mode style."""
    text = _read_balanced_text(interp._expander)
    message = f"! {text}"
    log_line = message
    help_text = _read_errhelp(interp)
    if help_text:
        log_line = f"{log_line}\nhelp: {help_text}"
    _LOG.warning(log_line)
    interp._messages.append(message)


def exec_show(interp: TeXInterpreter) -> None:
    r"""Execute ``\show<token>``: log the token's meaning and go on (§1294).

    In batch and nonstop mode TeX writes ``> \x=macro:`` and ``->X.`` and
    continues; the text goes to the log and to the job messages.
    """
    tok = interp._expander._next_raw()
    if tok is None:
        raise EngineError("\\show: missing token at end of input")
    _report_show(interp, interp._expander.show_text(tok))


def exec_showthe(interp: TeXInterpreter) -> None:
    r"""Execute ``\showthe<internal quantity>``: log what ``\the`` gives (§1297).

    The value is printed as a token list, as ``\message`` prints it:
    ``\showthe\count0`` logs ``> 1.``.
    """
    expander = interp._expander
    _report_show(interp, f"> {expander.token_list_text(expander.the_tokens())}.")


def _report_show(interp: TeXInterpreter, text: str) -> None:
    _LOG.info(text)
    interp._messages.append(text)


def exec_immediate(interp: TeXInterpreter) -> None:
    r"""Execute the ``\immediate`` prefix."""
    tok = interp._next_token()
    if not isinstance(tok, ControlSequenceToken):
        raise EngineError(f"\\immediate: control sequence expected, got {tok!r}")
    if tok.name == "write":
        exec_write(interp, immediate=True)
        return
    if tok.name == "openout":
        exec_openout(interp, immediate=True)
        return
    if tok.name == "closeout":
        exec_closeout(interp, immediate=True)
        return
    raise EngineError(f"\\immediate cannot prefix \\{interp._expander._diagnostic_cs_name(tok)}")


def exec_openin(interp: TeXInterpreter) -> None:
    r"""Parse ``\openin<n>=<filename>`` then raise ``NotImplementedError``."""
    stream = _read_stream_number(interp)
    _eat_optional_equals(interp._expander)
    _read_filename(interp._expander)
    _raise_deferred("openin", stream)


def exec_openout(interp: TeXInterpreter, *, immediate: bool = False) -> None:
    r"""Parse ``\openout<n>=<filename>`` then raise ``NotImplementedError``."""
    del immediate
    stream = _read_stream_number(interp)
    _eat_optional_equals(interp._expander)
    _read_filename(interp._expander)
    _raise_deferred("openout", stream)


def exec_closein(interp: TeXInterpreter) -> None:
    r"""Parse ``\closein<n>`` then raise ``NotImplementedError``."""
    stream = _read_stream_number(interp)
    _raise_deferred("closein", stream)


def exec_closeout(interp: TeXInterpreter, *, immediate: bool = False) -> None:
    r"""Parse ``\closeout<n>`` then raise ``NotImplementedError``."""
    del immediate
    stream = _read_stream_number(interp)
    _raise_deferred("closeout", stream)


def exec_read(interp: TeXInterpreter) -> None:
    r"""Parse ``\read<n> to <CS>`` then raise ``NotImplementedError``."""
    stream = _read_stream_number(interp)
    from aspose_tex._engine.dimparser import _scan_keyword

    if not _scan_keyword(interp._expander, "to"):
        raise EngineError("\\read: expected 'to'")
    tok = interp._expander._next_raw()
    while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
        tok = interp._expander._next_raw()
    if not isinstance(tok, ControlSequenceToken):
        raise EngineError(f"\\read: control sequence expected, got {tok!r}")
    _raise_deferred("read", stream)


def exec_ifeof(interp: TeXInterpreter) -> bool:
    r"""Execute ``\ifeof<n>`` as always false: file streams are not implemented."""
    _read_stream_number(interp)
    return False


def exec_dump(interp: TeXInterpreter) -> None:
    r"""Terminate format loading and inject ``\everyjob`` tokens."""
    if not interp._is_loading_format:
        raise EngineError("\\dump only allowed during format load")
    interp._is_loading_format = False
    interp._reader.pop()
    everyjob = interp._named_params.lookup("everyjob")
    if everyjob is not None:
        tokens = interp._named_params.dispatch_the(everyjob, interp._expander)
        if tokens:
            interp._expander.push_tokens(tokens)


def _format_tokens(toks: list[Token], expander: Expander) -> str:
    """Expand a balanced token list and stringify it for logs/messages."""
    return expander.token_list_text(expander._expand_fully(toks))


def _read_balanced_text(expander: Expander) -> str:
    expander._scan_left_brace("message text")
    return _format_tokens(expander._scan_balanced_group(), expander)


def _read_errhelp(interp: TeXInterpreter) -> str:
    entry = interp._named_params.lookup("errhelp")
    if entry is None:
        return ""
    return _format_tokens(
        interp._named_params.dispatch_the(entry, interp._expander),
        interp._expander,
    )


def _read_stream_number(
    interp: TeXInterpreter, *, minimum: int = 0, maximum: int = 15
) -> int:
    from aspose_tex._engine.dimparser import parse_integer

    stream = parse_integer(interp._expander)
    if not (minimum <= stream <= maximum):
        raise EngineError(f"stream number out of range: {stream}")
    return stream


def _eat_optional_equals(expander: Expander) -> None:
    from aspose_tex._engine.registers import _eat_optional_equals as eat

    eat(expander)


def _read_filename(expander: Expander) -> str:
    tok = expander._next_raw()
    while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
        tok = expander._next_raw()
    if tok is None:
        raise EngineError("filename expected")
    if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
        chars = [
            t.char for t in expander._scan_balanced_group()
            if isinstance(t, CharToken)
        ]
        if not chars:
            raise EngineError("filename expected")
        return "".join(chars)

    chars: list[str] = []
    while tok is not None:
        if isinstance(tok, CharToken) and tok.catcode in (
            Catcode.SPACE,
            Catcode.BEGIN_GROUP,
            Catcode.END_GROUP,
        ):
            break
        if isinstance(tok, CharToken):
            chars.append(tok.char)
        else:
            expander._stack.append(tok)
            break
        tok = expander._next_raw()
    if not chars:
        raise EngineError("filename expected")
    return "".join(chars)


def _raise_deferred(primitive: str, stream: int) -> None:
    raise NotImplementedError(f"\\{primitive} stream {stream} {_FILE_STREAM_MESSAGE}")
