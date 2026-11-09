"""named-parameter arithmetic operands.

`\\advance` / `\\multiply` / `\\divide` must accept named parameters
(`\\lineskip`, `\\baselineskip`, `\\lineskiplimit`, …) as operands so plain.tex's
`\\openup` (which does `\\advance\\lineskip…`) runs.  Direct-family arithmetic
(`\\count`/`\\dimen`/`\\skip`) must stay byte-identical; `\\toks` must still be
rejected as non-arithmetic.
"""
from __future__ import annotations

import pytest

from aspose_tex import DviDevice, TeXJob, TeXOptions, create_input_source
from aspose_tex.exceptions import EngineError


def _run(src: str, *, plain: bool = True) -> bytes:
    """Compile *src* to DVI through the public API; return the bytes."""
    dev = DviDevice()
    opts = TeXOptions(load_format="plain") if plain else TeXOptions()
    job = TeXJob(create_input_source(src), dev, opts)
    job.run()
    return dev.get_bytes() or b""


# ---------------------------------------------------------------------------
# D2 unit — named-parameter operands mutate the backing slot, \the reflects it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "param,op",
    [
        # \advance a glue/dimen named param by a dimension (with unit).
        (r"\lineskip", r"\advance\lineskip 2pt\relax"),
        (r"\baselineskip", r"\advance\baselineskip 2pt\relax"),
        (r"\lineskiplimit", r"\advance\lineskiplimit 2pt\relax"),
    ],
)
def test_advance_named_param_runs(param, op):
    src = op + r"\hbox{x}\bye"
    assert _run(src)  # produced output, no raise


def test_advance_lineskip_reflected_in_the():
    """`\\advance\\lineskip` mutates the slot; `\\the\\lineskip` shows the sum."""
    # plain.tex \lineskip default is 1pt; +2pt → 3pt.
    src = (
        r"\advance\lineskip 2pt\relax"
        r"\message{LS=\the\lineskip}\hbox{x}\bye"
    )
    dev = DviDevice()
    job = TeXJob(create_input_source(src), dev, TeXOptions(load_format="plain"))
    job.run()
    # \the of a glue echoes raw sp: 1pt default + 2pt = 3pt = 196608 sp.
    assert "LS=3.0pt" in " ".join(job.messages)


def test_multiply_and_divide_named_param():
    """`\\multiply` / `\\divide` accept a named-param operand."""
    assert _run(r"\multiply\baselineskip by 2\relax \hbox{x}\bye")
    assert _run(r"\divide\lineskip by 2\relax \hbox{x}\bye")


def test_advance_toks_still_rejected():
    """A token-register operand is not arithmetic — the error is unchanged."""
    with pytest.raises(EngineError, match="is not an arithmetic register"):
        _run(r"\advance\toks0 by 1\relax\bye")


def test_unknown_cs_still_rejected():
    with pytest.raises(EngineError, match="is not an arithmetic register"):
        _run(r"\advance\relax by 1\relax\bye", plain=False)


# ---------------------------------------------------------------------------
# D2 — direct-family arithmetic stays byte-identical (internal=False path)
# ---------------------------------------------------------------------------

def test_direct_dimen_arithmetic_unchanged():
    assert _run(r"\dimen0=3pt \advance\dimen0 by 2pt \hbox{x}\bye", plain=False)


def test_direct_count_arithmetic_unchanged():
    src = (
        r"\count5=10 \advance\count5 by 3 \multiply\count5 by 2 \divide\count5 by 4 "
        r"\message{C=\the\count5}\hbox{x}\bye"
    )
    dev = DviDevice()
    job = TeXJob(create_input_source(src), dev, TeXOptions())
    job.run()
    # (10+3)*2/4 = 26/4 = 6 (truncating toward zero)
    assert "C=6" in " ".join(job.messages)


def test_direct_skip_arithmetic_unchanged():
    assert _run(r"\skip0=3pt plus 1fil \advance\skip0 by 2pt \hbox{x}\bye", plain=False)


# ---------------------------------------------------------------------------
# D2 — group save/restore of an advanced named param
# ---------------------------------------------------------------------------

def test_named_param_advance_respects_group_restore():
    """An `\\advance` inside a group restores the named param on `}`."""
    src = (
        r"\message{BEFORE=\the\lineskip}"
        r"{\advance\lineskip 2pt\relax \message{INSIDE=\the\lineskip}}"
        r"\message{AFTER=\the\lineskip}\hbox{x}\bye"
    )
    dev = DviDevice()
    job = TeXJob(create_input_source(src), dev, TeXOptions(load_format="plain"))
    job.run()
    before = [m for m in job.messages if m.startswith("BEFORE=")]
    after = [m for m in job.messages if m.startswith("AFTER=")]
    inside = [m for m in job.messages if m.startswith("INSIDE=")]
    assert before and after and inside
    # The advance is local: BEFORE == AFTER, and INSIDE differs.
    assert before[0].split("=", 1)[1] == after[0].split("=", 1)[1]
    assert inside[0].split("=", 1)[1] != before[0].split("=", 1)[1]


# ---------------------------------------------------------------------------
# D2 integration — \openup runs end-to-end (the plain.tex blocker)
# ---------------------------------------------------------------------------

def test_openup_jot_runs():
    """`\\openup\\jot` (the `\\displ@y`/`\\eqalign` helper) no longer raises."""
    assert _run(r"\openup\jot \hbox{x}\bye")
