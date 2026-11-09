r"""Tests for cold ``\nullfont`` as a ``<font>`` operand


``\nullfont`` is TeX font 0 and is always defined.  Previously it was only
registered into the :class:`FontManager` the first time ``\nullfont`` was
*executed* as a command, so a ``<font>`` read of ``\nullfont`` BEFORE it was
ever selected (e.g. ``\the\fontdimen1\nullfont``) raised ``FontError``.

The fix eager-registers ``nullfont`` at ``FontManager`` construction.  These
tests pin both the unit-level guarantee (cold ``is_font`` / ``fontdimen``) and
the engine-level behaviour (cold ``\the`` / ``\kern`` of ``\nullfont``), plus
the warm-path regression.
"""
from __future__ import annotations

import warnings

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import KernNode
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._input import StringInputSource
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

# ---------------------------------------------------------------------------
# Helpers (mirrors test_fontdimen_internal_dimen.py)
# ---------------------------------------------------------------------------

def _run_messages(source: str) -> list[str]:
    """Run TeX source through a DVI job and return captured ``\\message`` text."""
    job = TeXJob(
        StringInputSource(source),
        DviDevice(),
        options=TeXOptions(load_format=False),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job.run()
    return job.messages


def _collect_kerns(source: str) -> list[int]:
    """Run TeX source and return the widths of explicit ``KernNode`` outputs."""
    captured: list = []

    class _Capturing(TeXInterpreter):
        def _end_paragraph(self) -> None:
            if self._par_list is not None:
                captured.extend(self._par_list.nodes)
            super()._end_paragraph()

    interp = _Capturing()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run(StringInputSource(source + r"\par\bye"))
    return [n.width for n in captured if isinstance(n, KernNode)]


# ---------------------------------------------------------------------------
# Unit level: a freshly constructed FontManager already knows \nullfont
# ---------------------------------------------------------------------------

class TestFontManagerEagerNullfont:
    """``\\nullfont`` is registered at construction (TeX font 0 is predefined)."""

    def test_cold_is_font_nullfont_true(self) -> None:
        """``is_font("nullfont")`` is true without any prior selection."""
        fm = FontManager()
        assert fm.is_font("nullfont")

    def test_cold_fontdimens_all_zero(self) -> None:
        """fontdimens 1-7 of the cold null font are all zero."""
        fm = FontManager()
        for i in range(1, 8):
            assert fm.fontdimen("nullfont", i) == 0

    def test_cold_nullfont_not_current(self) -> None:
        """Registering ``\\nullfont`` does not auto-select it as the current font."""
        fm = FontManager()
        assert fm.current_cs is None


# ---------------------------------------------------------------------------
# Engine level: <font> reads of \nullfont before it is ever executed
# ---------------------------------------------------------------------------

class TestColdNullfontFontOperand:
    """``\\nullfont`` as a ``<font>`` operand works cold (no prior ``\\nullfont``)."""

    def test_cold_the_fontdimen_nullfont(self) -> None:
        """``\\the\\fontdimen1\\nullfont`` reads ``0sp`` with no prior ``\\nullfont``."""
        messages = _run_messages(
            r"\font\tenrm=cmr10 \tenrm \message{n=\the\fontdimen1\nullfont}\bye"
        )
        assert messages == ["n=0.0pt"]

    def test_cold_kern_fontdimen_nullfont(self) -> None:
        """``\\kern\\fontdimen1\\nullfont`` is a 0-width kern with no prior ``\\nullfont``."""
        kerns = _collect_kerns(
            r"\font\tenrm=cmr10 \tenrm A\kern\fontdimen1\nullfont B"
        )
        assert kerns == [0]

    def test_cold_dimen_assign_from_nullfont(self) -> None:
        """``\\dimen0=\\fontdimen1\\nullfont`` assigns 0 cold via ``parse_dimen``."""
        messages = _run_messages(
            r"\font\tenrm=cmr10 \tenrm \dimen0=\fontdimen1\nullfont "
            r"\message{d=\the\dimen0}\bye"
        )
        assert messages == ["d=0.0pt"]


# ---------------------------------------------------------------------------
# Regression: the warm \nullfont path (selected first) still reads 0
# ---------------------------------------------------------------------------

class TestWarmNullfontUnchanged:
    """Selecting ``\\nullfont`` first then reading its fontdimens still gives 0."""

    def test_warm_the_fontdimen_nullfont(self) -> None:
        messages = _run_messages(
            r"\nullfont \message{n=\the\fontdimen1\nullfont}\bye"
        )
        assert messages == ["n=0.0pt"]

    def test_warm_kern_fontdimen_nullfont(self) -> None:
        kerns = _collect_kerns(r"\nullfont A\kern\fontdimen1\nullfont B")
        assert kerns == [0]
