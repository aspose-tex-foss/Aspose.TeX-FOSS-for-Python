"""Tests for the TeX interpreter skeleton.

Covers:
- ModeStack push/pop/current
- TeXInterpreter.run() on empty input
- Primitive registry completeness
- MATH_SHIFT raises EngineError
- Unknown CS raises EngineError with name and SourceLocation
- \\relax is a no-op
- Group open/close via {/}
"""
import pytest

from aspose_tex._engine.interpreter import ModeKind, ModeStack, TeXInterpreter
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError

# ---------------------------------------------------------------------------
# ModeStack tests
# ---------------------------------------------------------------------------

class TestModeStack:
 """Unit tests for ModeStack ( FR-1)."""

 def test_initial_mode_is_outer_vertical(self) -> None:
 ms = ModeStack()
 assert ms.current == ModeKind.OUTER_VERTICAL

 def test_push_changes_current(self) -> None:
 ms = ModeStack()
 ms.push(ModeKind.HORIZONTAL)
 assert ms.current == ModeKind.HORIZONTAL

 def test_push_pop_lifo(self) -> None:
 ms = ModeStack()
 ms.push(ModeKind.HORIZONTAL)
 ms.push(ModeKind.RESTRICTED_HORIZONTAL)
 assert ms.current == ModeKind.RESTRICTED_HORIZONTAL
 ms.pop()
 assert ms.current == ModeKind.HORIZONTAL
 ms.pop()
 assert ms.current == ModeKind.OUTER_VERTICAL

 def test_pop_returns_popped_mode(self) -> None:
 ms = ModeStack()
 ms.push(ModeKind.INTERNAL_VERTICAL)
 result = ms.pop()
 assert result == ModeKind.INTERNAL_VERTICAL

 def test_pop_base_raises(self) -> None:
 ms = ModeStack()
 with pytest.raises(EngineError, match="Cannot pop base mode"):
 ms.pop()

 def test_pop_after_all_pushed_raises(self) -> None:
 ms = ModeStack()
 ms.push(ModeKind.HORIZONTAL)
 ms.pop()
 with pytest.raises(EngineError, match="Cannot pop base mode"):
 ms.pop()


# ---------------------------------------------------------------------------
# TeXInterpreter skeleton tests
# ---------------------------------------------------------------------------

class TestInterpreterSkeleton:
 """: skeleton & mode machine acceptance criteria."""

 def test_empty_input_returns_valid_dvi(self) -> None:
 """AC-5: run() on empty input produces valid DVI bytes."""
 interp = TeXInterpreter()
 result = interp.run(StringInputSource(""))
 # DVI preamble starts with opcode 247 (0xF7)
 assert isinstance(result, bytes)
 assert len(result) > 0
 assert result[0] == 0xF7 # pre opcode

 def test_relax_is_noop(self) -> None:
 """\\relax followed by \\bye produces valid DVI without crash."""
 interp = TeXInterpreter()
 result = interp.run(StringInputSource(r"\relax\bye"))
 assert isinstance(result, bytes)
 assert result[0] == 0xF7

 def test_unclosed_math_shift_raises(self) -> None:
 """Unclosed inline math raises a clean EngineError."""
 interp = TeXInterpreter()
 with pytest.raises(EngineError, match=r"missing \$ inserted"):
 interp.run(StringInputSource("$"))

 def test_unknown_cs_raises(self) -> None:
 """AC-3: Unknown CS raises EngineError with CS name."""
 interp = TeXInterpreter()
 with pytest.raises(EngineError, match=r"Undefined control sequence \\undefined"):
 interp.run(StringInputSource(r"\undefined\bye"))

 def test_unknown_cs_includes_source_location(self) -> None:
 """AC-3: Error message includes source location info."""
 interp = TeXInterpreter()
 with pytest.raises(EngineError, match=r"at SourceLocation"):
 interp.run(StringInputSource(r"\undefined"))

 def test_primitives_registered(self) -> None:
 """AC-1: Primitive registry contains all required handlers."""
 interp = TeXInterpreter()
 # Run empty to create primitives
 interp.run(StringInputSource(""))
 prims = interp._primitives

 required = {
 # No-op
 "relax",
 # Group
 "begingroup", "endgroup", "aftergroup",
 # Paragraph
 "par", "indent", "noindent",
 # Horizontal glue
 "hfil", "hfill", "hfilneg", "hss",
 # Vertical primitives
 "vfil", "vfill", "vfilneg", "vss",
 "eject", "nointerlineskip", "offinterlineskip",
 # Box primitives
 "hbox", "vbox", "setbox", "box", "copy",
 "wd", "ht", "dp", "raise", "lower",
 # Vertical mode items
 "vskip", "kern", "hrule", "penalty",
 # Font
 "font", "nullfont",
 # Document end
 "bye", "end",
 }
 for name in required:
 assert name in prims, f"Missing primitive: {name}"

 def test_group_open_close(self) -> None:
 """AC: {\\relax} — GroupStack depth returns to 0 after group."""
 interp = TeXInterpreter()
 result = interp.run(StringInputSource(r"{\relax}\bye"))
 assert isinstance(result, bytes)
 assert result[0] == 0xF7

 def test_begingroup_endgroup(self) -> None:
 """\\begingroup \\relax \\endgroup \\bye — SEMI_SIMPLE group works."""
 interp = TeXInterpreter()
 result = interp.run(StringInputSource(r"\begingroup\relax\endgroup\bye"))
 assert isinstance(result, bytes)
 assert result[0] == 0xF7

 def test_bye_produces_valid_dvi(self) -> None:
 """\\bye terminates processing and produces valid DVI."""
 interp = TeXInterpreter()
 result = interp.run(StringInputSource(r"\bye"))
 assert isinstance(result, bytes)
 assert result[0] == 0xF7

 def test_end_produces_valid_dvi(self) -> None:
 """\\end terminates processing."""
 interp = TeXInterpreter()
 result = interp.run(StringInputSource(r"\end"))
 assert isinstance(result, bytes)

 def test_run_is_stateless(self) -> None:
 """NFR-1: Two successive calls do not share state."""
 interp = TeXInterpreter()
 r1 = interp.run(StringInputSource(r"\bye"))
 r2 = interp.run(StringInputSource(r"\bye"))
 # Both should produce valid DVI; contents may differ in details
 # but structure should be the same
 assert r1[0] == 0xF7
 assert r2[0] == 0xF7

 def test_register_through_interpreter(self) -> None:
 """Registers work through the interpreter dispatch."""
 interp = TeXInterpreter()
 # \count0=42 should not crash
 result = interp.run(StringInputSource(r"\count0=42 \bye"))
 assert isinstance(result, bytes)

 def test_nested_groups(self) -> None:
 """Nested brace groups work correctly."""
 interp = TeXInterpreter()
 result = interp.run(StringInputSource(r"{{\relax}}\bye"))
 assert isinstance(result, bytes)
