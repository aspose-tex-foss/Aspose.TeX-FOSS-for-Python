from __future__ import annotations

import pytest

from aspose_tex._engine.box_registers import BoxRegisterSet
from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.interpreter import ModeKind
from aspose_tex._engine.nodes import GlueSign, HlistNode, VlistNode
from aspose_tex._engine.registers import GlueOrder, RegisterSet
from aspose_tex._input import CatcodeTable, CharToken, InputReader, StringInputSource, Tokenizer
from aspose_tex.exceptions import EngineError


def _expand(
 text: str,
 *,
 mode: ModeKind = ModeKind.OUTER_VERTICAL,
 boxes: BoxRegisterSet | None = None,
 regs: RegisterSet | None = None,
) -> list:
 src = StringInputSource(text)
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tokenizer = Tokenizer(reader, catcodes)
 expander = Expander(
 reader,
 tokenizer,
 catcodes,
 mode_stack_provider=lambda: mode,
 box_provider=boxes or BoxRegisterSet(),
 register_provider=regs,
 )
 if regs is not None:
 expander._register_set = regs
 return list(expander)


def _chars(tokens: list) -> str:
 return "".join(t.char for t in tokens if isinstance(t, CharToken))


def test_ifdim_less_equal_and_greater() -> None:
 assert "yes" in _chars(_expand(r"\ifdim 5pt<6pt yes\else no\fi"))
 assert "yes" in _chars(_expand(r"\ifdim 5pt=5pt yes\else no\fi"))
 assert "yes" in _chars(_expand(r"\ifdim 6pt>5pt yes\else no\fi"))


def test_ifdim_missing_relation_raises() -> None:
 with pytest.raises(EngineError, match=r"\\ifdim: expected relation"):
 _expand(r"\ifdim 5pt 6pt yes\fi")


@pytest.mark.parametrize(
 ("primitive", "mode", "expected"),
 [
 ("ifhmode", ModeKind.HORIZONTAL, "yes"),
 ("ifhmode", ModeKind.RESTRICTED_HORIZONTAL, "yes"),
 ("ifhmode", ModeKind.OUTER_VERTICAL, "no"),
 ("ifvmode", ModeKind.OUTER_VERTICAL, "yes"),
 ("ifvmode", ModeKind.INTERNAL_VERTICAL, "yes"),
 ("ifvmode", ModeKind.HORIZONTAL, "no"),
 ("ifinner", ModeKind.RESTRICTED_HORIZONTAL, "yes"),
 ("ifinner", ModeKind.INTERNAL_VERTICAL, "yes"),
 ("ifinner", ModeKind.MATH, "yes"),
 ("ifinner", ModeKind.MATH_DISPLAY, "no"),
 ("ifinner", ModeKind.OUTER_VERTICAL, "no"),
 ("ifmmode", ModeKind.MATH, "yes"),
 ("ifmmode", ModeKind.MATH_DISPLAY, "yes"),
 ("ifmmode", ModeKind.OUTER_VERTICAL, "no"),
 ],
)
def test_mode_conditionals(primitive: str, mode: ModeKind, expected: str) -> None:
 result = _chars(_expand(fr"\{primitive} yes\else no\fi", mode=mode))
 assert expected in result


def test_ifbox_family_reads_without_voiding_register() -> None:
 boxes = BoxRegisterSet()
 hbox = HlistNode(
 list=[],
 width=1,
 height=0,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 vbox = VlistNode(
 list=[],
 width=1,
 height=0,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 boxes.setbox(1, hbox)
 boxes.setbox(2, vbox)

 assert "yes" in _chars(_expand(r"\ifvoid0 yes\else no\fi", boxes=boxes))
 assert "yes" in _chars(_expand(r"\ifhbox1 yes\else no\fi", boxes=boxes))
 assert "yes" in _chars(_expand(r"\ifvbox2 yes\else no\fi", boxes=boxes))
 assert boxes.peekbox(1) is hbox


def test_ifbox_accepts_chardef_constant_index() -> None:
 regs = RegisterSet()
 regs.define_constant("boxnum", "chardef", 1)
 boxes = BoxRegisterSet()
 boxes.setbox(
 1,
 HlistNode(
 list=[],
 width=1,
 height=0,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 ),
 )

 assert "yes" in _chars(_expand(r"\ifhbox\boxnum yes\else no\fi", boxes=boxes, regs=regs))


def test_ifbox_out_of_range_raises_engine_error() -> None:
 with pytest.raises(EngineError, match="box register index out of range"):
 _expand(r"\ifvoid300 yes\else no\fi")


def test_ifodd_and_ifeof() -> None:
 assert "yes" in _chars(_expand(r"\ifodd 3 yes\else no\fi"))
 assert "no" in _chars(_expand(r"\ifodd 4 yes\else no\fi"))
 assert "no" in _chars(_expand(r"\ifeof 0 yes\else no\fi"))


def test_ifeof_out_of_range_raises_engine_error() -> None:
 # Matches \openin / \openout / \closein / \closeout / \read / \write
 # bounds-check wording from io_primitives._read_stream_number.
 with pytest.raises(EngineError, match="stream number out of range: 99"):
 _expand(r"\ifeof 99 yes\else no\fi")
 with pytest.raises(EngineError, match="stream number out of range: 16"):
 _expand(r"\ifeof 16 yes\else no\fi")
 with pytest.raises(EngineError, match="stream number out of range: -1"):
 _expand(r"\ifeof -1 yes\else no\fi")


def test_ifcat_regression_with_noexpand() -> None:
 result = _chars(_expand(r"\ifcat\bgroup\noexpand\next yes\else no\fi"))
 assert "no" in result
