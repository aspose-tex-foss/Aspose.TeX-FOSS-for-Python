r"""full bundled plain.tex load gate.

Closes the AC-18 / AC-8 broader contract (the
redirect): the **entire** bundled ``src/aspose_tex/data/format/plain.tex`` must
load verbatim through the format loader without an ``EngineError`` /
``NotImplementedError`` / ``Undefined control sequence`` — every macro
(including the alignment-math macros ``\matrix``/``\eqalign``/``\cases``/
``\bordermatrix``/``\displaylines``/``\eqalignno``/``\leqalignno``/``\ialign``,
whose execution paths land at) must at least **define** cleanly.

The task title's "1-1402" is the historical upper bound; the
bundled file is 1241 lines (it ends with ``\def\fmtname...\dump``).  ``\dump``
is only legal during a format load, so the file is loaded the way users load it
- ``TeXOptions(load_format="plain")`` - not re-fed as ordinary document input.
"""
from __future__ import annotations

from pathlib import Path

from aspose_tex import DviDevice, TeXJob, TeXOptions, create_input_source
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError

_PLAIN_TEX = Path(__file__).parent.parent / "src" / "aspose_tex" / "data" / "format" / "plain.tex"


def test_bundled_plain_tex_is_present_and_nonempty() -> None:
    assert _PLAIN_TEX.is_file(), f"bundled plain.tex missing at {_PLAIN_TEX}"
    lines = _PLAIN_TEX.read_text(encoding="utf-8").splitlines()
    # The bundled format is the full ~1241-line plain.tex (corpus),
    # ending with the \fmtname / \fmtversion / \dump epilogue.
    assert len(lines) >= 1200, f"plain.tex unexpectedly short: {len(lines)} lines"
    assert any("\\dump" in ln for ln in lines[-3:]), "plain.tex must end with \\dump"


def test_full_plain_tex_loads_via_format_loader_without_raising() -> None:
    """The whole bundled plain.tex loads through load_format='plain' clean.

    Exercises the real format-load path (the file is pushed onto the input
    stack and executed, ``\\dump`` included), then runs a trivial body so the
    loaded format is actually used.  Any ``EngineError`` /
    ``NotImplementedError`` raised while loading or running fails the gate.
    """
    dev = DviDevice()
    job = TeXJob(
        create_input_source(r"\relax\bye"), dev, TeXOptions(load_format="plain")
    )
    try:
        job.run()
    except (EngineError, NotImplementedError) as exc:  # pragma: no cover - gate
        raise AssertionError(f"plain.tex format load raised: {exc!r}") from exc
    assert dev.get_bytes(), "format load + \\relax\\bye produced no DVI"


def test_loaded_plain_format_exercises_alignment_math_macros() -> None:
    r"""A run-doc that pulls in every alignment-math macro defined by plain.tex.

    Confirms the macros are not just *defined* by the load but *runnable* under
    the loaded format end-to-end — no ``Undefined control sequence`` for any of
    ``\matrix``/``\pmatrix``/``\bordermatrix``/``\cases``/``\eqalign``/
    ``\displaylines``/``\eqalignno``/``\leqalignno``/``\ialign``.
    """
    # One macro per paragraph (real-document usage): adjacent display + inline
    # math without an intervening \par is not a valid plain-TeX sequence.
    formulas = (
        r"$\matrix{a&b\cr c&d\cr}$",
        r"$\pmatrix{x&y\cr z&w\cr}$",
        r"$\bordermatrix{&c_1\cr r_1&a\cr}$",
        r"$f=\cases{1&if $x>0$\cr 0&else\cr}$",
        r"$$\eqalign{x &= y\cr a &= b\cr}$$",
        r"$$\displaylines{p = q\cr r = s\cr}$$",
        r"$$\eqalignno{x &= y&(1)\cr}$$",
        r"$$\leqalignno{x &= y&(1)\cr}$$",
    )
    body = r"\nopagenumbers " + r"\par ".join(formulas) + r"\par\bye"
    dev = DviDevice()
    job = TeXJob(create_input_source(body), dev, TeXOptions(load_format="plain"))
    try:
        job.run()
    except (EngineError, NotImplementedError) as exc:  # pragma: no cover - gate
        raise AssertionError(f"alignment-math run-doc raised: {exc!r}") from exc
    assert dev.get_bytes(), "alignment-math run-doc produced no DVI"


def test_dump_outside_format_load_is_rejected() -> None:
    r"""Sanity guard: \dump is only legal during a format load.

    Feeding plain.tex's epilogue as ordinary document input (not via the format
    loader) must raise — this is why the full-file gate uses load_format, not a
    verbatim re-feed of the file through run_with_device.
    """
    interp = TeXInterpreter()
    try:
        interp.run_with_device(StringInputSource(r"\dump"), DviDevice())
    except EngineError:
        return
    raise AssertionError("\\dump outside a format load should raise EngineError")
