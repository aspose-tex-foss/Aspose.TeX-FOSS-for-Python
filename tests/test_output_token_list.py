"""Tests for cascade #1 token-list ``\\output`` dispatch."""
from __future__ import annotations

import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode, HlistNode, VlistNode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError


class _CapturingBackend:
 def __init__(self) -> None:
 self.calls: list[tuple[int, VlistNode]] = []

 def shipout(self, page_number: int, box: VlistNode) -> None:
 self.calls.append((page_number, box))


class _CapturingDevice:
 def __init__(self) -> None:
 self.backend = _CapturingBackend()

 def _create_backend(self, font_manager, *, mag: int = 1000):
 return self.backend

 def finalize(self) -> None:
 pass


def _run(tex: str) -> tuple[TeXInterpreter, _CapturingDevice]:
 interp = TeXInterpreter()
 device = _CapturingDevice()
 interp.run_with_device(StringInputSource(tex), device)
 return interp, device


def _chars(node) -> str:
 if isinstance(node, CharNode):
 return chr(node.char)
 if isinstance(node, (HlistNode, VlistNode)):
 return "".join(_chars(child) for child in node.list)
 return ""


def test_output_user_redefined_flips_page_builder_flag() -> None:
 interp, _device = _run(r"\output={\relax}\end")

 assert interp._page_builder._output_is_user_redefined is True


def test_output_minimal_user_routine_ships_box255() -> None:
 interp, device = _run(r"\output={\shipout\box255}X\eject")

 assert len(device.backend.calls) == 1
 page_number, box = device.backend.calls[0]
 assert page_number == 1
 assert "X" in _chars(box)
 assert interp._box_regs.copybox(255) is None
 assert interp._register_set.get_count(0) == 2


def test_output_user_routine_can_interpose_markup() -> None:
 _interp, device = _run(
 r"\output={\setbox0=\box255 \shipout\vbox{\hbox{TOP}\unvbox0}}X\eject"
 )

 assert len(device.backend.calls) == 1
 chars = _chars(device.backend.calls[0][1])
 assert chars.index("TOP") < chars.index("X")


def test_output_outputpenalty_visible_to_body() -> None:
 messages: list[str] = []
 interp = TeXInterpreter(messages=messages)
 device = _CapturingDevice()

 interp.run_with_device(
 StringInputSource(r"\output={\message{\the\outputpenalty}\shipout\box255}X\eject"),
 device,
 )

 assert messages == ["-10000"]


def test_output_dead_cycles_overflow_raises() -> None:
 with pytest.raises(EngineError, match="Output loop"):
 _run(r"\maxdeadcycles=1 \output={\global\setbox255=\box255}A\eject B\eject")


def test_output_bye_drains_pending_output_tokens_before_stopping() -> None:
 _interp, device = _run(r"\output={\shipout\box255}X\bye")

 assert len(device.backend.calls) == 1
 assert "X" in _chars(device.backend.calls[0][1])
