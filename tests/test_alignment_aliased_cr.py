"""by-meaning alignment-terminator classification.

`alignment._resolve_terminator_name` must classify a `\\let`-alias of
`\\cr` / `\\crcr` / `\\span` (e.g. plain.tex's `\\let\\endline=\\cr`) by its
underlying primitive meaning, not by control-sequence name.

NOTE (return scope): these unit tests cover the by-meaning *classification*
helper that landed.  The end-to-end `\\bordermatrix` /
`\\displaylines` integration is NOT covered here — that path needs a separate
architectural fix (math `$…$` cells inside an eager-`\\vbox` `\\halign` consume
the `&`/`\\cr` terminator); see the return note.
"""
from __future__ import annotations

import types

from aspose_tex._engine.alignment import (
    _TERM_CR,
    _TERM_CRCR,
    _TERM_SPAN,
    _resolve_terminator_name,
)
from aspose_tex._input.token import ControlSequenceToken


def _interp_with_macros(**aliases: str):
    """A minimal interpreter stand-in exposing only ``._expander._macros``.

    ``_resolve_terminator_name`` reads nothing else; the macro table is seeded
    with ``name -> ControlSequenceToken(target)`` entries (mirroring ``\\let``).
    """
    macros = {name: ControlSequenceToken(target) for name, target in aliases.items()}
    expander = types.SimpleNamespace(_macros=macros)
    return types.SimpleNamespace(_expander=expander)


# ---------------------------------------------------------------------------
# Literal-name fast path
# ---------------------------------------------------------------------------

def test_literal_primitives_resolve_to_themselves():
    interp = _interp_with_macros()
    assert _resolve_terminator_name("cr", interp) == _TERM_CR
    assert _resolve_terminator_name("crcr", interp) == _TERM_CRCR
    assert _resolve_terminator_name("span", interp) == _TERM_SPAN


# ---------------------------------------------------------------------------
# \let-alias resolution (the \endline=\cr case)
# ---------------------------------------------------------------------------

def test_let_alias_of_cr_resolves():
    interp = _interp_with_macros(endline="cr")
    assert _resolve_terminator_name("endline", interp) == _TERM_CR


def test_let_alias_of_crcr_resolves():
    interp = _interp_with_macros(myend="crcr")
    assert _resolve_terminator_name("myend", interp) == _TERM_CRCR


def test_let_alias_of_span_resolves():
    interp = _interp_with_macros(myspan="span")
    assert _resolve_terminator_name("myspan", interp) == _TERM_SPAN


def test_chained_alias_resolves():
    # \let\a=\cr ; \let\b=\a  →  \b resolves through two hops.
    interp = _interp_with_macros(a="cr", b="a")
    assert _resolve_terminator_name("b", interp) == _TERM_CR


# ---------------------------------------------------------------------------
# Non-terminator aliases and absent names
# ---------------------------------------------------------------------------

def test_non_terminator_alias_is_none():
    interp = _interp_with_macros(foo="relax")
    assert _resolve_terminator_name("foo", interp) is None


def test_absent_name_is_none():
    interp = _interp_with_macros()
    assert _resolve_terminator_name("notdefined", interp) is None


def test_cyclic_alias_chain_does_not_hang():
    # \let\a=\b ; \let\b=\a  →  a 2-cycle that must terminate, returning None.
    interp = _interp_with_macros(a="b", b="a")
    assert _resolve_terminator_name("a", interp) is None
