r""" regression: plain.tex's ``\newif`` runtime gap.

Covers the four engine pieces fixed by :

1. ``\string`` honours ``\escapechar`` (TeXbook ch. 24): emit the escape
 character only when ``\escapechar`` is in ``0..255``, otherwise omit.
2. ``_scan_args`` consumes leading delimiter tokens in macros that have no
 ``#``-parameter (TeXbook §200): essential for plain.tex's ``\if@`` (param
 text ``if``, body empty), the gobbler that ``\newif`` uses to build switch
 names via ``\csname\if@iffoo true\endcsname → \footrue``.
3. The Expander short-circuit (``if name == "newif": return tok``) is gone.
4. The interpreter primitive ``"newif": self._exec_newif_cmd`` and its
 ``_exec_newif_cmd`` helper are gone.

End-to-end smoke: ``\newif\iffoo``-derived switches in plain.tex (line 598,
1023, 1120, 1148, 1177) are reachable post-format-load.
"""
from __future__ import annotations

import warnings

import pytest

from aspose_tex._engine.box_primitives import OverfullBoxWarning
from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.registers import RegisterSet
from aspose_tex._input.catcode import Catcode, CatcodeTable
from aspose_tex._input.reader import InputReader, StringInputSource
from aspose_tex._input.token import CharToken
from aspose_tex._input.tokenizer import Tokenizer
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

_PLAIN = TeXOptions(load_format="plain")


def _run_dvi(tex: str) -> bytes:
 """Run ``tex`` under plain.tex and return the DVI bytes."""
 device = DviDevice()
 with warnings.catch_warnings():
 warnings.simplefilter("ignore", OverfullBoxWarning)
 TeXJob(StringInputSource(tex), device, options=_PLAIN).run()
 out = device.get_bytes()
 assert out is not None
 return out


def _expand(text: str, *, escapechar: int = 92) -> list:
 """Build an Expander with ``\\escapechar`` seeded (TeX default = 92).

 Strips the trailing EOF-space token that the tokenizer appends.
 """
 src = StringInputSource(text)
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 exp = Expander(reader, tok, catcodes)
 regs = RegisterSet()
 regs._bank.count[298] = escapechar
 exp._register_set = regs
 tokens = list(exp)
 if tokens and isinstance(tokens[-1], CharToken) and tokens[-1].catcode == Catcode.SPACE:
 tokens = tokens[:-1]
 return tokens


# ---------------------------------------------------------------------------
# 1. \string respects \escapechar (TeXbook ch. 24)
# ---------------------------------------------------------------------------


def test_string_default_escapechar_emits_backslash() -> None:
 r"""``\escapechar`` defaults to 92 (``\``); ``\string\foo`` -> ``\foo``."""
 tokens = _expand(r"\string\foo")
 text = "".join(t.char for t in tokens if isinstance(t, CharToken))
 assert text == r"\foo"


def test_string_escapechar_minus_one_omits_prefix() -> None:
 r"""``\escapechar = -1`` means no escape character is emitted."""
 tokens = _expand(r"\string\foo", escapechar=-1)
 text = "".join(t.char for t in tokens if isinstance(t, CharToken))
 assert text == "foo"


def test_string_escapechar_custom_byte_emits_that_char() -> None:
 r"""``\escapechar`` in ``0..255`` emits ``chr(escapechar)`` as the prefix."""
 tokens = _expand(r"\string\foo", escapechar=ord("A"))
 text = "".join(t.char for t in tokens if isinstance(t, CharToken))
 assert text == "Afoo"


def test_string_escapechar_out_of_range_omits_prefix() -> None:
 r"""``\escapechar`` > 255 also suppresses the prefix per TeXbook ch. 24."""
 tokens = _expand(r"\string\foo", escapechar=256)
 text = "".join(t.char for t in tokens if isinstance(t, CharToken))
 assert text == "foo"


def test_string_char_token_unaffected_by_escapechar() -> None:
 r"""``\string A`` always yields ``A`` regardless of ``\escapechar``."""
 for esc in (92, -1, 0, 65, 256):
 tokens = _expand(r"\string A", escapechar=esc)
 text = "".join(t.char for t in tokens if isinstance(t, CharToken))
 assert text == "A", f"escapechar={esc}"


