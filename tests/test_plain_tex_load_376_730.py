"""Plain TeX lines 376-730 load fixtures ( AC-18, , ).

Two fixtures coexist:

1. ``test_plain_tex_376_730_text_mark_leader_active_subset_loads`` — the original
 bounded subset shipped under . Exercises only the -owned text
 slice (active ``~`` macro at line 555, ``\\hrulefill`` at line 707,
 ``\\outer\\def\\bye`` at line 724) with a hand-rolled scaffolding so that
 neither alignment nor math execution paths are entered. Retained for
 targeted regression coverage of the cascade primitives.

2. ``test_plain_tex_376_730_verbatim_loads`` — the follow-up. Loads
 ``src/aspose_tex/data/format/plain.tex`` lines 1-730 verbatim (the AC-18
 slice 376-730 plus its required preamble — lines 1-375 define ``\\newskip``,
 ``\\active``, ``\\@m``, ``\\@M`` and the other control sequences the slice
 reads). Asserts the engine raises no ``EngineError`` and no
 ``NotImplementedError`` during the load.
"""
from __future__ import annotations

from pathlib import Path

from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

_PLAIN_TEX = Path("src/aspose_tex/data/format/plain.tex")


def _plain_lines() -> list[str]:
 return _PLAIN_TEX.read_text(encoding="utf-8").splitlines()


def _plain_line(line_no: int) -> str:
 return _plain_lines()[line_no - 1]


def test_plain_tex_376_730_text_mark_leader_active_subset_loads() -> None:
 """Exercise the -owned text slice paths with math/alignment excluded."""
 source = "\n".join([
 r"\catcode`@=11",
 r"\chardef\active=13 \catcode`\~=\active",
 r"\mathchardef\@M=10000 \chardef\z@=0",
 r"\font\tenrm=cmr10 \tenrm",
 _plain_line(555), # active tie macro
 _plain_line(707), # \leaders\hrule\hfill
 _plain_line(724), # plain \bye shape, no alignment/math execution
 r"\noindent A~B\hrulefill\par",
 r"\end",
 ])

 job = TeXJob(StringInputSource(source), DviDevice(), options=TeXOptions(load_format=False))
 job.run()

 assert job.messages == []


def test_plain_tex_376_730_verbatim_loads() -> None:
 """Load plain.tex lines 1-730 verbatim — closes AC-18 for .

 Per AC-18 the engine must parse and execute lines 376-730 without raising
 ``Undefined control sequence`` or ``NotImplementedError``. Lines 376-730
 reference control sequences defined in lines 1-375 (``\\newskip``,
 ``\\active``, ``\\@m``/``\\@M``, ``\\p@``/``\\z@``, ``\\sixt@@n``,
 ``\\insc@unt``, ``\\m@ne`` and the catcode setup for ``@``/``~``), so the
 preamble must be in scope; loading 376-730 in isolation is unsupported by
 TeX itself (the macros are simply undefined).

 Excluded sub-ranges: **none**. The AC text reserves the right to skip
 alignment-using and math-mode-using paths (covered by /
 ). The reason no exclusion is needed is narrow but load-bearing:
 the *macro-definition* statements in 376-730 (``\\def`` / ``\\outer\\def``
 / ``\\let``) store their replacement text verbatim and do not expand
 alignment bodies (e.g. ``\\m@ketabbox`` lines 615-631 with ``\\ialign``,
 ``\\oalign`` lines 679-680) or math-mode bodies (e.g. ``\\mathhexbox``
 lines 671-672, ``\\underbar`` line 584, ``\\dots`` line 692) at
 definition time — those bodies only fail when later invoked. The
 *non-definition* statements that do execute at load time —
 ``\\font`` directives (lines 400-465), allocator macros
 (``\\newskip`` / ``\\newdimen`` / ``\\newcount`` / ``\\newif`` /
 ``\\newfam`` lines 378-386 + scattered), ``\\textfont`` / ``\\scriptfont``
 / ``\\scriptscriptfont`` family bindings (lines 477-492),
 ``\\skewchar`` assignments (lines 474-475),
 ``\\let\\preloaded=\\undefined`` (line 472), the
 ``\\setbox\\strutbox=\\hbox{\\vrule height8.5pt depth3.5pt width\\z@}``
 construction (line 588), and the ``{\\catcode`\\^^M=\\active
 \\gdef\\obeylines{...}}`` group (lines 521-523) — are all in-scope for
 AC-18 and execute cleanly under the current engine (verified by the
 successful load asserted below). AC-18 is therefore satisfied
 at load time with zero excluded sub-ranges.
 """
 lines = _plain_lines()
 source = "\n".join(lines[0:730]) + "\n\\end\n"

 job = TeXJob(StringInputSource(source), DviDevice(), options=TeXOptions(load_format=False))
 try:
 job.run()
 except EngineError as exc:
 if "Undefined control sequence" in str(exc):
 raise AssertionError(
 f"AC-18 regressed: undefined control sequence during 376-730 load: {exc}"
 ) from exc
 raise
 except NotImplementedError as exc:
 raise AssertionError(
 f"AC-18 regressed: NotImplementedError during 376-730 load: {exc}"
 ) from exc

 assert job.messages == [
 "Preloading the plain format: codes,",
 "registers,",
 "parameters,",
 "fonts,",
 "more fonts,",
 "macros,",
 "math definitions,",
 ], (
 "plain.tex emits \\message{...} markers at known offsets; if this list "
 "drifts, plain.tex has been mutated or the engine swallowed a message "
 "expansion — investigate before re-baselining."
 )
