r"""redefined-\cr honouring in the alignment cell scanner.

plain.tex's ``\m@ketabbox`` does ``\def\cr{\@crtrue\crcr\egroup\egroup…}`` — the
user's ``\cr`` after an alignment row is a *macro* whose body emits the real
primitive ``\crcr`` plus box code. 's cell scanner detected ``\cr`` as a
structural terminator by control-sequence name, intercepting the token before
its macro meaning could expand.  Q5 fixes this: the expander already
expands a user ``\def``/``\let`` of ``\cr`` (so the scanner sees the body, whose
primitive ``\crcr`` is the true terminator), while a non-redefined ``\cr`` still
terminates structurally.
"""
from __future__ import annotations

import warnings

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import HlistNode, KernNode, VlistNode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice

_PRE = r"\font\tenrm=cmr10 \tenrm "


def _halign_vlist(body: str) -> VlistNode:
    """Run ``\\halign{body}`` and return its packed alignment vlist.

    Wraps the alignment in ``\\setbox0=\\vbox{…}`` so it takes the
    *packed* path (a box frame is open); a *top-level* ``\\halign`` splices its
    rows into the page list per ``fin_align`` §812.
    """
    interp = TeXInterpreter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(
            StringInputSource(
                _PRE + r"\setbox0=\vbox{\halign{" + body + r"}}\bye"
            ),
            DviDevice(),
        )
    result = interp._box_regs.getbox(0)
    assert isinstance(result, VlistNode), "no alignment vbox was built"
    return result


def _rows(vlist: VlistNode) -> list[HlistNode]:
    return [n for n in vlist.list if isinstance(n, HlistNode)]


def _kerns(vlist: VlistNode) -> list[KernNode]:
    return [n for n in vlist.list if isinstance(n, KernNode)]


class TestRedefinedCr:
    def test_redefined_cr_runs_body_at_row_break(self) -> None:
        # A user \def\cr{\crcr\noalign{\kern3pt}} runs its body at each row break:
        # the primitive \crcr terminates the row, the \noalign injects a kern.
        vlist = _halign_vlist(
            r"#\cr \def\cr{\crcr\noalign{\kern3pt}}a\cr b\cr"
        )
        assert len(_rows(vlist)) == 2
        kerns = _kerns(vlist)
        assert kerns, "redefined-\\cr \\noalign{\\kern} body did not run"
        assert all(k.width == 3 * 65536 for k in kerns)

    def test_non_redefined_cr_still_terminates(self) -> None:
        # A plain (non-redefined) \cr terminates rows structurally as before.
        vlist = _halign_vlist(r"#\cr a\cr b\cr c\cr")
        assert len(_rows(vlist)) == 3
        assert not _kerns(vlist)

    def test_let_cr_alias_terminates(self) -> None:
        # \let\cr\crcr aliases \cr to the primitive terminator; rows still close.
        vlist = _halign_vlist(r"#\cr \let\cr\crcr a\cr b\cr")
        assert len(_rows(vlist)) == 2
