r"""Interpreter-level tests for the ``\ht`` / ``\wd`` / ``\dp`` box-dimension
primitives (, §F).

These cover the two halves of the contract:

* **read path** — ``\ht`` / ``\wd`` / ``\dp`` as an ``<internal dimen>`` operand
  (e.g. ``\dimen0=\ht0``), resolved by ``dimparser._lookup_box_dimension``;
* **write path** — ``\ht<reg>=<dimen>`` in command position, dispatched by the
  retired-stub interpreter handlers to ``BoxRegisterSet.set_*``.

The M1 stubs (``_exec_wd_cmd`` / ``_exec_ht_cmd`` / ``_exec_dp_cmd``) used to
consume only the register index and return nothing, so a following dimen-scan
read garbage; these tests pin the real semantics.
"""
from __future__ import annotations

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice


def _run(tex: str) -> TeXInterpreter:
    """Run *tex* through a fresh interpreter and return it for inspection."""
    interp = TeXInterpreter()
    interp.run_with_device(StringInputSource(tex), DviDevice())
    return interp


class TestBoxDimensionRead:
    r"""``\ht`` / ``\wd`` / ``\dp`` as ``<internal dimen>`` operands (AC-4 #1/#2)."""

    def test_ht_read_into_dimen_matches_box_height(self) -> None:
        interp = _run(r"\setbox0=\hbox{Hello}\dimen0=\ht0 \bye")
        assert interp._register_set.get_dimen(0) == interp._box_regs.get_ht(0)
        # A non-empty hbox has a positive height.
        assert interp._register_set.get_dimen(0) > 0

    def test_wd_read_into_dimen_matches_box_width(self) -> None:
        interp = _run(r"\setbox0=\vbox{\hbox{Hello}}\dimen1=\wd0 \bye")
        assert interp._register_set.get_dimen(1) == interp._box_regs.get_wd(0)
        assert interp._register_set.get_dimen(1) > 0

    def test_dp_read_into_dimen_matches_box_depth(self) -> None:
        # 'y' has a descender, so the hbox carries a positive depth.
        interp = _run(r"\setbox0=\hbox{y}\dimen2=\dp0 \bye")
        assert interp._register_set.get_dimen(2) == interp._box_regs.get_dp(0)

    def test_void_box_read_is_zero(self) -> None:
        """Void-box dimension reads as 0 sp, not an error (TeXbook §439; AC-4 #4)."""
        interp = _run(r"\dimen0=\ht5 \dimen1=\wd5 \dimen2=\dp5 \bye")
        assert interp._register_set.get_dimen(0) == 0
        assert interp._register_set.get_dimen(1) == 0
        assert interp._register_set.get_dimen(2) == 0


class TestBoxDimensionWrite:
    r"""``\ht<reg>=<dimen>`` assignment in command position (AC-4 #3)."""

    def test_ht_setter_mutates_register_height(self) -> None:
        interp = _run(r"\setbox0=\hbox{Hello}\ht0=10pt \bye")
        assert interp._box_regs.get_ht(0) == 10 * 65536

    def test_wd_setter_mutates_register_width(self) -> None:
        interp = _run(r"\setbox0=\hbox{Hello}\wd0=72pt \bye")
        assert interp._box_regs.get_wd(0) == 72 * 65536

    def test_dp_setter_mutates_register_depth(self) -> None:
        interp = _run(r"\setbox0=\hbox{Hello}\dp0=3pt \bye")
        assert interp._box_regs.get_dp(0) == 3 * 65536

    def test_equals_less_assignment_scans_dimen(self) -> None:
        r"""Command-position ``\ht<reg>`` is ALWAYS an assignment: the ``=`` is
        optional but a ``<dimen>`` always follows (TeX:The Program §1244
        ``set_box_dimen``;).  This is the ``\finph@nt`` form
        ``\ht\tw@\ht\z@`` — copy box 1's height onto box 0 with no ``=``."""
        interp = _run(r"\setbox0=\hbox{Hello}\setbox1=\hbox{y}\ht0\ht1 \bye")
        # The equals-less assignment RAN: box 0's height now equals box 1's.
        assert interp._box_regs.get_ht(0) == interp._box_regs.get_ht(1)

    def test_set_then_read_round_trips(self) -> None:
        interp = _run(r"\setbox0=\hbox{Hello}\ht0=8.5pt \dimen0=\ht0 \bye")
        assert interp._register_set.get_dimen(0) == round(8.5 * 65536)

    def test_setter_on_void_box_is_noop(self) -> None:
        """Setting a dimension on a void register is a silent no-op."""
        interp = _run(r"\ht7=10pt \dimen0=\ht7 \bye")
        assert interp._box_regs.get_ht(7) == 0
        assert interp._register_set.get_dimen(0) == 0


class TestBoxDimensionGroupScoping:
    r"""The setter is group-scoped: a local ``\ht`` change restores on group close."""

    def test_local_ht_change_persists_after_group(self) -> None:
        r"""Box DIMENSIONS are NOT group-scoped (TeX §1247-1248
        ``alter_box_dimen`` writes the node field directly, no ``eq_save``;
        ).  A ``\ht`` change inside ``{…}`` persists after the group —
        unlike a scoped register write."""
        interp = _run(
            r"\setbox0=\hbox{Hello}"
            r"{\ht0=100pt}"
            r"\dimen0=\ht0 \bye"
        )
        # The change made inside the group survives it (not restored).
        assert interp._register_set.get_dimen(0) == 100 * 65536

    def test_box_dim_write_does_not_corrupt_extracted_box(self) -> None:
        r"""D-β regression (, non-math): a ``\ht``/``\dp`` write followed
        by ``\box`` (which extracts the node) must not be reverted at group
        close — the old save/restore closure mutated the already-contributed
        node by reference.  This is the exact ``\finph@nt`` shape."""
        # \hbox{} is an empty (0,0,0) box — the IniTeX equivalent of \null.
        interp = _run(
            r"\setbox0=\hbox{Hello}"
            r"\setbox3=\hbox{{\setbox2=\hbox{}\ht2=\ht0 \dp2=\dp0 \box2}}"
            r"\bye"
        )
        # box3 wraps the extracted+contributed box2; it must keep box0's height,
        # not the \null (0) it would have if the group-close restore fired.
        assert interp._box_regs.get_ht(3) == interp._box_regs.get_ht(0)
        assert interp._box_regs.get_ht(3) > 0

    def test_global_ht_change_survives_group(self) -> None:
        interp = _run(
            r"\setbox0=\hbox{Hello}"
            r"{\global\ht0=100pt}"
            r"\dimen0=\ht0 \bye"
        )
        assert interp._register_set.get_dimen(0) == 100 * 65536
