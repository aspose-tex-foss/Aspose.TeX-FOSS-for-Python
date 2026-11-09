r"""``\let`` primitive-meaning capture (alias self-cycle).

``\let`` stores its right-hand side as a by-name token, not a captured
primitive meaning.  ``\let\endline=\cr`` then ``\global\let\cr\endline`` (the
plain.tex ``\bordermatrix`` mechanism: plain.tex 511 + 1101) makes ``\cr`` a
by-name alias to the token ``\cr`` — a self-cycle that span ``_next_unexpandable``
forever before this fix.  C1 resolves a same-named alias to the
primitive (TeX copies the *equivalent*), breaking the cycle without masking a
genuine distinct-primitive alias or a macro alias.
"""
from __future__ import annotations

from aspose_tex._engine.expansion import Expander
from aspose_tex._input.catcode import CatcodeTable
from aspose_tex._input.reader import InputReader, StringInputSource
from aspose_tex._input.token import CharToken, ControlSequenceToken
from aspose_tex._input.tokenizer import Tokenizer


def _expander(src: str) -> Expander:
    reader = InputReader(StringInputSource(src))
    catcodes = CatcodeTable()
    return Expander(reader, Tokenizer(reader, catcodes), catcodes)


def _drain(exp: Expander, limit: int = 5000) -> list:
    """Pull up to *limit* unexpandable tokens; assert no runaway (no hang)."""
    out = []
    for _ in range(limit):
        tok = exp._next_unexpandable()
        if tok is None:
            return out
        out.append(tok)
    raise AssertionError("expander did not terminate — alias self-cycle (regression)")


class TestLetSelfCycle:
    def test_cr_endline_self_cycle_resolves_to_primitive(self) -> None:
        # The \bordermatrix pair, isolated: \let\endline=\cr ; \let\cr\endline.
        # A trailing \cr must resolve (no hang) to the unexpandable primitive.
        exp = _expander(r"\let\endline=\cr \let\cr\endline \cr X")
        toks = _drain(exp)
        # The \cr surfaces as an unexpandable ControlSequenceToken('cr'); the
        # interpreter's primitive registry would dispatch it.  X follows.
        names = [t.name for t in toks if isinstance(t, ControlSequenceToken)]
        assert "cr" in names
        assert any(isinstance(t, CharToken) and t.char == "X" for t in toks)

    def test_distinct_primitive_alias_unaffected(self) -> None:
        # \let\x\cr aliases to a DIFFERENT name → one-step resolve, then the
        # primitive \cr surfaces (meaning.name 'cr' != name 'x').
        exp = _expander(r"\let\x\cr \x Y")
        toks = _drain(exp)
        names = [t.name for t in toks if isinstance(t, ControlSequenceToken)]
        assert "cr" in names
        assert any(isinstance(t, CharToken) and t.char == "Y" for t in toks)

    def test_macro_alias_unaffected(self) -> None:
        # A \let alias to a macro is expanded, not short-circuited.
        exp = _expander(r"\def\foo{Z}\let\bar\foo \bar")
        toks = _drain(exp)
        assert any(isinstance(t, CharToken) and t.char == "Z" for t in toks)
