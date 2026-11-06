r"""Tests for ``\fontdimen<n>\font`` as ``<internal dimen>`` + the shared
``<font>`` resolver ( FR-7 / §E).

Covers:
- AC-1: ``FontManager.current_cs`` + ``resolve_font_cs`` (``\font`` → current,
  a font CS → itself, ``\nullfont`` → ``"nullfont"``, else ``EngineError``);
  ``\the`` / ``\kern`` / assignment all accept ``\font``.
- AC-2: ``\kern\fontdimen1\font`` produces the slant-based kern of the current
  font (read as ``<internal dimen>`` via ``parse_dimen``).
- AC-3: ``\fontdimen8\font=2pt`` mutates and ``\the\fontdimen8\font`` reads it
  back as ``2.0pt``.
- AC-4: existing ``\the\fontdimen<cs>`` / ``\fontdimen<cs>=`` paths still work.
"""
from __future__ import annotations

import warnings

import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import KernNode
from aspose_tex._fonts.font_manager import FontManager, resolve_font_cs
from aspose_tex._input import StringInputSource
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

# cmti10 carries a non-zero slant (fontdimen 1); cmr10 is upright (slant 0).
_CMTI10_SLANT_SP = 16384  # MiKTeX: \fontdimen1 cmti10 = 0.25pt.
_2PT_SP = 131072           # 2pt in scaled points


# ---------------------------------------------------------------------------
# Helpers
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
# AC-1: FontManager.current_cs + resolve_font_cs
# ---------------------------------------------------------------------------

class TestCurrentCsAndResolver:
    """The current-font CS property and the shared ``<font>`` resolver."""

    def test_current_cs_none_when_unselected(self) -> None:
        fm = FontManager()
        assert fm.current_cs is None

    def test_current_cs_reflects_selected_font(self) -> None:
        fm = FontManager()
        fm.load_font("tenit", "cmti10")
        fm.select_font("tenit")
        assert fm.current_cs == "tenit"

    def test_resolver_font_maps_to_current(self) -> None:
        fm = FontManager()
        fm.load_font("tenit", "cmti10")
        fm.select_font("tenit")
        assert resolve_font_cs(fm, "font") == fm.font_id("tenit")

    def test_resolver_font_cs_maps_to_itself(self) -> None:
        fm = FontManager()
        fm.load_font("tenit", "cmti10")
        assert resolve_font_cs(fm, "tenit") == fm.font_id("tenit")

    def test_resolver_nullfont(self) -> None:
        fm = FontManager()
        assert resolve_font_cs(fm, "nullfont") == fm.font_id("nullfont")

    def test_resolver_non_font_token_raises(self) -> None:
        fm = FontManager()
        with pytest.raises(EngineError):
            resolve_font_cs(fm, "relax")

    def test_resolver_non_cs_operand_raises(self) -> None:
        fm = FontManager()
        with pytest.raises(EngineError):
            resolve_font_cs(fm, None)

    def test_resolver_font_without_current_raises(self) -> None:
        fm = FontManager()
        with pytest.raises(EngineError):
            resolve_font_cs(fm, "font")


# ---------------------------------------------------------------------------
# AC-2: \kern\fontdimen1\font reads as <internal dimen> via parse_dimen
# ---------------------------------------------------------------------------

class TestFontdimenInternalDimenRead:
    """``\\fontdimen<n>\\font`` resolves as an ``<internal dimen>``."""

    def test_kern_from_current_font_slant(self) -> None:
        """``\\kern\\fontdimen1\\font`` = slant of the current (cmti10) font."""
        kerns = _collect_kerns(
            r"\font\tenit=cmti10 \tenit A\kern\fontdimen1\font B"
        )
        assert kerns == [_CMTI10_SLANT_SP]

    def test_kern_from_named_font_cs(self) -> None:
        """``\\kern\\fontdimen1\\tenit`` accepts an explicit font CS operand."""
        kerns = _collect_kerns(
            r"\font\tenit=cmti10 \tenit A\kern\fontdimen1\tenit B"
        )
        assert kerns == [_CMTI10_SLANT_SP]

    def test_kern_zero_slant_upright_font(self) -> None:
        """A zero ``\\fontdimen1`` (cmr10 slant) still parses as a 0-width kern."""
        kerns = _collect_kerns(
            r"\font\tenrm=cmr10 \tenrm A\kern\fontdimen1\font B"
        )
        assert kerns == [0]

    def test_internal_dimen_negatable(self) -> None:
        """A leading ``-`` negates the ``<internal dimen>`` fontdimen value."""
        kerns = _collect_kerns(
            r"\font\tenit=cmti10 \tenit A\kern-\fontdimen1\font B"
        )
        assert kerns == [-_CMTI10_SLANT_SP]

    def test_kern_into_dimen_register(self) -> None:
        """``\\dimen0=\\fontdimen1\\font`` assigns through ``parse_dimen``."""
        messages = _run_messages(
            r"\font\tenit=cmti10 \tenit \dimen0=\fontdimen1\font "
            r"\message{d=\the\dimen0}\bye"
        )
        assert messages == ["d=0.25pt"]


# ---------------------------------------------------------------------------
# AC-3: \fontdimen8\font=2pt assignment with the \font operand
# ---------------------------------------------------------------------------

class TestFontdimenAssignmentWithFontOperand:
    """``\\fontdimen<n>\\font=<dimen>`` accepts the ``\\font`` current-font operand."""

    def test_assign_then_read_back_via_the(self) -> None:
        messages = _run_messages(
            r"\font\tenrm=cmr10 \tenrm \fontdimen8\font=2pt "
            r"\message{v=\the\fontdimen8\font}\bye"
        )
        assert messages == ["v=2.0pt"]

    def test_assign_then_read_back_via_kern(self) -> None:
        kerns = _collect_kerns(
            r"\font\tenrm=cmr10 \tenrm \fontdimen8\font=2pt "
            r"A\kern\fontdimen8\font B"
        )
        assert kerns == [_2PT_SP]

    def test_assignment_affects_only_current_font(self) -> None:
        """Assigning ``\\fontdimen8\\font`` mutates the *current* font's metric."""
        messages = _run_messages(
            r"\font\tenrm=cmr10 \font\other=cmr10 \tenrm "
            r"\fontdimen8\font=2pt "
            r"\message{cur=\the\fontdimen8\tenrm other=\the\fontdimen8\other}\bye"
        )
        # cmr10 has only 7 params; index 8 reads 0 until overridden.
        assert messages == ["cur=2.0ptother=2.0pt"]


# ---------------------------------------------------------------------------
# AC-4: existing \the\fontdimen<cs> / \fontdimen<cs>= paths unchanged
# ---------------------------------------------------------------------------

class TestNoRegressionNamedFontPaths:
    """The pre-existing named-font-CS read/assign paths still work."""

    def test_the_fontdimen_named_cs(self) -> None:
        messages = _run_messages(
            r"\font\tenit=cmti10 \message{s=\the\fontdimen1\tenit}\bye"
        )
        assert messages == ["s=0.25pt"]

    def test_assign_fontdimen_named_cs(self) -> None:
        messages = _run_messages(
            r"\font\tenrm=cmr10 \fontdimen8\tenrm=3pt "
            r"\message{v=\the\fontdimen8\tenrm}\bye"
        )
        assert messages == ["v=3.0pt"]
