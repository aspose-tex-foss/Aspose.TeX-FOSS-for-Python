r""": scanner delegation and math scope; MiKTeX 24.4 measurements."""
import warnings

import pytest

from aspose_tex import DviDevice
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.reader import StringInputSource


def run(src):
    interp = TeXInterpreter(load_format="plain")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(StringInputSource(src + r"\end"), DviDevice())
    return interp


CONTEXTS = [
    r"\hbox{%s}",
    r"\vbox{\hbox{%s}}",
    r"\vbox{\halign{#\cr %s\cr}}",
]


@pytest.mark.parametrize("wrap", CONTEXTS)
def test_font_definition_in_scanner_matches_miktex(wrap):
    interp = run(r"\setbox0=" + wrap % r"\font\x=cmr12 \x A")
    box = interp._box_regs.getbox(0)
    assert (box.width, box.height, box.depth) == (577257, 537395, 0)
    assert interp._font_manager.current_cs == "tenrm"


def test_font_definition_in_vbox_text_and_footnote():
    interp = run(r"\setbox0=\vbox{\font\x=cmr12 \x A}")
    box = interp._box_regs.getbox(0)
    # Deferred paragraph layout in vboxes is the separate boundary.
    assert box.height == 537395
    assert run(r"x\footnote{1}{\font\x=cmr12 \x A}")


def test_font_units_need_no_preamble_workaround():
    box = run(r"\setbox0=\hbox{\font\x=cmr12 \x\hskip1em\hskip1ex}")._box_regs.getbox(0)
    assert box.width == 1108643


@pytest.mark.parametrize("wrap", [*CONTEXTS, r"\vbox{%s}", r"\hbox{$%s$}"])
@pytest.mark.parametrize("command,expected", [
    (r"\message{MARK:x}", "MARK:x"),
    (r"\errmessage{MARK:x}", "! MARK:x"),
    (r"\write16{MARK:x}", "MARK:x"),
    (r"\immediate\write16{MARK:x}", "MARK:x"),
])
def test_messages_and_supported_write_use_existing_handlers(wrap, command, expected):
    interp = run(r"\setbox0=" + wrap % command)
    assert expected in interp._messages
    assert interp._box_regs.getbox(0).width == 0


@pytest.mark.parametrize("wrap", CONTEXTS)
def test_write_keeps_existing_file_stream_boundary(wrap):
    with pytest.raises(NotImplementedError, match="requires"):
        run(r"\setbox0=" + wrap % r"\write0{x}")


@pytest.mark.parametrize("wrap", CONTEXTS)
def test_immediate_keeps_existing_invalid_prefix_error(wrap):
    from aspose_tex.exceptions import EngineError
    with pytest.raises(EngineError, match="cannot prefix"):
        run(r"\setbox0=" + wrap % r"\immediate\kern1pt")


@pytest.mark.parametrize("command,expected", [
    (r"\message{MARK:x}", "MARK:x"),
    (r"\errmessage{MARK:x}", "! MARK:x"),
    (r"\immediate\write16{MARK:x}", "MARK:x"),
])
def test_io_in_running_vbox_text_line(command, expected):
    interp = run(r"\setbox0=\vbox{a" + command + "b}")
    assert expected in interp._messages
    assert interp._box_regs.getbox(0).height > 0
