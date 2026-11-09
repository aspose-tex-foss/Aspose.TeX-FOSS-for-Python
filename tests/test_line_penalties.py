r"""TeX §890 inter-line penalties.

Expected sequences are MiKTeX 24.4 ``\showbox`` measurements of the same
``\vbox`` paragraphs (plain: ``\clubpenalty=\widowpenalty=150``,
``\displaywidowpenalty=50``, ``\brokenpenalty=100``).
"""
import warnings

from aspose_tex import DviDevice
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import PenaltyNode
from aspose_tex._engine.par_primitives import exec_par
from aspose_tex._input.reader import StringInputSource

FOUR = r"aaa bbb ccc ddd eee fff ggg hhh iii jjj kkk lll mmm nnn ooo ppp"

# combined_document's matrix paragraph: three lines, the second ends at the
# explicit hyphen of "page-builder" (MiKTeX).
HYPHEN_PARAGRAPH = (
    r"\setbox0\vbox{\noindent Inline matrices also appear in text: a matrix "
    r"$\matrix{a&b\cr c&d\cr}$ and a parenthesised one $\pmatrix{x&y\cr z&w\cr}$ "
    r"sit within the paragraph, and enough further running text follows here to "
    r"push the remaining content onto a second page so the page-builder must "
    r"break the mixed body naturally rather than at a forced boundary.\par}"
)


def _run(src: str) -> TeXInterpreter:
    interp = TeXInterpreter(load_format="plain")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(StringInputSource(src + r"\end"), DviDevice())
    return interp


def _penalties(src: str, register: int = 0) -> list[int]:
    box = _run(src)._box_regs.getbox(register)
    return [node.penalty for node in box.list if isinstance(node, PenaltyNode)]


def test_two_line_paragraph_gets_club_plus_widow():
    # MiKTeX: \penalty 300 between the two lines of combined_document's first
    # paragraph.
    src = (r"\setbox0\vbox{\noindent The quick brown fox jumps over the lazy dog. "
           r"The identity $x+y=z$ holds for all values, and $\alpha\beta$ are Greek "
           r"letters that appear inline in running prose without disturbing the "
           r"surrounding line.\par}")
    assert _penalties(src) == [300]


def test_four_line_paragraph_club_and_widow_only():
    # MiKTeX: 150, (none), 150.
    assert _penalties(r"\setbox0\vbox{\hsize=1in \noindent " + FOUR + r"\par}") == [150, 150]


def test_interlinepenalty_is_added_to_every_gap():
    # MiKTeX: 157, 7, 157.
    src = r"\setbox0\vbox{\hsize=1in \interlinepenalty=7 \noindent " + FOUR + r"\par}"
    assert _penalties(src) == [157, 7, 157]


def test_zero_penalties_contribute_no_node():
    src = r"\setbox0\vbox{\hsize=1in \clubpenalty=0 \widowpenalty=0 \noindent " + FOUR + r"\par}"
    assert _penalties(src) == []


def test_display_uses_displaywidowpenalty_and_restarts_club():
    # MiKTeX: before the display 150, 50 (\displaywidowpenalty); the display's
    # 10000 / 0; after it the paragraph's first gap carries \clubpenalty again.
    src = r"\setbox0\vbox{\hsize=1in \noindent " + FOUR + r" $$x$$ " + FOUR + r"\par}"
    assert _penalties(src) == [150, 50, 10000, 0, 150, 150]


def test_line_ending_at_explicit_hyphen_adds_brokenpenalty():
    # MiKTeX: 150 (club), 250 = \brokenpenalty + \widowpenalty after "page-".
    assert _penalties(HYPHEN_PARAGRAPH) == [150, 250]


def test_exec_par_reports_discretionary_breaks(monkeypatch):
    """The disc_breaks out-param flags exactly the line ending at "page-"."""
    from aspose_tex._engine import interpreter as interpreter_module

    seen: list[list[bool]] = []

    def recording_exec_par(*args, **kwargs):
        lines = exec_par(*args, **kwargs)
        seen.append(list(kwargs["disc_breaks"]))
        return lines

    monkeypatch.setattr(interpreter_module, "exec_par", recording_exec_par)
    _run(HYPHEN_PARAGRAPH)
    assert seen[-1] == [False, True, False]
