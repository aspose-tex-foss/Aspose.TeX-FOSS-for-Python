r"""§1203/§1205/§1206 display penalties.

Every display contributes ``\penalty\predisplaypenalty`` directly before the
above-display glue and ``\penalty\postdisplaypenalty`` directly before the
below-display glue (MiKTeX 24.4 ``\showbox``/``\showlists``).
"""
import warnings
from itertools import pairwise

import pytest

from aspose_tex import DviDevice
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import GlueNode, PenaltyNode
from aspose_tex._input.reader import StringInputSource


def _box_list(body: str) -> list:
    interp = TeXInterpreter(load_format="plain")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(
            StringInputSource(r"\setbox0\vbox{" + body + r"}\end"), DviDevice(),
        )
    return interp._box_regs.getbox(0).list


def _display_penalties(nodes: list) -> list[tuple[int, int]]:
    """Return (penalty, following glue width) for each penalty followed by glue."""
    out = []
    for node, nxt in pairwise(nodes):
        if isinstance(node, PenaltyNode) and isinstance(nxt, GlueNode):
            out.append((node.penalty, nxt.glue.width))
    return out


@pytest.mark.parametrize("body", [
    r"\noindent A $$x$$ B\par",              # after a line (short skips)
    r"\noindent A\par $$x$$ B\par",          # after an empty line
    r"\noindent $$x$$ B\par",                # void paragraph
    r"\noindent A $$\halign{#\cr a\cr b\cr}$$ B\par",  # display alignment
])
def test_every_display_has_pre_and_post_penalty(body):
    pairs = _display_penalties(_box_list(body))
    assert [p for p, _ in pairs] == [10000, 0]


def test_display_penalties_follow_the_registers():
    # MiKTeX: \penalty 77 before \abovedisplayshortskip (0pt), \penalty -33
    # before \belowdisplayshortskip (7pt).
    body = r"\predisplaypenalty=77 \postdisplaypenalty=-33 \noindent A $$x$$ B\par"
    assert _display_penalties(_box_list(body)) == [(77, 0), (-33, 7 * 65536)]