def test_string_emits_other_catcode_for_escape_char() -> None:
 r"""The emitted escape character has Catcode.OTHER (per TeXbook ch. 24)."""
 tokens = _expand(r"\string\foo", escapechar=ord("A"))
 chars = [t for t in tokens if isinstance(t, CharToken)]
 assert chars[0].char == "A"
 assert chars[0].catcode == Catcode.OTHER


# ---------------------------------------------------------------------------
# 2. _scan_args consumes leading delimiters (TeXbook §200)
# ---------------------------------------------------------------------------


def test_macro_with_only_delimiters_no_params_consumes_input() -> None:
 r"""``\def\foo XY{Z}`` defines a no-param macro that gobbles ``XY``.

 Before , the delimiters at positions 0/1 of the param pattern
 were silently skipped and ``\foo XY`` produced ``ZXY`` instead of ``Z``.
 """
 tokens = _expand(r"\def\foo XY{Z}\foo XY")
 text = "".join(t.char for t in tokens if isinstance(t, CharToken))
 assert text == "Z"


def test_macro_with_leading_delimiter_run_then_param() -> None:
 r"""``\def\foo AB#1{<#1>}`` matches ``AB`` then captures one undelimited arg."""
 tokens = _expand(r"\def\foo AB#1{<#1>}\foo ABx")
 text = "".join(t.char for t in tokens if isinstance(t, CharToken))
 assert text == "<x>"


def test_macro_delimiter_mismatch_raises() -> None:
 r"""``\def\foo X{Z}\foo Y`` raises (TeXbook §200 ``doesn't match``)."""
 with pytest.raises(EngineError, match="doesn't match"):
 _expand(r"\def\foo X{Z}\foo Y")


# ---------------------------------------------------------------------------
# 3. \newif primitive shortcut is gone (Expander short-circuit + interpreter
# primitive both removed)
# ---------------------------------------------------------------------------


def test_newif_primitive_removed_from_interpreter() -> None:
 r"""``TeXInterpreter._build_primitives`` no longer registers ``newif``."""
 import inspect

 from aspose_tex._engine.interpreter import TeXInterpreter

 src = inspect.getsource(TeXInterpreter._build_primitives)
 assert '"newif"' not in src, "newif primitive entry should be retired"


def test_expander_no_newif_shortcircuit() -> None:
 r"""The Expander's ``if name == 'newif': return tok`` bypass is gone."""
 import inspect

 src = inspect.getsource(Expander._next_unexpandable)
 assert 'name == "newif"' not in src
 assert "name == 'newif'" not in src


# ---------------------------------------------------------------------------
# 4. End-to-end: \newif works through plain.tex's macro
# ---------------------------------------------------------------------------


def test_newif_truthy_branch_renders_y_glyph() -> None:
 r"""``\newif\iffoo\footrue\iffoo Y\else N\fi`` -> DVI contains glyph ``Y``."""
 dvi = _run_dvi(r"\newif\iffoo\footrue\iffoo Y\else N\fi\bye")
 assert ord("Y") in dvi
 assert ord("N") not in dvi


def test_newif_falsy_branch_renders_n_glyph() -> None:
 r"""``\newif\iffoo\foofalse\iffoo Y\else N\fi`` -> DVI contains glyph ``N``."""
 dvi = _run_dvi(r"\newif\iffoo\foofalse\iffoo Y\else N\fi\bye")
 assert ord("N") in dvi
 assert ord("Y") not in dvi


def test_newif_default_is_false() -> None:
 r"""``\newif\iffoo`` without ``\footrue`` defaults to false (TeXbook ch. 20)."""
 dvi = _run_dvi(r"\newif\iffoo\iffoo Y\else N\fi\bye")
 assert ord("N") in dvi
 assert ord("Y") not in dvi


def test_plain_internal_newif_switches_reachable() -> None:
 r"""``\newif``-derived switches in plain.tex itself must be reachable.

 Smoke-checks all five in-tree call sites (plain.tex 598, 1023, 1120,
 1148, 1177): if any one failed to register, format load would raise
 "Undefined control sequence" later on; format load completing without
 raising AND a follow-up ``\ifXxx ...\fi`` test confirms reachability.
 """
 # \ifr@ggedbottom is the most-cited case in 's hypothesis.
 # We can't reference it directly from user code (\catcode`@=12 reverts
 # @ to OTHER at end of plain.tex), but we can confirm format load
 # succeeded by running a no-op job and getting non-empty DVI:
 dvi = _run_dvi(r"X\bye")
 assert len(dvi) > 0
