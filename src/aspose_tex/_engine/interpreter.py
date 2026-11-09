"""TeX interpreter: mode machine, primitive dispatch, component wiring.

Implements: the central integration layer
that connects Expander, FontManager, RegisterSet, GroupStack, PageBuilder, and
output devices into a working end-to-end pipeline.

See and for design rationale.
"""
from __future__ import annotations

import dataclasses
import logging
import warnings
from contextlib import contextmanager
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aspose_tex.presentation import OutputDevice

from aspose_tex._engine.alignment import (
    _NoalignRecord,
    build_alignment_handlers,
    indent_display_rules,
)
from aspose_tex._engine.box_builder import short_display
from aspose_tex._engine.box_primitives import (
    _PREVDEPTH_SENTINEL,
    OverfullBoxWarning,
    UnderfullBoxWarning,
)
from aspose_tex._engine.box_registers import BoxRegisterSet
from aspose_tex._engine.code_arrays import CodeArrays
from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.group import GroupKind, GroupStack
from aspose_tex._engine.hyph_pass import HyphenationContext, hyphenate_paragraph
from aspose_tex._engine.hyph_primitives import exec_setlanguage, fix_language, try_bundled_hyphen
from aspose_tex._engine.hyphenation import HyphenationStore, norm_min, normalize_language
from aspose_tex._engine.internal_quantities import InternalQuantityRegistry, QuantityKind
from aspose_tex._engine.io_primitives import (
    exec_closein,
    exec_closeout,
    exec_dump,
    exec_errmessage,
    exec_immediate,
    exec_message,
    exec_openin,
    exec_openout,
    exec_read,
    exec_show,
    exec_showthe,
    exec_write,
)
from aspose_tex._engine.linebreak import LinebreakParams, _line_geometry
from aspose_tex._engine.macro import PrimitiveMeaning
from aspose_tex._engine.marks import MarksRegistry
from aspose_tex._engine.math_list import MathListBuilder
from aspose_tex._engine.math_shell import _build_math_shell_registry
from aspose_tex._engine.math_style import TeXStyle
from aspose_tex._engine.meanings import BindingKind, MeaningBindings
from aspose_tex._engine.named_parameters import (
    NamedParameterRegistry,
    _register_appendix_a,
)
from aspose_tex._engine.nodes import (
    NEG_INF_PENALTY,
    RUNNING_DIMEN,
    CharNode,
    DiscretionaryNode,
    GlueNode,
    GlueSign,
    HlistNode,
    KernNode,
    LeadersKind,
    LeadersNode,
    MathNode,
    PenaltyNode,
    RuleNode,
    VlistNode,
)
from aspose_tex._engine.page_builder import (
    SENTINEL_FINISH_OUTPUT_CS,
    PageBuilder,
    PageBuilderConfig,
    PlainOutputRoutine,
)
from aspose_tex._engine.page_primitives import (
    exec_nointerlineskip,
    exec_offinterlineskip,
    exec_shipout,
    make_vfil_glue,
    make_vfill_glue,
    make_vfilneg_glue,
    make_vss_glue,
)
from aspose_tex._engine.par_primitives import (
    ParagraphList,
    exec_par,
    exec_penalty,
    make_hfil_glue,
    make_hfill_glue,
    make_hfilneg_glue,
    make_hss_glue,
)
from aspose_tex._engine.registers import MAX_DIMEN, Glue, GlueOrder, RegisterSet
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._fonts.math_family_registry import MathFamilyRegistry
from aspose_tex._fonts.math_font_parameters import MathFontParameters, MathStyle
from aspose_tex._input.catcode import Catcode, CatcodeTable
from aspose_tex._input.reader import FileInputSource, InputReader, InputSource
from aspose_tex._input.token import CharToken, ControlSequenceToken, FontRefToken, PrimitiveRefToken, Token
from aspose_tex._input.tokenizer import Tokenizer
from aspose_tex.exceptions import EngineError, InputError


def _meaning_token(meaning):
    """Token that stands for a non-macro meaning when it is re-read."""
    if isinstance(meaning, PrimitiveMeaning):
        return PrimitiveRefToken(meaning.name)
    return meaning


# ---------------------------------------------------------------------------
# ModeKind enum
# ---------------------------------------------------------------------------

class ModeKind(Enum):
    """TeX processing modes.

    Math modes build a math list that is converted to a horizontal
    list when the formula ends.

    Example::

        mode = ModeKind.OUTER_VERTICAL
        assert mode != ModeKind.HORIZONTAL
    """

    OUTER_VERTICAL = auto()
    HORIZONTAL = auto()
    INTERNAL_VERTICAL = auto()
    RESTRICTED_HORIZONTAL = auto()
    MATH = auto()
    MATH_DISPLAY = auto()


# ---------------------------------------------------------------------------
# ModeStack
# ---------------------------------------------------------------------------

class ModeStack:
    """LIFO mode stack; starts with OUTER_VERTICAL.

    Example::

        ms = ModeStack()
        assert ms.current == ModeKind.OUTER_VERTICAL
        ms.push(ModeKind.HORIZONTAL)
        assert ms.current == ModeKind.HORIZONTAL
        ms.pop()
        assert ms.current == ModeKind.OUTER_VERTICAL
    """

    def __init__(self) -> None:
        self._stack: list[ModeKind] = [ModeKind.OUTER_VERTICAL]

    @property
    def current(self) -> ModeKind:
        """The active mode (top of stack)."""
        return self._stack[-1]

    @property
    def depth(self) -> int:
        """Number of modes on the stack (1 = base OUTER_VERTICAL only)."""
        return len(self._stack)

    def push(self, mode: ModeKind) -> None:
        """Push a new mode onto the stack."""
        self._stack.append(mode)

    def outside_math(self) -> ModeKind:
        """The innermost mode that is not a math mode (the formula's owner)."""
        return next(
            mode for mode in reversed(self._stack)
            if mode not in (ModeKind.MATH, ModeKind.MATH_DISPLAY)
        )

    def pop(self) -> ModeKind:
        """Pop and return the top mode.

        Raises:
            EngineError: If only OUTER_VERTICAL remains (cannot pop the base).
        """
        if len(self._stack) <= 1:
            raise EngineError("Cannot pop base mode")
        return self._stack.pop()


# ---------------------------------------------------------------------------
# Open-group box construction
# ---------------------------------------------------------------------------

@dataclasses.dataclass(slots=True)
class _BoxBuildFrame:
    """One open-group box under construction by the main loop.

    Created when ``\\hbox``/``\\vbox``/``\\vtop`` (optionally with ``\\setbox``
    or ``to``/``spread``) is followed by a begin-group whose matching
    ``\\egroup``/``}`` arrives later in the token stream — possibly across
    macro and alignment-cell boundaries.  While the frame is on
    ``TeXInterpreter._box_construction_stack`` the main loop routes every
    contribution into ``builder``; the matching end-group finalises the
    builder (applying ``target``/``spread``) and hands the box to
    ``destination``.

    Attributes:
        builder:      The :class:`HBoxBuilder` or :class:`VBoxBuilder`.
        vertical:     ``True`` for ``\\vbox`` / ``\\vtop``.
        group_depth:  ``GroupStack`` depth (after the paired ``BRACE`` push)
                      at which the matching end-group closes this frame.
        destination:  Callback delivering the finished box (Q3): register set
                      for ``\\setbox``, ``_add_box_to_current_list`` for a bare
                      box, or an enclosing builder's ``add_box`` for a nested
                      box.
        target:       ``\\hbox to <dimen>`` width / ``\\vbox to <dimen>`` height.
        spread:       ``\\hbox spread <dimen>`` / ``\\vbox spread <dimen>``.
        vtop:         ``\\vtop`` reference-point semantics.
        saved_par_list: The ``_par_list`` swapped out on open (restored on close).
        restore_mode_depth: ``ModeStack`` depth to restore to on close — the
                      frame may have been opened on top of a delegated-cell
                      ``RESTRICTED_HORIZONTAL`` push (alignment cells).
        saved_spacefactor: The enclosing list's ``\\spacefactor``; every frame
                      restores it on close, and a horizontal list starts at 1000
                      (§1083 push_nest / pop_nest).
    """

    builder: object
    vertical: bool
    group_depth: int
    destination: object
    target: int | None
    spread: int | None
    vtop: bool
    saved_par_list: object
    restore_mode_depth: int
    restore_tail_depth: int
    saved_prev_depth: int
    saved_spacefactor: int = 1000
    saved_prev_graf: int = 0
    saved_last_line: object = None
    saved_math_state: object = None


# ---------------------------------------------------------------------------
# Plain TeX defaults (hardcoded)
# ---------------------------------------------------------------------------

_HSIZE = 30_785_886          # 6.5 in
_VSIZE = 42_152_952          # 8.9 in
_BASELINESKIP = 786_432      # 12 pt
_TOPSKIP = 655_360           # 10 pt
_MAXDEPTH = 262_144          # 4 pt
_LINESKIPLIMIT = 0
_LINESKIP = 65_536           # 1 pt
_LINEPENALTY = 10
_ADJDEMERITS = 10_000
_MAX_DEAD_CYCLES = 25


# TeX §1090: horizontal commands that, met in vertical mode, are read again in
# a new indented paragraph (``back_input; new_graf(true)``).  Letters, other
# characters, ``\chardef`` constants and ``$`` take the same path from their
# own dispatch branches. Leaders retain the receiving axis.
# Vertical commands that end a paragraph through the current \par (TeX
# §1094 hmode+stop/vskip/hrule/un_vbox/halign, head_for_vmode §1095).
_HEAD_FOR_VMODE_PRIMITIVES = frozenset({
    "vskip", "vfil", "vfill", "vss", "vfilneg", "unvbox", "unvcopy", "hrule",
    "halign", "end", "dump",
})

# Consecutive \par insertions that may leave horizontal mode untouched before
# the paragraph is declared stuck (TeX itself would loop forever).
_HEAD_FOR_VMODE_LIMIT = 10_000

_NEW_GRAF_PRIMITIVES = frozenset({
    "char", "unhbox", "unhcopy", "vrule", "accent", "discretionary", "-", " ",
    "hskip", "hglue", "hfil", "hfill", "hss", "hfilneg", "noboundary", "valign",
})


# ---------------------------------------------------------------------------
# Math-mode primitive → MathListBuilder routing (§F)
# ---------------------------------------------------------------------------

_CLASS_PRIMITIVE_NAMES = frozenset(
    {"mathord", "mathop", "mathbin", "mathrel", "mathopen", "mathclose", "mathpunct", "mathinner"}
)
_STYLE_PRIMITIVE_NAMES = frozenset(
    {"displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle"}
)
_FRACTION_PRIMITIVE_NAMES = frozenset(
    {"over", "atop", "above", "overwithdelims", "atopwithdelims", "abovewithdelims"}
)

# Single-method builder dispatch for the remaining in-scope primitives.  \left
# and \right are handled specially in the interpreter (they also update the math
# shell's \left-depth counter); see _math_left / _math_right.
_MATH_BUILDER_DISPATCH: dict[str, object] = {
    "mskip": lambda self, b: b.add_mskip(),
    "mkern": lambda self, b: b.add_mkern(),
    "nonscript": lambda self, b: b.add_nonscript(),
    "mathaccent": lambda self, b: b.add_mathaccent(),
    "radical": lambda self, b: b.add_radical(),
    "overline": lambda self, b: b.add_overline(),
    "underline": lambda self, b: b.add_underline(),
    "vcenter": lambda self, b: b.add_vcenter(),
    "mathchoice": lambda self, b: b.add_mathchoice(),
    "delimiter": lambda self, b: b.add_delimiter(),
    "left": lambda self, b: self._math_left(b),
    "right": lambda self, b: self._math_right(b),
    # §E.1: limit switches set the last OP atom's placement (§1158).
    "limits": lambda self, b: b.add_limits("limits"),
    "nolimits": lambda self, b: b.add_limits("nolimits"),
    "displaylimits": lambda self, b: b.add_limits("displaylimits"),
}


# ---------------------------------------------------------------------------
# \pageno register adapter
# ---------------------------------------------------------------------------

class _Count0PagenoRegister:
    """Adapts ``RegisterSet`` to the ``PageNumberRegister`` protocol.

    \\pageno is defined by plain.tex as ``\\countdef\\pageno=0`` — i.e. an
    alias for ``\\count0``.  The interpreter sets up that alias before
    constructing the output routine; this adapter gives ``PlainOutputRoutine``
    and ``PageBuilder`` read/write access to the same slot.
    """

    __slots__ = ("_groups", "_rs")

    def __init__(self, register_set: RegisterSet, group_stack: GroupStack) -> None:
        self._rs = register_set
        self._groups = group_stack

    def get_pageno(self) -> int:
        """Return current \\pageno (== \\count0)."""
        return self._rs.get_count(0)

    def set_pageno(self, value: int) -> None:
        """Set \\pageno globally, as plain's \\advancepageno does."""
        self._groups.set_global()
        self._rs.set_count(0, value)


# ---------------------------------------------------------------------------
# TeXInterpreter
# ---------------------------------------------------------------------------

def _ends_in_rule(node: object) -> bool:
    r"""Return whether a display alignment's last item ends in a raw rule."""
    return isinstance(node, _NoalignRecord) and bool(node.nodes) and isinstance(
        node.nodes[-1], RuleNode
    )


class TeXInterpreter:
    """Central TeX interpreter: wires all engine components into a pipeline.

    Each call to ``run()`` creates completely fresh state (NFR-1).

    Example::

        from aspose_tex._input.reader import StringInputSource
        interp = TeXInterpreter()
        dvi_bytes = interp.run(StringInputSource("Hello\\\\bye"))
    """

    def __init__(
        self,
        *,
        extra_font_paths: list[Path] | None = None,
        extra_format_paths: list[Path] | None = None,
        load_format: bool | str | None = False,
        messages: list[str] | None = None,
        job_name: str = "texput",
    ) -> None:
        r"""
        Args:
            extra_font_paths: Additional directories to search for TFM files
                              (appended after bundled data).
            extra_format_paths: Additional directories to search for format and
                                ``\input`` files after bundled format data.
            load_format: Format name to load before user input, or ``False`` /
                         ``None`` to skip loading. Defaults to ``False`` for
                         direct interpreter construction.
            messages: Mutable sink for message-producing primitives.
            job_name: Current TeX job name exposed by ``\jobname``.
        """
        self._extra_font_paths: list[Path] = list(extra_font_paths or [])
        self._extra_format_paths: list[Path] = list(extra_format_paths or [])
        self._load_format: bool | str | None = load_format
        self._messages: list[str] = messages if messages is not None else []
        self._job_name = job_name
        self._is_loading_format = False
        # §1: per-language \patterns / \hyphenation stores of the job.
        self._hyphenation = HyphenationStore()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, source: InputSource) -> bytes:
        """Process a TeX source and return DVI output as bytes.

        .. deprecated:: 0.2.0
            Use :class:`~aspose_tex.presentation.TeXJob` with
            :class:`~aspose_tex.presentation.DviDevice` instead.

        Args:
            source: InputSource (FileInputSource or StringInputSource).

        Returns:
            Complete DVI file content as bytes.

        Raises:
            EngineError: On TeX-level errors (undefined CS, mode violations, etc.).
            FontError: On font loading failures.
        """
        warnings.warn(
            "TeXInterpreter.run() is deprecated; "
            "use TeXJob with DviDevice instead",
            DeprecationWarning,
            stacklevel=2,
        )
        from aspose_tex.presentation import DviDevice

        device = DviDevice()
        self.run_with_device(source, device)
        return device.get_bytes()  # type: ignore[return-value]

    def run_with_device(
        self,
        source: InputSource,
        device: OutputDevice,
        *,
        mag: int = 1000,
    ) -> None:
        """Process TeX source, directing output to the given device.

        This is the internal entry point used by ``TeXJob``.  It replaces the
        hardwired DVI pipeline in ``run()`` with a device-agnostic flow.

        Args:
            source: TeX input source.
            device: Output device (provides the backend writer).
            mag:    Magnification * 1000.
        """
        # Step 1 — fresh state
        self._hyphenation = HyphenationStore()
        group_stack = GroupStack()
        # Catcodes share the group stack so \catcode changes are group-scoped
        # Required.
        catcodes = CatcodeTable(group_stack=group_stack)
        font_manager = FontManager(
            extra_search_paths=self._extra_font_paths,
            group_stack=group_stack,
        )
        register_set = RegisterSet(group_stack=group_stack)
        code_arrays = CodeArrays(group_stack=group_stack)
        named_params = NamedParameterRegistry(register_set, group_stack)
        # Post-construction wiring (§5d) so \the\catcode<n> /
        # \the\<codename><n> can read live state, and so that
        # \the\<named-param> resolves through the registry.  The Appendix A
        # catalog is populated later, after PageBuilderConfig exists, because
        # vsize/topskip/maxdepth need an on_set mirror onto it (
        # §"Migration plan").
        register_set._catcodes = catcodes
        register_set._code_arrays = code_arrays
        register_set._named_params = named_params
        box_regs = BoxRegisterSet(group_stack=group_stack)
        reader = InputReader(source)
        tokenizer = Tokenizer(reader, catcodes)
        expander = Expander(
            reader, tokenizer, catcodes,
            max_depth=10_000,
            register_provider=register_set,
            group_stack=group_stack,
            input_resolver=self._resolve_input_path,
            mode_stack_provider=lambda: self._mode_stack.current,
            input_interceptor=lambda path: try_bundled_hyphen(self, path),
            box_provider=box_regs,
            job_name_provider=lambda: self._job_name,
            code_arrays_provider=lambda: self._code_arrays,
        )
        # Allow dimparser to resolve register/alias/chardef constant references
        # (parse_integer / parse_dimen) and to read \mag for true* units.
        expander._register_set = register_set
        expander._named_params = named_params
        expander._interpreter = self
        # one binding per name across the four owners.
        bindings = MeaningBindings(expander, register_set, font_manager, group_stack)
        expander._bindings = bindings
        register_set._bindings = bindings
        self._bindings = bindings

        # Step 2 — output pipeline (device-agnostic)
        backend = device._create_backend(font_manager, mag=mag)
        config = PageBuilderConfig(
            vsize=_VSIZE,
            topskip=Glue(_TOPSKIP, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
            max_depth=_MAXDEPTH,
            baselineskip=Glue(_BASELINESKIP, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
            lineskip=Glue(_LINESKIP, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
            lineskiplimit=_LINESKIPLIMIT,
            max_dead_cycles=_MAX_DEAD_CYCLES,
            hsize=_HSIZE,  # \hsize mirror seed (page-box width).
        )

        # \pageno is an alias for \count0, initialised to 1 (plain.tex line 1144).
        register_set.define_alias("pageno", "count", 0)
        register_set.set_count(0, 1)
        pageno_register = _Count0PagenoRegister(register_set, group_stack)

        # Populate the Appendix A catalog now that PageBuilderConfig exists,
        # so vsize / maxdepth / topskip can carry on_set mirror callbacks
        # (§"Migration plan").
        _register_appendix_a(named_params, page_config=config)
        # TeX §640: the DVI page counters are \count0..\count9.
        set_counter_source = getattr(backend, "set_counter_source", None)
        if set_counter_source is not None:
            set_counter_source(
                lambda: [register_set.get_count(i) for i in range(10)]
            )
        # TeX §617: the job's magnification is fixed by the first shipout.
        set_mag_source = getattr(backend, "set_mag_source", None)
        if set_mag_source is not None:
            set_mag_source(lambda: self._prepare_mag(mag))

        # Step 3 — default font (needed before the output routine so that
        # PlainOutputRoutine can resolve "tenrm" for folio typesetting).
        font_manager.load_font("tenrm", "cmr10")
        font_manager.select_font("tenrm")

        output_routine = PlainOutputRoutine(
            hsize=_HSIZE,
            font_manager=font_manager,
            pageno_register=pageno_register,
            config=config,
        )
        marks_registry = MarksRegistry()
        expander._marks_provider = marks_registry
        page_builder = PageBuilder(
            config, backend, output_routine,
            pageno_register=pageno_register,
            marks_registry=marks_registry,
            box_registers=box_regs,
            named_params=named_params,
            expander=expander,
            font_manager=font_manager,
            on_output_start=self._open_output_nest,
        )
        # §Component 4c: \output's and \maxdeadcycles' on_set hooks
        # are bound after PageBuilder construction so the page-trigger gate
        # flips (and max_dead_cycles tracks the user assignment) as soon as
        # user TeX writes the register.
        if named_params.lookup("output") is not None:
            named_params.set_on_set(
                "output",
                lambda _value, pb=page_builder: setattr(
                    pb, "_output_is_user_redefined", True,
                ),
            )
        if named_params.lookup("maxdeadcycles") is not None:
            named_params.set_on_set(
                "maxdeadcycles",
                lambda value, cfg=config: setattr(cfg, "max_dead_cycles", value),
            )

        # Store component references for dispatch methods
        self._reader = reader
        self._expander = expander
        self._catcodes = catcodes
        self._group_stack = group_stack
        self._font_manager = font_manager
        self._register_set = register_set
        group_stack.set_globaldefs_source(lambda: register_set.get_count(293, _internal=True))
        self._code_arrays = code_arrays
        self._named_params = named_params
        font_manager.set_missing_character_sink(self._report_missing_character)
        self._box_regs = box_regs
        self._page_builder = page_builder
        self._marks = marks_registry
        self._mode_stack = ModeStack()
        self._math_family_registry = MathFamilyRegistry(group_stack, font_manager)
        # sigma/xi provider, consumed by the mlist_to_hlist pass
        # (math axis, quad for mu→sp).  §C.
        self._math_params = MathFontParameters(self._math_family_registry, font_manager)
        self._math_shell = _build_math_shell_registry(
            expander,
            code_arrays,
            self._math_family_registry,
            mode_provider=lambda: self._mode_stack.current,
        )

        # Step 4 — primitive registry
        self._primitives = self._build_primitives()

        # Step 5 — mutable interpreter state
        self._par_list: ParagraphList | None = None
        # / §F: the active math-list builder, constructed on a
        # math-mode push and cleared at the matching ``$``/``$$`` close.  None
        # outside math mode.
        self._math_builder: MathListBuilder | None = None
        self._math_group_base: int | None = None
        self._math_parent_mode_depth = 1
        self._math_eqno_kind: str | None = None       # §F.3
        self._math_eqno_equation: list | None = None
        # open-group boxes (\hbox\bgroup…\egroup) under construction
        # by the main loop, innermost last.  Empty in the common eager path.
        self._box_construction_stack: list[_BoxBuildFrame] = []
        # >0 while scanning an alignment cell, so a math $…$ cell
        # opened via run_inline_math_in_box ends at a top-level &/\cr/\span (the
        # TeX \endv boundary) instead of pumping past the terminator. A counter
        # (not a bool) because alignment cells nest (a \halign inside a cell).
        self._alignment_cell_depth = 0
        # (\endv v-template injection): parallel stacks to
        # `_alignment_cell_depth`, pushed/popped in `alignment._scan_cell`.
        #   _alignment_cell_vtemplate[-1]  → the active math cell's v-template
        #       tokens (or None for an omit/template-less cell); the math pump
        #       injects them AHEAD of a top-level &/\cr so the v-part's `}$…`
        #       closes the cell's open braces+`$` before the terminator fires.
        #   _alignment_cell_pushed_v[-1]   → whether THIS cell already injected
        #       its v-template (a cell may run several `$…$` formulas; the
        #       v-template is consumed once, at the cell terminator).
        self._alignment_cell_vtemplate: list[list | None] = []
        self._alignment_cell_pushed_v: list[bool] = []
        # An assembled text cell can encounter an expanded terminator before
        # its queued V. Keep that boundary and the template's owning depth.
        self._alignment_cell_assembled_close: list[tuple[Token, int] | None] = []
        #   _alignment_cell_ubrace[-1]     → braces the u-template left open
        #       after its `$` (\eqalign's straddling `{`); the math pump fires
        #       the \endv injection when its brace depth reaches this value, not
        #       0 (a genuine `{a&b}` body shield is deeper → stays literal).
        self._alignment_cell_ubrace: list[int] = []
        # depth counter set around `build_math_vcenter_box`'s box
        # execution; >0 ⇒ the `\halign` being built is a math `\vcenter` body
        # (\m@th/\ialign context), so its cells scan in MATH mode (bare
        # `\mathstrut`→`\mathchoice` is a legal atom) via `_scan_math_cell`.
        self._alignment_math_context = 0
        self._spacefactor = 1000
        self._prev_depth = -65_536_000
        self._prev_graf = 0
        # the last line contributed by _end_paragraph, consumed at
        # display entry to measure \predisplaysize and inherit its depth.
        self._last_paragraph_line: HlistNode | None = None
        self._display_resume_paragraph: bool = False
        # the \prevdepth a display's alignment must start
        # from.  TeX ends and contributes the preceding paragraph BEFORE the
        # display's \halign collects its rows, so that alignment's leading
        # \everycr firing sees the last pre-display line's depth.  Our
        # two-pass model collects rows later inside `_translate_mlist`, so
        # preserve the entry depth across intervening nested-box work.
        # Read-and-cleared by `alignment._collect_rows`; None ⇒ inherit.
        self._pending_display_prev_depth: int | None = None
        # §1146 adds 2·quad(cur_font) — the text font in
        # force when `$$` opens, not the family-2 symbol font — captured at
        # display entry because the formula may change the current font.
        self._display_entry_quad = 0
        # when a display's body IS an alignment, its rows
        # and \noalign material are handed over here rather than packed into a
        # box, so `_emit_display` can splice them into the vertical list §812
        # style — between \abovedisplayskip and \belowdisplayskip.  Read-and-
        # cleared by `_emit_display`; None ⇒ the display is an ordinary formula.
        self._pending_display_alignment: list | None = None
        # TeX §1145: True while a `$$…$$` display's save scope is open, so
        # `\displ@y`'s `\openup\jot` is restored at display close rather than
        # accumulating across displays.
        self._display_group_open: bool = False
        self._badness = 0
        self._last_skip = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
        self._tail_providers = []
        self._math_tail_depths = []
        self._last_penalty = 0
        self._last_kern = 0
        self._page_number = 1
        self._done = False
        # \hsize is read live from named-param slot 258 at \par time via
        # _current_hsize() — no stale instance cache.
        # \hangindent / \hangafter live in their named-parameter slots
        # \parshape keeps its own owner here.
        self._parshape: list[tuple[int, int]] | None = None
        # §1095 \par insertions since the last paragraph end.
        self._head_for_vmode_count = 0
        # The open \output routine's nest.
        self._output_frame: _BoxBuildFrame | None = None
        self._split_capture_callback = self._marks.capture_split
        self._internal_quantities = self._build_internal_quantities()

        # Step 6 — main loop
        try:
            self._token_iter = iter(expander)
            if self._load_format not in (False, None):
                self.load_format(str(self._load_format))
            for token in self._token_iter:
                if self._done and not page_builder.output_cycle_pending:
                    break
                self._dispatch(token)
            if self._box_construction_stack:
                # §Error Handling: an open-group \hbox/\vbox whose matching
                # \egroup never arrived leaves a dangling box-build frame at EOF.
                raise EngineError(
                    "Unexpected end of input inside open \\hbox/\\vbox (missing \\egroup})"
                )
            if self._mode_stack.current == ModeKind.MATH:
                self._mode_stack.pop()
                self._math_shell.check_left_right_balanced()
                raise EngineError("missing $ inserted")
            if self._mode_stack.current == ModeKind.MATH_DISPLAY:
                self._mode_stack.pop()
                self._math_shell.check_left_right_balanced()
                raise EngineError("missing $$ inserted")
            if self._is_loading_format:
                self._is_loading_format = False
                raise EngineError("format-load failed: missing \\dump")

            # §1054 its_all_over: flush residual material, running each
            # \output the flush fires, until nothing is left.
            self._token_iter = iter(expander)
            while not page_builder.its_all_over():
                while page_builder.output_cycle_pending:
                    token = next(self._token_iter, None)
                    if token is None:
                        raise EngineError("output routine ended before finish sentinel")
                    self._dispatch(token)
            device.finalize()
        except EngineError:
            self._restore_math_scope(emit_aftergroup=False)
            self._math_shell._left_right_depth = 0
            raise
        finally:
            self._tail_providers.clear()
            self._math_tail_depths.clear()
            if self._box_construction_stack:
                self._prev_depth = self._box_construction_stack[0].saved_prev_depth
                self._box_construction_stack.clear()

    def load_format(self, name: str) -> None:
        """Push a format file onto the input stack for execution.

        Args:
            name: Format name resolved through the input search path.

        Raises:
            EngineError: If *name* is unsupported or cannot be resolved.
        """
        try:
            path = self._resolve_input_path(name)
        except InputError as exc:
            raise EngineError(f"unsupported format: {name}") from exc
        self._is_loading_format = True
        self._reader.push(FileInputSource(path))

    def _resolve_input_path(self, filename: str) -> Path:
        r"""Resolve ``\input`` and format filenames per search order.

        Search order is bundled ``data/format`` first, then
        ``extra_format_paths``, then the current working directory.  A missing
        suffix also probes the ``.tex`` variant.
        """
        requested = Path(filename)
        candidates = [requested]
        if requested.suffix == "":
            candidates.append(requested.with_suffix(".tex"))

        if requested.is_absolute():
            for candidate in candidates:
                if candidate.is_file():
                    return candidate
            raise InputError(f"cannot resolve input file '{filename}'")

        search_roots = [
            Path(__file__).resolve().parent.parent / "data" / "format",
            *self._extra_format_paths,
            Path.cwd(),
        ]
        for root in search_roots:
            for candidate in candidates:
                path = root / candidate
                if path.is_file():
                    return path
        raise InputError(f"cannot resolve input file '{filename}'")

    # ------------------------------------------------------------------
    # Primitive registry
    # ------------------------------------------------------------------

    def _build_primitives(self) -> dict[str, object]:
        """Build the primitive dispatch table.

        Returns:
            A dict mapping CS names to zero-arg handler callables.
        """
        primitives: dict[str, object] = {
            # No-op
            "relax": lambda: None,
            # §1045/§1038: a non-character command that ends the lig/kern run;
            # CM fonts have no boundary character, so nothing else happens.
            "noboundary": lambda: None,
            " ": self._exec_control_space,
            # Private output-cycle sentinel; unreachable from TeX source
            # because the control-sequence name starts with NUL.
            SENTINEL_FINISH_OUTPUT_CS: self._end_output_routine,
            # Group commands (moved from Expander)
            "begingroup": self._exec_begingroup,
            "endgroup": self._exec_endgroup,
            "aftergroup": self._exec_aftergroup,
            # Paragraph commands
            "par": self._exec_par_cmd,
            "indent": self._exec_indent,
            "noindent": self._exec_noindent,
            # Horizontal glue helpers
            "hfil": lambda: self._append_horizontal_glue(make_hfil_glue()),
            "hfill": lambda: self._append_horizontal_glue(make_hfill_glue()),
            "hfilneg": lambda: self._append_horizontal_glue(make_hfilneg_glue()),
            "hss": lambda: self._append_horizontal_glue(make_hss_glue()),
            # Vertical primitives
            "vfil": lambda: self._contribute_vertical_glue(make_vfil_glue()),
            "vfill": lambda: self._contribute_vertical_glue(make_vfill_glue()),
            "vfilneg": lambda: self._contribute_vertical_glue(make_vfilneg_glue()),
            "vss": lambda: self._contribute_vertical_glue(make_vss_glue()),
            "eject": self._exec_eject_cmd,
            "shipout": self._exec_shipout_cmd,
            "nointerlineskip": lambda: exec_nointerlineskip(self._page_builder),
            "offinterlineskip": lambda: exec_offinterlineskip(self._page_builder),
            # Box primitives
            "hbox": self._exec_hbox_cmd,
            "vbox": self._exec_vbox_cmd,
            "vtop": self._exec_vtop_cmd,
            "setbox": self._exec_setbox_cmd,
            "box": self._exec_box_cmd,
            "copy": self._exec_copy_cmd,
            "wd": self._exec_wd_cmd,
            "ht": self._exec_ht_cmd,
            "dp": self._exec_dp_cmd,
            "raise": self._exec_raise_cmd,
            "lower": self._exec_lower_cmd,
            "moveleft": self._exec_moveleft_cmd,
            "moveright": self._exec_moveright_cmd,
            "hskip": self._exec_hskip_cmd,
            "hglue": self._exec_hglue_cmd,
            "vglue": self._exec_vglue_cmd,
            "unhbox": lambda: self._exec_unhbox_cmd(copy=False),
            "unhcopy": lambda: self._exec_unhbox_cmd(copy=True),
            "unvbox": lambda: self._exec_unvbox_cmd(copy=False),
            "unvcopy": lambda: self._exec_unvbox_cmd(copy=True),
            "unskip": self._exec_unskip_cmd,
            "unkern": self._exec_unkern_cmd,
            "unpenalty": self._exec_unpenalty_cmd,
            "lastbox": self._exec_lastbox_cmd,
            "vsplit": self._exec_vsplit_cmd,
            "leavevmode": self._exec_leavevmode_cmd,
            "parshape": self._exec_parshape_cmd,
            "char": self._exec_char_cmd,
            "accent": self._exec_accent_cmd,
            "discretionary": self._exec_discretionary_cmd,
            "-": self._exec_discretionary_hyphen,
            "ignorespaces": self._exec_ignorespaces,
            "vrule": self._exec_vrule_cmd,
            "fontdimen": self._exec_fontdimen_cmd,
            "skewchar": self._exec_skewchar_cmd,
            "hyphenchar": self._exec_hyphenchar_cmd,
            "setlanguage": lambda: exec_setlanguage(self),
            "textfont": self._exec_textfont_cmd,
            "scriptfont": self._exec_scriptfont_cmd,
            "scriptscriptfont": self._exec_scriptscriptfont_cmd,
            "eqno": lambda: self._begin_eqno("eqno"),
            "leqno": lambda: self._begin_eqno("leqno"),
            "mark": self._exec_mark_cmd,
            "insert": self._exec_insert_cmd,
            # `\/` is a real TeX primitive — plain.tex does not redefine it as a
            # macro, so §"Primitive shortcut catalogue" row 6 is
            # implemented rather than retired (there is no macro to take over).
            "/": self._exec_italic_correction,
            "leaders": lambda: self._exec_leaders_cmd(LeadersKind.NORMAL),
            "cleaders": lambda: self._exec_leaders_cmd(LeadersKind.C),
            "xleaders": lambda: self._exec_leaders_cmd(LeadersKind.X),
            # Vertical mode items
            "vskip": self._exec_vskip,
            "kern": self._exec_kern_cmd,
            "hrule": self._exec_hrule,
            "penalty": self._exec_penalty_cmd,
            "vadjust": self._exec_vadjust,
            # \vsize / \topskip / \maxdepth: dispatched through
            # NamedParameterRegistry as; their on_set mirrors keep
            # PageBuilderConfig in sync (§"Migration plan").
            # Code-array primitives (§5b —)
            "catcode":  self._exec_catcode,
            "mathcode": self._exec_mathcode,
            "delcode":  self._exec_delcode,
            "sfcode":   self._exec_sfcode,
            "lccode":   self._exec_lccode,
            "uccode":   self._exec_uccode,
            # Font commands (— stubs for now)
            "font": self._exec_font,
            "nullfont": self._exec_nullfont,
            # Document end
            "bye": self._exec_bye,
            "end": self._exec_end,
            # I/O primitives (—)
            "message": lambda: exec_message(self),
            "write": lambda: exec_write(self),
            "immediate": lambda: exec_immediate(self),
            "errmessage": lambda: exec_errmessage(self),
            "show": lambda: exec_show(self),
            "showthe": lambda: exec_showthe(self),
            "dump": lambda: exec_dump(self),
            "openin": lambda: exec_openin(self),
            "openout": lambda: exec_openout(self),
            "closein": lambda: exec_closein(self),
            "closeout": lambda: exec_closeout(self),
            "read": lambda: exec_read(self),
        }
        primitives.update(build_alignment_handlers(self))
        return primitives

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, token: Token) -> None:
        """Dispatch a single token based on type, catcode, and current mode."""
        if isinstance(token, CharToken):
            self._dispatch_char(token)
        elif isinstance(token, ControlSequenceToken):
            self._dispatch_cs(token)

    def _dispatch_char(self, token: CharToken) -> None:
        """Dispatch a CharToken by catcode and mode."""
        cat = token.catcode
        mode = self._mode_stack.current

        if cat == Catcode.BEGIN_GROUP:
            self._group_stack.open_group(GroupKind.BRACE)
            # In math mode a brace also opens a sub-mlist (TeX §1150): the group
            # builds a self-contained sub-formula boxed as one Ord atom, so
            # \over / scripts inside it stay scoped.
            if mode in (ModeKind.MATH, ModeKind.MATH_DISPLAY) and self._math_builder is not None:
                self._math_builder.begin_group()
            return

        if cat == Catcode.END_GROUP:
            if not self._group_stack.depth:
                raise EngineError("Extra } at global level")
            if self._group_stack._frames[-1].kind != GroupKind.BRACE:
                raise EngineError("} cannot close a \\begingroup")
            # an \egroup/} that closes an open-group box-build frame
            # finalises the box and delivers it (the frame opened the paired
            # BRACE save-frame, closed here via _close_group_box).
            frame = self._current_box_frame()
            if frame is not None and self._group_stack.depth == frame.group_depth:
                if mode in (ModeKind.MATH, ModeKind.MATH_DISPLAY):
                    raise EngineError("} cannot close the active math group")
                if frame.vertical and mode == ModeKind.HORIZONTAL:
                    self._end_paragraph()
                # §1086 package reads box_max_depth before unsave restores it.
                max_depth = self._get_named_dimen("boxmaxdepth") if frame.vertical else None
                aftergroup_tokens, _kind = self._group_stack.close_group()
                self._close_group_box(max_depth=max_depth)
                if aftergroup_tokens:
                    self._expander.push_tokens(aftergroup_tokens)
                return
            if mode in (ModeKind.MATH, ModeKind.MATH_DISPLAY) and self._math_builder is not None:
                self._math_builder.end_group()
            aftergroup_tokens, _kind = self._group_stack.close_group()
            if aftergroup_tokens:
                self._expander.push_tokens(aftergroup_tokens)
            return

        if cat == Catcode.MATH_SHIFT:
            self._handle_math_shift(token)
            return

        if cat == Catcode.ALIGNMENT:
            raise EngineError("alignment tab outside \\halign/\\valign")

        if mode in (ModeKind.MATH, ModeKind.MATH_DISPLAY):
            if cat == Catcode.SPACE:
                return
            if cat == Catcode.SUBSCRIPT:
                self._math_builder.add_subscript()
                return
            if cat == Catcode.SUPERSCRIPT:
                self._math_builder.add_superscript()
                return
            if cat in (Catcode.LETTER, Catcode.OTHER, Catcode.ACTIVE):
                self._dispatch_char_in_math(token)
                return

        if cat in (Catcode.LETTER, Catcode.OTHER):
            if mode in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
                self._handle_char(token)
            elif mode in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
                self._back_input_new_graf(token)
            return

        if cat == Catcode.SPACE:
            # §1041 hmode+spacer: interword glue in both horizontal modes (an
            # open-group \hbox\bgroup list is restricted horizontal); vertical
            # modes discard it.
            if mode in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
                self._handle_space()
            return

        if cat == Catcode.ACTIVE:
            self._dispatch_active_char(token)
            return

        # Other catcodes are outside the text-mode surface.

    def _handle_math_shift(self, token: CharToken) -> None:
        """Open or close inline/display math on ``$`` (cascade #1)."""
        mode = self._mode_stack.current

        if mode in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
            self._back_input_new_graf(token)
            return

        if mode == ModeKind.HORIZONTAL:
            # raw lookahead must not run a leading global or conditional
            # before the formula's local fam initialization and save frame.
            self._math_group_base = self._group_stack.depth
            self._math_parent_mode_depth = self._mode_stack.depth
            self._mode_stack.push(ModeKind.MATH)
            if self._peek_opening_math_shift():
                self._expander._next_raw()
                self._mode_stack.pop()  # was the tentative MATH
                # contribute text with its entry snapshot, before any
                # body/everydisplay assignments or the display's math nest.
                shape = self._linebreak_params()
                metrics = self._font_manager.current_metrics
                self._display_entry_quad = metrics.fontdimen(6) if metrics is not None else 0
                self._display_resume_paragraph = self._par_list is not None
                self._last_paragraph_line = None
                self._end_paragraph(normal=False, build=False)
                self._math_parent_mode_depth = self._mode_stack.depth
                self._mode_stack.push(ModeKind.MATH_DISPLAY)
                # §1145: \displaywidth / \displayindent
                # must be live BEFORE the formula body is scanned — the plain.tex
                # \displ@y families expand to `\halign to\displaywidth{…}`, so a
                # zero here silently packs the rows at their natural width.
                self._init_display_params(shape)
                self._init_display_prev_depth()
                # TeX §1145: opening a display pushes a math nest whose save
                # stack restores at `$$`-close, so plain.tex `\displ@y`'s
                # `\openup\jot` (+3 pt to \baselineskip/\lineskip/
                # \lineskiplimit) is scoped to the display.  Without the group
                # it ACCUMULATES: measured 12 → 15 → 18 pt across a document
                # with three displays, where MiKTeX reports 12.0 pt before and
                # after every one.  Closed in `_emit_display`.
                self._group_stack.open_group(GroupKind.SEMI_SIMPLE)
                self._display_group_open = True
                self._open_math_builder()
                self._push_toks_if_any(259)
                return
            self._open_math_builder()
            self._push_toks_if_any(258)
            return

        if mode == ModeKind.RESTRICTED_HORIZONTAL:
            if self._math_builder is not None:
                # A deferred box is also a mode barrier around the parent
                # formula. Reuse the eager scanner's local ownership guard.
                for node in self.run_inline_math_in_box(token):
                    self._append_to_hlist(node)
                return
            self._math_group_base = self._group_stack.depth
            self._math_parent_mode_depth = self._mode_stack.depth
            self._mode_stack.push(ModeKind.MATH)
            if self._peek_opening_math_shift():
                self._mode_stack.pop()
                raise EngineError(
                    "display math is not allowed in restricted horizontal mode"
                )
            self._open_math_builder()
            self._push_toks_if_any(258)
            return

        if mode == ModeKind.MATH:
            self._math_shell.check_left_right_balanced()
            self._close_math_builder()
            return

        if mode == ModeKind.MATH_DISPLAY:
            if not self._peek_is_math_shift():
                raise EngineError("$$ display-math close expected")
            self._consume_peeked_token()
            self._math_shell.check_left_right_balanced()
            self._close_math_builder(display=True)
            return

    def _open_math_builder(self) -> None:
        """Construct the math-list builder on a math-mode push (§F)."""
        self._math_parent_mode_depth = self._mode_stack.depth - 1
        self._math_group_base = self._group_stack.depth
        if self._mode_stack.current == ModeKind.MATH:
            self._group_stack.open_group(GroupKind.SEMI_SIMPLE)
        else:
            self._math_group_base -= 1  # display owns its existing frame
        self._math_builder = MathListBuilder(
            self._expander,
            self._code_arrays,
            self._math_family_registry,
            self._register_set,
        )
        builder = self._math_builder
        self._math_tail_depths.append(len(self._tail_providers))
        self._tail_providers.append(lambda: builder.tail)
        # §F.3: \eqno/\leqno capture state (reset per formula).
        self._math_eqno_kind = None
        self._math_eqno_equation = None
        # TeX:The Program §1138 (init_math): entering math mode resets the
        # current family to -1, so a variable-family (\mathcode class 7) letter
        # uses its *encoded* family (math italic = 1) rather than the \fam left
        # over from the surrounding text mode (plain.tex's \rm sets \fam=0).
        # Saved here and restored at $-close (after_math, §1194).
        with self._group_stack.local_assignment():
            self._register_set.set_count(296, -1, _internal=True)

    def _begin_eqno(self, kind: str) -> None:
        r"""Start an ``\eqno`` / ``\leqno`` equation number (§F.3).

        The math-list built so far is the equation; the builder is reset to
        collect the equation-number mlist (scanned until ``$$``).  Preserves the
        ``\eqno``-outside-display error contract.
        """
        if self._mode_stack.current.name != "MATH_DISPLAY":
            raise EngineError(f"\\{kind} is valid only in display math")
        if self._math_eqno_kind is not None:
            raise EngineError("double \\eqno")
        self._math_eqno_kind = kind
        self._math_eqno_equation = self._math_builder.take_mlist()

    def _close_math_builder(self, *, display: bool = False) -> None:
        """Finish the formula at ``$``/``$$``-close: translate + place (§F).

        Inline (``$``) runs ``mlist_to_hlist`` at text style and appends the
        result to the surrounding horizontal list, framed by ``\\mathsurround``
        kerns (TeX:The Program §1196).  Display (``$$``) runs at *display* style
        and centres the equation in the vertical list with the display skips and
        the ``\\eqno`` / ``\\leqno`` number (§F, TeX §1199-§1206).
        """
        completed = False
        try:
            if self._group_stack.depth != self._math_group_base + 1:
                raise EngineError("Unclosed group inside math")
            builder = self._math_builder
            self._math_builder = None
            if builder is None:
                return
            eqno_kind = self._math_eqno_kind
            if eqno_kind is not None:
                # The builder holds the eqno mlist; the equation was captured at \eqno.
                equation_mlist = self._math_eqno_equation
                eqno_mlist = builder.take_mlist()
            else:
                equation_mlist = builder.take_mlist()
                eqno_mlist = None
            self._math_eqno_kind = None
            self._math_eqno_equation = None

            style = TeXStyle.DISPLAY if display else TeXStyle.TEXT
            try:
                eq_nodes = self._translate_mlist(
                    equation_mlist, style=style,
                    # §761: only a formula in a paragraph (not in \hbox)
                    # gets the §767 Bin/Rel penalties.
                    penalties=(not display
                               and self._mode_stack.outside_math() == ModeKind.HORIZONTAL),
                )
                eqno_nodes = (
                    self._translate_mlist(eqno_mlist, style=style)
                    if eqno_mlist is not None else None
                )
            except EngineError as exc:
                # TeX:The Program §1195: insufficient math fonts → the formula is
                # *deleted* (a recoverable error), not a hard abort.  A document
                # that enters math without assigning \textfont1/2/3 produces no
                # rendered math rather than crashing — matching TeX and preserving
                # the "math without fonts is a no-op" behaviour.
                if "is undefined" in str(exc) or "is not a math" in str(exc):
                    completed = True
                    return
                raise

            if display:
                self._mode_stack.pop()
                self._emit_display(eq_nodes, eqno_nodes, leqno=(eqno_kind == "leqno"))
                # The successful display has installed a new continuation nest.
                # Scope cleanup must retain it rather than unwind to entry vmode.
                self._math_parent_mode_depth = self._mode_stack.depth
                completed = True
                return

            # Inline ($) — append to the surrounding horizontal list.
            self._spacefactor = 1000  # §1196 after_math, including an empty formula.
            if self._par_list is None:
                completed = True
                return
            # §1196: math-on and math-off nodes frame every inline formula,
            # an empty or deleted one included, so the formula's last glue or
            # kern is never the list tail.  \mathsurround is
            # read inside the formula's scope.
            surround = self._register_set.get_dimen(268, _internal=True)  # \mathsurround
            self._append_to_hlist(MathNode(width=surround, after=False))
            for node in eq_nodes:
                self._append_to_hlist(node)
            self._append_to_hlist(MathNode(width=surround, after=True))
            completed = True
        finally:
            self._restore_math_scope(emit_aftergroup=completed)

    def _translate_mlist(
        self, mlist: list, *, style: TeXStyle = TeXStyle.TEXT, penalties: bool = False,
    ) -> list:
        """Translate a noad mlist to hlist nodes via mlist_to_hlist (§C).

        ``penalties`` is TeX's ``mlist_penalties`` (§761): only a formula that
        goes into a paragraph gets the §767 Bin/Rel penalties.
        """
        from aspose_tex._engine.mlist_to_hlist import mlist_to_hlist

        thin = self._register_set.get_muskip(256, _internal=True)   # \thinmuskip
        med = self._register_set.get_muskip(257, _internal=True)    # \medmuskip
        thick = self._register_set.get_muskip(258, _internal=True)  # \thickmuskip
        scriptspace = self._register_set.get_dimen(267, _internal=True)         # \scriptspace
        nulldelimiterspace = self._register_set.get_dimen(266, _internal=True)  # \nulldelimiterspace
        delimiterfactor = self._register_set.get_count(303, _internal=True)      # \delimiterfactor
        delimitershortfall = self._register_set.get_dimen(265, _internal=True)  # \delimitershortfall
        return mlist_to_hlist(
            mlist,
            style,
            math_params=self._math_params,
            family_registry=self._math_family_registry,
            font_manager=self._font_manager,
            thin_mu=thin,
            med_mu=med,
            thick_mu=thick,
            scriptspace=scriptspace,
            nulldelimiterspace=nulldelimiterspace,
            delimiterfactor=delimiterfactor,
            delimitershortfall=delimitershortfall,
            penalties=penalties,
            binoppenalty=self._get_named_int("binoppenalty"),
            relpenalty=self._get_named_int("relpenalty"),
        )

    def _emit_display(self, eq_nodes: list, eqno_nodes: list | None, *, leqno: bool) -> None:
        r"""Centre a display equation and contribute it to vertical mode (§1199-§1206).

        The paragraph was finalized at opening ``$$``. Contributes
        ``\abovedisplayskip`` → the centred display line →
        ``\belowdisplayskip`` to the page builder.  The equation is centred in
        ``\displaywidth`` (offset by ``\displayindent``); ``\eqno`` is placed
        flush right, ``\leqno`` flush left, with §1201 squeeze and direct
        own-line number contributions; §1203 chooses display skips.
        """
        from aspose_tex._engine.mlist_to_hlist import _pack_hbox

        # The paragraph and all entry parameters were finalized at opening $$.
        resume_paragraph = self._display_resume_paragraph
        self._display_resume_paragraph = False

        # a display whose body IS an alignment contributes
        # its rows individually (§812) instead of as one packed box, so the
        # first row attracts its own \baselineskip and the \everycr \noalign
        # glue reaches the vertical list.  Taken (and cleared) before the
        # §1204 read below, which must still see \predisplaysize as computed.
        spliced = self._pending_display_alignment
        self._pending_display_alignment = None

        eq_box = _pack_hbox(eq_nodes, self._font_manager)
        adjustments = self._extract_adjustments(eq_box)
        display_width = self._get_named_dimen("displaywidth")
        display_indent = self._get_named_dimen("displayindent")

        line, d, separate_number = self._build_display_line(
            eq_box, eqno_nodes, leqno=leqno,
            display_width=display_width, display_indent=display_indent,
        )

        # §1203 verbatim: long skips iff d+s <= pre or the
        # number is a \leqno.  A void paragraph needs no case of its own — its
        # \predisplaysize is -\maxdimen.  §1206 fin_align never reaches §1203:
        # a display alignment always takes the long skips.
        pre = self._get_named_dimen("predisplaysize")
        short = spliced is None and not leqno and pre < display_indent + d
        above = self._get_named_skip("abovedisplayshortskip" if short else "abovedisplayskip")
        below = self._get_named_skip("belowdisplayshortskip" if short else "belowdisplayskip")

        # TeX §1205: \abovedisplayskip is part of the display's vertical material
        # (not discardable page-top glue) — it is contributed unconditionally so
        # a standalone display sits topskip + \abovedisplayskip below the top,
        # matching MiKTeX.  §1203/§1206: \predisplaypenalty comes first, for
        # every display, so the above-skip is never a breakpoint.
        # §1200: the page is built only after the display's material and the
        # §1207 optional space, and only when it lands on the main list.
        build_after = self._receives_outer_vlist()
        self._contribute(PenaltyNode(self._get_named_int("predisplaypenalty")))
        if spliced is None and separate_number is not None and leqno:
            self._contribute(separate_number)
            self._contribute(PenaltyNode(10000))
        else:
            self._contribute(GlueNode(above))
        if spliced is not None:
            # §812: rows and their \everycr \noalign material go in one at a
            # time, so the page builder computes \baselineskip against each row
            # (§679) exactly as it does for a top-level \halign.
            for node in spliced:
                if isinstance(node, _NoalignRecord):
                    # body glue is already computed; replay it raw.
                    self._splice_vertical_nodes(
                        indent_display_rules(node.nodes, display_indent)
                    )
                    self._set_prevdepth(node.prev_depth)
                else:
                    if isinstance(node, (HlistNode, VlistNode)):
                        node.shift_amount += display_indent
                    self._contribute(node)
        else:
            self._contribute(line)
            if separate_number is not None and not leqno:
                self._contribute(PenaltyNode(10000))
                self._contribute(separate_number)
        if adjustments:
            self._splice_vertical_nodes(adjustments)
        # §1205/§1206: every display close emits \postdisplaypenalty ahead of
        # the below-skip.  Measured: it does NOT track
        # \interdisplaylinepenalty, so it is the display's, not \everycr's.
        # §806/§812: fin_align's tail pointer still names a final rule it boxed
        # for the indent, so §1206 appends these two inside that box and they
        # never reach the list.
        if not (display_indent and spliced and _ends_in_rule(spliced[-1])):
            self._contribute(PenaltyNode(self._get_named_int("postdisplaypenalty")))
            if spliced is not None or separate_number is None or leqno:
                self._contribute(GlueNode(below))

        # §1145: close the display's save scope, so `\displ@y`'s `\openup\jot`
        # does not leak into the following text.  Closed HERE rather than
        # earlier because the rows above are contributed with the display's
        # interline parameters in force, which is what MiKTeX's transcript
        # shows (\glue(\baselineskip) 7.5 = 15.0 - 0.0 - 7.5).
        if self._display_group_open:
            self._display_group_open = False
            aftergroup_tokens, _kind = self._group_stack.close_group()
            if aftergroup_tokens:
                self._expander.push_tokens(aftergroup_tokens)

        # TeX §1206 resume_after_display: the paragraph CONTINUES after the
        # display — re-enter horizontal mode with no \parindent box, and absorb
        # the §1207 optional space.  Deleting this silently re-introduces a
        # 20 pt indent on every post-display line.  Must run
        # AFTER the below-glue (§1206 appends below_display_skip before
        # push_nest) and after the §1204 \predisplaysize read.
        if resume_paragraph:
            self._resume_after_display()
        if build_after:
            self._page_builder.build_page()

    def _resume_after_display(self) -> None:
        r"""Resume the paragraph interrupted by a ``$$…$$`` display (§1206-§1207).

        TeX's ``resume_after_display`` re-enters horizontal mode with
        ``push_nest; mode := hmode; space_factor := 1000`` — going *directly*
        to hmode rather than through ``new_graf``, so **no** ``\parindent``
        indent box is contributed: the paragraph is continuing, not starting.
        It then scans and discards one optional space (§1207
        ``get_x_token; if cur_cmd<>spacer then back_input``), so the space a
        author naturally writes in ``$$…$$ tail`` does not become leading glue
        on the resumed line.
        """
        # §1206: push_nest; mode := hmode; space_factor := 1000 — exactly what
        # _begin_paragraph(indent=False) does (HORIZONTAL push, parindent=None so
        # ParagraphList prepends no indent box, _spacefactor reset to 1000) —
        # minus the new_graf \parskip.  §1200: the display counts as three
        # lines of the paragraph, so \prevgraf carries on from them.
        self._prev_graf += 3
        self._begin_paragraph(indent=False, par_skip=False)

        # §1207: get_x_token — the EXPANDED next token (peek(), not peek_raw()),
        # so a macro expanding to a leading space still has that space absorbed.
        # The unpeek() is defensive rather than load-bearing HERE: _next_raw
        # drains the one-slot _peeked cache before _stack, so an un-parked token
        # still reaches the main loop next.  The ordering inversion only
        # bites once a push_tokens() intervenes — which this method does not do.
        # Parking it back keeps the branch correct if one is ever added.
        token = self._expander.peek()
        if isinstance(token, CharToken) and token.catcode == Catcode.SPACE:
            next(self._token_iter)
        else:
            self._expander.unpeek()

    def _build_display_line(
        self, eq_box, eqno_nodes: list | None, *, leqno: bool,
        display_width: int, display_indent: int,
    ) -> tuple[HlistNode, int, HlistNode | None]:
        r"""Build the centred display line (§1199-§1205).

        Centres *eq_box* in ``display_width`` (offset by ``display_indent``) and
        appends an ``\eqno`` flush right (or ``\leqno`` flush left).  When the
        number plus the equation cannot fit on one line (§1201) the number is
        moved to its own line — *below* the equation for ``\eqno``, *above* for
        ``\leqno`` — and returned separately for direct contribution.

        Returns:
            ``(line, d, separate_number)``: formula line, §1202 displacement
            for skip selection, and optional separately shifted number box.
        """
        from aspose_tex._engine.mlist_to_hlist import _pack_hbox

        eqno_box = _pack_hbox(eqno_nodes, self._font_manager) if eqno_nodes is not None else None
        d, e = self._display_displacement(eq_box, eqno_box, display_width=display_width)

        # §1201: e = 0 means the number cannot sit beside the equation within
        # \displaywidth (w + width + math_quad > z) and gets its own line.
        if eqno_box is not None and e == 0:
            eq_box.shift_amount = display_indent + d
            eqno_box.shift_amount = (display_indent if leqno else
                                    display_indent + display_width - eqno_box.width)
            return eq_box, d, eqno_box

        return self._centre_display_line(
            eq_box, eqno_box, leqno=leqno, d=d,
            display_width=display_width, display_indent=display_indent,
        ), d, None

    def _display_displacement(
        self, eq_box: HlistNode, eqno_box: HlistNode | None, *, display_width: int,
    ) -> tuple[int, int]:
        r"""Return ``(d, e)`` of TeX §1199-§1202 for a display formula.

        ``e`` is the number's width (0 without a number, or when §1201 moves it
        to its own line); ``d`` is the formula's displacement from
        ``\displayindent``: ``half(z - w)``, or ``half(z - w - e)`` when a number
        would come closer than ``2e`` — and 0 if the formula then starts with
        glue.

        Args:
            eq_box: The packed formula.
            eqno_box: The packed ``\eqno``/``\leqno`` number, or None.
            display_width: ``\displaywidth`` in sp.

        Returns:
            ``(d, e)`` in sp.

        Example::

            d, e = self._display_displacement(eq_box, None, display_width=z)
        """
        from aspose_tex._engine.box_builder import (
            _collect_shrink,
            append_overfull_rule,
            set_glue_hbox,
        )
        from aspose_tex._engine.math_delimiters import _half

        z = display_width
        w = eq_box.width
        e = 0
        q = 0
        if eqno_box is not None:
            e = eqno_box.width
            q = e + self._math_params.math_quad(MathStyle.TEXT)
        if w + q > z:
            # §1201: shrink the actual formula list, not just its measured
            # width. Nested box glue cannot supply shrink to this hpack.
            shrink = _collect_shrink(eq_box.list)
            badness = 0
            if e != 0 and (w - shrink[GlueOrder.NORMAL] + q <= z
                           or any(shrink[o] != 0 for o in
                                  (GlueOrder.FIL, GlueOrder.FILL, GlueOrder.FILLL))):
                badness = set_glue_hbox(eq_box, target_width=z - q)
            else:
                e = 0
                if w > z:
                    badness = set_glue_hbox(eq_box, target_width=z)
            # A formula wider than the display is an overfull hpack (§666).
            from aspose_tex._engine.box_primitives import _warn_badness

            _warn_badness(eq_box, badness, expander=self._expander, font_manager=self._font_manager)
            append_overfull_rule(
                eq_box, badness, self._font_manager,
                hfuzz=self._get_named_dimen("hfuzz"),
                overfull_rule=self._get_named_dimen("overfullrule"),
            )
            w = eq_box.width
        d = _half(z - w)
        if e > 0 and d < 2 * e:
            d = _half(z - w - e)
            if eq_box.list and isinstance(eq_box.list[0], (GlueNode, LeadersNode)):
                d = 0
        return d, e

    def _centre_display_line(
        self, eq_box, eqno_box, *, leqno: bool, d: int,
        display_width: int, display_indent: int,
    ):
        r"""Build the one-line display hbox (number beside the equation).

        An unnumbered formula is shifted directly to its center. A numbered
        one follows §1204: ``\eqno`` → kern ``d``, formula, kern ``z-w-e-d``,
        number; ``\leqno`` → number, kern ``z-w-e-d``, formula — so the
        number is flush right / left and the formula sits at the §1202 ``d``.
        """
        from aspose_tex._engine.box_builder import HBoxBuilder

        hfil = Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)
        builder = HBoxBuilder(self._font_manager)
        if eqno_box is None:
            eq_box.shift_amount = display_indent + d
            return eq_box
        gap = display_width - eq_box.width - eqno_box.width - d
        if leqno:
            builder.add_box(eqno_box)
            builder.add_kern(gap, explicit=True)
            builder.add_box(eq_box)
            builder.add_glue(hfil)
        else:
            builder.add_kern(d, explicit=True)
            builder.add_box(eq_box)
            builder.add_kern(gap, explicit=True)
            builder.add_box(eqno_box)
        line = builder.build(target_width=display_width)
        line.shift_amount = display_indent
        return line

    def _peek_opening_math_shift(self) -> bool:
        """Inspect one raw opening token without running body assignments."""
        tok = self._expander.peek_raw()
        if isinstance(tok, ControlSequenceToken):
            tok = self._expander.macros.get(tok.name, tok)
        return isinstance(tok, CharToken) and tok.catcode == Catcode.MATH_SHIFT

    def _restore_math_scope(self, *, emit_aftergroup: bool) -> None:
        """Unwind only the current formula's owned save frames."""
        base = self._math_group_base
        if base is None:
            return
        tokens = []
        while self._group_stack.depth > base:
            deferred, _kind = self._group_stack.close_group()
            tokens.extend(deferred)
        self._math_group_base = None
        self._display_group_open = False
        self._display_resume_paragraph = False
        self._pending_display_prev_depth = None
        self._display_entry_quad = 0
        self._math_builder = None
        if self._math_tail_depths:
            del self._tail_providers[self._math_tail_depths.pop():]
        while self._mode_stack.depth > self._math_parent_mode_depth:
            self._mode_stack.pop()
        if emit_aftergroup and tokens:
            self._expander.unpeek()
            self._expander.push_tokens(tokens)

    def _peek_is_math_shift(self) -> bool:
        """Return whether the next unexpandable token is a math-shift char."""
        tok = self._peek_token()
        return isinstance(tok, CharToken) and tok.catcode == Catcode.MATH_SHIFT

    def _consume_peeked_token(self) -> Token | None:
        """Consume the token currently exposed by ``Expander.peek``."""
        return self._next_token()

    def _push_toks_if_any(self, slot: int) -> None:
        """Inject an Appendix A toks value when it is non-empty."""
        toks = self._register_set.get_toks(slot, _internal=True)
        if toks:
            self._expander.push_tokens(toks)

    def _dispatch_active_char(self, token: CharToken) -> None:
        """Dispatch an active character the expander handed over unexpanded.

        The expander expands a defined active character itself, so this sees
        one that is undefined, came through ``\\noexpand`` (TeX would treat it
        as ``\\relax`` here, §358), or was returned as an alias by
        ``get_x_token``.  Its meaning lives under ``active_char_key``, not under
        the character, which is the key of the control symbol ``\\<char>``.
        """
        from aspose_tex._engine.expansion import _EXPANDABLE_PRIMITIVES, _UNDEFINED
        from aspose_tex._engine.macro import MacroDefinition, active_char_key

        key = active_char_key(token.char)
        meaning = self._expander.macros.get(key)
        if meaning is None and self._bindings.binding_of(key) is not None:
            self._expander.push_tokens([ControlSequenceToken(key)])
            return
        if self._expander._last_noexpand:
            resolved = self._expander._ifx_meaning(token)
            if (resolved == _UNDEFINED or isinstance(resolved, MacroDefinition)
                    or (isinstance(resolved, tuple) and resolved[0] == "prim"
                        and resolved[1] in _EXPANDABLE_PRIMITIVES)):
                return  # Only expandable/undefined meanings act as relax (§358).
        if meaning is None:
            if (self._mode_stack.current in (ModeKind.MATH, ModeKind.MATH_DISPLAY)
                    and self._code_arrays.get_mathcode(ord(token.char)) == 0x8000):
                raise EngineError("math-active char without macro")
            loc = self._reader.current_location
            raise EngineError(f"Undefined active character: {token.char} at {loc}")
        if isinstance(meaning, MacroDefinition):
            self._expander._expand_macro(token.char, meaning)
            return
        self._expander.push_tokens([_meaning_token(meaning)])

    def _dispatch_char_in_math(self, token: CharToken) -> None:
        """Route a character token in math mode to the noad builder (§F).

        A math-active (``\\mathcode = 0x8000``) char defers to its active macro
        (contract preserved); every other char builds a symbol noad via
        :meth:`MathListBuilder.add_char` (the class-7/``\\fam`` resolution lives
        in the builder).
        """
        from aspose_tex._engine.macro import MacroDefinition, active_char_key

        if token.catcode == Catcode.ACTIVE:
            self._dispatch_active_char(token)
            return
        code = self._code_arrays.get_mathcode(ord(token.char))
        if code == 0x8000:
            # §1151: a math-active char acts as the active char of that code.
            key = active_char_key(token.char)
            meaning = self._expander.macros.get(key)
            if meaning is None and self._bindings.binding_of(key) is not None:
                self._expander.push_tokens([ControlSequenceToken(key)])
                return
            if meaning is None:
                raise EngineError("math-active char without macro")
            if isinstance(meaning, MacroDefinition):
                self._expander._expand_macro(token.char, meaning)
                return
            self._expander.push_tokens([_meaning_token(meaning)])
            return
        self._math_builder.add_char(ord(token.char))

    def _dispatch_math_builder(self, name: str) -> bool:
        """Route a in-scope math primitive to the noad builder (§F).

        Returns ``True`` if *name* was handled.  ``\\left``/``\\right`` also
        update the math shell's depth counter so ``check_left_right_balanced``
        keeps its error contract; ``\\limits``/``\\nolimits``/``\\displaylimits``
        set the last OP atom's limit mode (§E.1, TeX §1158).
        """
        builder = self._math_builder
        if builder is None:
            return False
        if name in _CLASS_PRIMITIVE_NAMES:
            builder.add_class_primitive(name)
            return True
        if name in _STYLE_PRIMITIVE_NAMES:
            builder.add_style(name)
            return True
        if name in _FRACTION_PRIMITIVE_NAMES:
            builder.add_fraction(name)
            return True
        if name in ("mathchar", "char"):
            from aspose_tex._engine.dimparser import parse_integer

            builder.add_mathchar(parse_integer(self._expander, allow_negative=False))
            return True
        handler = _MATH_BUILDER_DISPATCH.get(name)
        if handler is not None:
            handler(self, builder)
            return True
        return False

    def _math_left(self, builder: MathListBuilder) -> None:
        builder.add_boundary("left")
        self._math_shell._left_right_depth += 1

    def _math_right(self, builder: MathListBuilder) -> None:
        if self._math_shell._left_right_depth == 0:
            raise EngineError("\\right without \\left")
        self._math_shell._left_right_depth -= 1
        builder.add_boundary("right")

    def cs_has_meaning(self, name: str) -> bool:
        r"""Return whether control sequence *name* has a non-macro meaning here.

        Answers TeX's ``eq_type(p) <> undefined_cs`` for the names this
        interpreter owns, by asking every registry :meth:`_dispatch_cs`
        consults, without executing anything.  Macros and ``\let`` aliases
        live in the expander's table and are checked there.

        Args:
            name: Control sequence name without backslash.

        Returns:
            ``True`` if *name* is a primitive, parameter, font, register or
            constant; ``False`` if dispatching it would report an undefined
            control sequence.
        """
        return (
            name in self._primitives
            or name in _CLASS_PRIMITIVE_NAMES
            or name in _STYLE_PRIMITIVE_NAMES
            or name in _FRACTION_PRIMITIVE_NAMES
            or name in ("mathchar", "char")
            or name in _MATH_BUILDER_DISPATCH
            or self._math_shell.knows(name)
            or self._internal_quantities.lookup(name) is not None
            or self._named_params.lookup(name) is not None
            or self._font_manager.is_font(name)
            or self._register_set.has_command(name)
            or self._register_set.resolve_constant(name) is not None
        )

    def _dispatch_cs(self, token: ControlSequenceToken) -> None:
        """Dispatch a ControlSequenceToken."""
        name = token.name

        if isinstance(token, FontRefToken):
            self._font_manager.select_font_id(token.name)
            return
        # A PrimitiveRefToken is a resolved built-in, never a binding.
        if not isinstance(token, PrimitiveRefToken) and self._dispatch_binding(token):
            return

        # 1. Primitive registry
        handler = self._primitives.get(name)
        if handler is not None:
            if (name in _HEAD_FOR_VMODE_PRIMITIVES
                    and self._mode_stack.current == ModeKind.HORIZONTAL):
                self._insert_par_before(token)
                return
            if name in _NEW_GRAF_PRIMITIVES and self._mode_stack.current in (
                ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL,
            ):
                self._back_input_new_graf(token)
                return
            handler()
            return

        # Math-mode primitive dispatch (§F): math-mode-only
        # primitives such as \over / \mathopen / \mathaccent are consulted ONLY
        # when the current mode is MATH or MATH_DISPLAY; outside math mode they
        # fall through so the standard "Undefined control sequence" path runs.
        # builders own list construction; routes the limit
        # switches (\limits / \nolimits / \displaylimits) to the builder too.
        if self._mode_stack.current in (ModeKind.MATH, ModeKind.MATH_DISPLAY):
            if self._dispatch_math_builder(name):
                return
            if self._math_shell.dispatch_if_known(name):
                return

        # 2. InternalQuantityRegistry.  It supersedes the
        # older Appendix A placeholder entries for page-state names.
        internal_entry = self._internal_quantities.lookup(name)
        if internal_entry is not None:
            self._internal_quantities.dispatch_assignment(internal_entry, self._expander)
            return

        # 3. NamedParameterRegistry (§5c —).  Sits between
        # primitives and font check so user macros (Expander expands first)
        # still win, but \hsize / \tolerance / etc. parse without falling
        # through to the "Undefined control sequence" branch.
        named_entry = self._named_params.lookup(name)
        if named_entry is not None:
            self._named_params.dispatch_assignment(named_entry, self._expander)
            return

        # 5. Register command (families, arithmetic, \...def)
        if self._register_set.execute(
            name, self._expander, primitive=isinstance(token, PrimitiveRefToken),
        ):
            return

        # 7. Unknown CS — include SourceLocation in message
        loc = self._reader.current_location
        raise EngineError(
            f"Undefined control sequence \\{name} at {loc}"
        )

    def _dispatch_binding(self, token: ControlSequenceToken) -> bool:
        """Dispatch a register alias, constant or font binding.

        A binding outranks the built-in of the same name, so this runs before
        the primitive registry.  Returns ``True`` if *token* had a binding.
        """
        name = token.name
        if self._register_set.resolve_alias(name) is not None:
            return self._register_set.execute(name, self._expander)
        if self._font_manager.is_font(name):
            self._font_manager.select_font(name)
            return True
        # \chardef / \mathchardef constant — emit char in H mode (§5c).
        # Integer-coercion paths (e.g. ``\catcode`\~=\active``) are handled by
        # parse_integer's resolve_constant fallback.
        const = self._register_set.resolve_constant(name)
        if const is not None:
            kind, value = const
            if kind == "chardef":
                if self._mode_stack.current in (
                    ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL,
                ):
                    self._back_input_new_graf(token)
                    return True
                self._handle_chardef_constant(value)
                return True
            if kind == "mathchardef" and self._mode_stack.current in (
                ModeKind.MATH,
                ModeKind.MATH_DISPLAY,
            ):
                # / §B.2: a \mathchardef symbol builds a noad.
                self._math_builder.add_mathchar(value)
                return True
            # Outside math mode, behave as a no-op (integer coercion already
            # handled by parse_integer fallback).
            return True

        return False

    def _handle_chardef_constant(self, code: int) -> None:
        """Treat a \\chardef constant as a character in H/RH mode (§5c).

        Vertical mode never gets here: :meth:`_dispatch_cs` starts the
        paragraph first (§1090).  The constant becomes a synthetic
        ``CharToken(chr(code), Catcode.OTHER)`` routed through
        ``_handle_char`` so that lig/kern/spacefactor still apply.
        """
        synthetic = CharToken(chr(code), Catcode.OTHER)
        self._handle_char(synthetic)

    # ------------------------------------------------------------------
    # Group commands (moved from Expander)
    # ------------------------------------------------------------------

    def _exec_begingroup(self) -> None:
        """\\begingroup — open a SEMI_SIMPLE group."""
        self._group_stack.open_group(GroupKind.SEMI_SIMPLE)

    def _exec_endgroup(self) -> None:
        """\\endgroup — close a SEMI_SIMPLE group."""
        if not self._group_stack.depth:
            raise EngineError("Extra \\endgroup at global level")
        if self._group_stack._frames[-1].kind != GroupKind.SEMI_SIMPLE:
            raise EngineError("\\endgroup cannot close a box or brace group")
        # only the formula's dollar close may restore its owned
        # frame. Reject before mutation so fatal cleanup can discard deferred
        # tokens and leave every enclosing frame intact.
        if (self._math_group_base is not None
                and self._group_stack.depth <= self._math_group_base + 1):
            raise EngineError("\\endgroup cannot close the active math group")
        aftergroup_tokens, _kind = self._group_stack.close_group()
        if aftergroup_tokens:
            self._expander.push_tokens(aftergroup_tokens)

    def _exec_aftergroup(self) -> None:
        """\\aftergroup — read next token and queue for after-group insertion."""
        tok = self._expander._next_raw()
        if tok is None:
            raise EngineError("\\aftergroup: missing token")
        self._group_stack.push_aftergroup(tok)

    # ------------------------------------------------------------------
    # Character processing
    # ------------------------------------------------------------------

    def _prepare_mag(self, option: int) -> int:
        r"""Return the magnification the output is written at (TeX §288).

        Args:
            option: ``TeXOptions.magnification``.  A value other than the
                default 1000 is the caller's explicit choice and stands.

        Returns:
            The document's ``\mag`` otherwise, or 1000 if that is illegal.
        """
        if option != 1000:
            return option
        mag = self._get_named_int("mag")
        if 0 < mag <= 32768:
            return mag
        self._messages.append(f"! Illegal magnification has been changed to 1000 ({mag}).")
        return 1000

    def _report_missing_character(self, font_name: str, code: int) -> None:
        """Report construction-time absence with the live tracinglostchars gate."""
        if self._get_named_int("tracinglostchars") <= 0:
            return
        metrics = self._font_manager.get_metrics(font_name)
        font = ("nullfont" if metrics is self._font_manager._nullfont_metrics
                else metrics.tfm_name)
        char = chr(code) if 32 <= code < 127 else f"^^{code:02x}"
        message = f"Missing character: There is no {char} in font {font}!"
        logging.getLogger("aspose_tex").warning(message)
        self._messages.append(message)

    def _handle_char(self, token: CharToken) -> None:
        """Process a character token in H/RH mode: create CharNode, apply lig/kern."""
        metrics = self._font_manager.current_metrics
        if metrics is None:
            raise EngineError("No font selected")
        font_name = self._font_manager._current  # type: ignore[attr-defined]
        if self._mode_stack.current == ModeKind.HORIZONTAL:
            fix_language(self)  # §1034: ahead of the character (§7)
        char_code = ord(token.char)
        original_tail = char_code
        # §1034 precedes §1038 lookahead: expansion may read \spacefactor
        # (plain's \footnote saves it in an \edef). Use source characters,
        # including each ligature constituent, rather than the ligature code.
        self._update_spacefactor(char_code)
        if not self._font_manager.check_character(font_name, char_code):
            return

        # Ligature loop; `source` keeps the constituents for hyphenation (§4).
        source = [char_code]
        while True:
            next_tok = self._peek_text_character()
            if not (isinstance(next_tok, CharToken)
                    and next_tok.catcode in (Catcode.LETTER, Catcode.OTHER)):
                break
            next_code = ord(next_tok.char)
            if not metrics.has_char(next_code):
                break  # a missing byte terminates shaping; do not diagnose lookahead
            lig = metrics.ligature(char_code, next_code)
            if lig is None:
                break
            next(self._token_iter)  # consume
            self._update_spacefactor(next_code)
            original_tail = next_code
            source.append(next_code)
            char_code = lig

        # Emit CharNode
        node = CharNode(char=char_code, font_name=font_name,
                        source=tuple(source) if len(source) > 1 else ())
        self._append_to_hlist(node)
        # §1039: a paragraph may break after the font's hyphen character, so
        # an empty discretionary follows it, ahead of any font kern.
        if (self._mode_stack.current == ModeKind.HORIZONTAL
                and original_tail == self._font_manager.hyphenchar(font_name)):
            self._append_to_hlist(DiscretionaryNode(pre=(), post=(), nobreak=()))

        # Kern check
        next_tok = self._peek_text_character()
        if (isinstance(next_tok, CharToken)
                and next_tok.catcode in (Catcode.LETTER, Catcode.OTHER)):
            next_code = ord(next_tok.char)
            kern_amount = (metrics.kern(char_code, next_code)
                           if metrics.has_char(next_code) else None)
            if kern_amount is not None and kern_amount != 0:
                self._append_to_hlist(KernNode(width=kern_amount, explicit=False))

    def _peek_text_character(self) -> Token | None:
        r"""Expose a following ``\char`` or ``\chardef`` constant to the lig/kern loop (§1038)."""
        tok = self._expander.peek()
        if isinstance(tok, ControlSequenceToken):
            const = self._register_set.resolve_constant(tok.name)
            if const is not None and const[0] == "chardef":
                next(self._token_iter)
                tok = CharToken(chr(const[1]), Catcode.OTHER)
                self._expander.push_tokens([tok])
                return tok
        if isinstance(tok, ControlSequenceToken) and tok.name == "char":
            from aspose_tex._engine.box_primitives import _check_char_code
            from aspose_tex._engine.dimparser import parse_integer

            next(self._token_iter)
            code = parse_integer(self._expander)
            _check_char_code(code, "\\char")
            tok = CharToken(chr(code), Catcode.OTHER)
            self._expander.push_tokens([tok])
        return tok

    def _handle_space(self, *, normal: bool = False) -> None:
        r"""Process a space token in H mode: insert inter-word GlueNode.

        The glue goes through :meth:`_append_horizontal_glue`, so a control
        space in math mode lands on the math list (§1045).

        Every space token that reaches H mode is appended (TeX §1041): runs of
        input spaces are already collapsed by the tokenizer's state S (§347),
        so two space tokens in a row are deliberate — ``\ \ `` or a macro
        that expands to a space — and each one is a glue.

        Args:
            normal: Ignore the space factor, as for control space ``\ ``
                (§1045 ``append_normal_space``): the font's plain
                interword glue, with no sentence extra space or stretch.
        """
        glue = self._interword_glue(normal=normal)
        if glue is not None:
            self._append_horizontal_glue(GlueNode(glue=glue))

    def _interword_glue(self, *, normal: bool = False) -> Glue | None:
        """Compute existing §1042/§1045 spacing for paragraphs and eager lists."""
        metrics = self._font_manager.current_metrics
        if metrics is None:
            return None
        font_name = self._font_manager._current  # type: ignore[attr-defined]

        sf = 1000 if normal else self._spacefactor
        spaceskip = self._register_set.get_skip(268, _internal=True)
        xspaceskip = self._register_set.get_skip(269, _internal=True)
        if sf >= 2000 and (xspaceskip.width or xspaceskip.stretch or xspaceskip.shrink):
            return xspaceskip
        if spaceskip.width or spaceskip.stretch or spaceskip.shrink:
            # §1042: spaceskip replaces normal glue, then sentence extra
            # space and stretch/shrink scaling apply to that copy.
            glue = Glue(
                spaceskip.width + (self._font_manager.fontdimen(font_name, 7) if sf >= 2000 else 0),
                spaceskip.stretch * sf // 1000,
                spaceskip.stretch_order, spaceskip.shrink * 1000 // sf,
                spaceskip.shrink_order,
            )
            return glue
        if sf >= 2000:
            extra = self._font_manager.fontdimen(font_name, 7)
            space = self._font_manager.fontdimen(font_name, 2) + extra
        else:
            space = self._font_manager.fontdimen(font_name, 2)
        stretch = self._font_manager.fontdimen(font_name, 3)
        shrink = self._font_manager.fontdimen(font_name, 4)

        # Spacefactor stretch/shrink modification (TeX §1042). Both components
        # move, in opposite directions: a sentence space stretches more readily
        # and resists shrinking. Integer floor division mirrors xn_over_d.
        # See — omitting the shrink line mis-set every glue node on any
        # justified line that shrinks and contains a sentence-ending space.
        if sf != 1000:
            stretch = stretch * sf // 1000
            shrink = shrink * 1000 // sf

        return Glue(space, stretch, GlueOrder.NORMAL, shrink, GlueOrder.NORMAL)

    def _exec_control_space(self) -> None:
        r"""Control space ``\ `` — append the current font's normal interword glue.

        TeX §1045 sends ``hmode+ex_space`` and ``mmode+ex_space`` alike to
        ``append_normal_space``: in math mode the glue (``\spaceskip`` or the
        current text font's fontdimens 2-4, never math spacing) goes onto the
        math list, via the math-aware append in :meth:`_handle_space`.
        """
        if self._mode_stack.current in (
            ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL,
            ModeKind.MATH, ModeKind.MATH_DISPLAY,
        ):
            self._handle_space(normal=True)

    def _update_spacefactor(self, char_code: int) -> None:
        """Update spacefactor after typesetting a character (TeX §1034).

        ``adjust_space_factor``: an sfcode of 0 leaves the factor alone (so
        ``x.)`` keeps the sentence 3000), 1..999 sets it outright, 1000 sets
        1000, and above 1000 sets it unless the factor is below 1000.
        """
        sfcode = self._get_sfcode(char_code)
        if sfcode > 1000:
            self._spacefactor = 1000 if self._spacefactor < 1000 else sfcode
        elif sfcode > 0:
            self._spacefactor = sfcode

    def _get_sfcode(self, char_code: int) -> int:
        r"""Return the space factor code for a character.

        Reads the same group-scoped ``CodeArrays`` table that ``\sfcode``
        assignments write, so a user (or format) assignment actually reaches
        §1034. Until this read a private 3-entry dict that
        ``_exec_sfcode`` never touched, which silently dropped every
        ``\sfcode`` assignment — including plain.tex's own
        ``\nonfrenchspacing`` (``:``=2000, ``;``=1500, ``,``=1250,
        ``)``/``'``/``]``=0).
        """
        return self._code_arrays.get_sfcode(char_code)

    def _set_spacefactor(self, value: int | Glue) -> None:
        r"""Set ``\spacefactor`` after registry mode validation."""
        int_value = int(value)
        if int_value < 0:
            raise EngineError("\\spacefactor must be >= 0")
        self._spacefactor = int_value

    def _set_prevdepth(self, value: int | Glue) -> None:
        r"""Set ``\prevdepth`` after registry mode validation."""
        int_value = int(value)
        self._prev_depth = int_value
        frame = self._current_box_frame()
        if frame is not None and frame.vertical:
            return
        self._page_builder._prev_depth = int_value

    def _set_badness(self, value: int) -> None:
        """Record the last hbox/vbox glue-setting badness."""
        self._badness = value

    def _record_last_skip(self, glue: Glue) -> None:
        self._last_skip = glue
        self._last_penalty = 0
        self._last_kern = 0

    @contextmanager
    def _tail_scope(self, builder):
        """Scope a live builder's physical tail, restoring the owner on error."""
        depth = len(self._tail_providers)
        self._tail_providers.append(lambda: builder._nodes[-1] if builder._nodes else None)
        try:
            yield
        finally:
            del self._tail_providers[depth:]

    def _current_list_tail(self):
        """Read only the physical last node of the live list."""
        if self._tail_providers:
            return self._tail_providers[-1]()
        if self._par_list is not None:
            return self._par_list.last_node
        return None

    def _deferred_vertical_tail(self, builder):
        """A running paragraph inside a deferred vbox supersedes its vlist."""
        if self._mode_stack.current == ModeKind.HORIZONTAL and self._par_list is not None:
            return self._par_list.last_node
        return builder._nodes[-1] if builder._nodes else None

    def _outer_tail_cache(self) -> bool:
        return not self._tail_providers and self._mode_stack.current == ModeKind.OUTER_VERTICAL

    def _read_last_skip(self) -> Glue:
        from aspose_tex._engine.math_list import Noad, NoadKind
        tail = self._current_list_tail()
        if isinstance(tail, (GlueNode, LeadersNode)):
            return tail.glue
        if isinstance(tail, Noad) and tail.kind == NoadKind.GLUE:
            if tail.leaders is not None:
                return tail.leaders.glue
            return tail.glue or Glue(tail.glue_value, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
        return self._last_skip if self._outer_tail_cache() else Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)

    def _read_last_kern(self) -> int:
        from aspose_tex._engine.math_list import Noad, NoadKind
        tail = self._current_list_tail()
        if isinstance(tail, KernNode) or (isinstance(tail, Noad) and tail.kind == NoadKind.KERN):
            return tail.width
        return self._last_kern if self._outer_tail_cache() else 0

    def _read_last_penalty(self) -> int:
        from aspose_tex._engine.math_list import Noad, NoadKind
        tail = self._current_list_tail()
        if isinstance(tail, Noad) and tail.kind == NoadKind.PENALTY:
            return tail.penalty
        if isinstance(tail, PenaltyNode):
            return tail.penalty
        return self._last_penalty if self._outer_tail_cache() else 0

    def _last_skip_unit(self) -> str:
        """Use mu only for an actual mu-glue tail, never from mode alone."""
        from aspose_tex._engine.math_list import Noad, NoadKind
        tail = self._current_list_tail()
        return "mu" if (isinstance(tail, Noad) and tail.kind == NoadKind.GLUE
                        and tail.mu_glue and not tail.nonscript) else "pt"

    def _record_last_penalty(self, penalty: int) -> None:
        self._last_skip = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
        self._last_penalty = penalty
        self._last_kern = 0

    def _record_last_kern(self, kern: int) -> None:
        self._last_skip = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
        self._last_penalty = 0
        self._last_kern = kern

    def _record_non_discardable(self) -> None:
        self._last_skip = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
        self._last_penalty = 0
        self._last_kern = 0

    def _contribute(self, node) -> None:
        """Contribute to the owning vertical list, preserving the page cache."""
        frame = self._current_box_frame()
        if frame is not None and frame.vertical:
            if isinstance(node, (HlistNode, VlistNode)):
                from aspose_tex._engine.box_builder import compute_interline_glue
                glue = compute_interline_glue(
                    prev_depth=self._prev_depth, next_height=node.height,
                    baselineskip=self._get_named_skip("baselineskip"),
                    lineskip=self._get_named_skip("lineskip"),
                    lineskiplimit=self._get_named_dimen("lineskiplimit"),
                )
                if glue is not None:
                    frame.builder._nodes.append(GlueNode(glue))
            frame.builder._nodes.append(node)
            if isinstance(node, (HlistNode, VlistNode)):
                self._prev_depth = node.depth
            elif isinstance(node, RuleNode):
                self._prev_depth = _PREVDEPTH_SENTINEL
            return
        if isinstance(node, (GlueNode, LeadersNode)):
            self._record_last_skip(node.glue)
        elif isinstance(node, PenaltyNode):
            self._record_last_penalty(node.penalty)
        elif isinstance(node, KernNode):
            self._record_last_kern(node.width)
        else:
            self._record_non_discardable()
        self._page_builder.contribute(node)
        if isinstance(node, (HlistNode, VlistNode)):
            self._prev_depth = node.depth
        elif isinstance(node, RuleNode):
            # TeX:The Program §679 (contribute_rule):
            #   prev_depth <- ignore_depth (-1000 pt sentinel)
            # Mirrors PageBuilder._prev_depth update inside contribute()
            # and matches exec_vbox's in-vbox
            # _track_rule / _track_splice convention so the
            # \prevdepth named-parameter registry read returns -1000 pt
            # after a vertical-mode \hrule regardless of whether the
            # rule contributed in outer-V-mode or inside a \vbox{...}
            # group.  See v6 §Component 2.
            self._prev_depth = _PREVDEPTH_SENTINEL

    def _receives_outer_vlist(self) -> bool:
        """Whether vertical material now lands on the main vertical list."""
        return (self._mode_stack.current == ModeKind.OUTER_VERTICAL
                and self._current_box_frame() is None)

    def _build_page_if_outer(self) -> None:
        """Run ``build_page`` when the current list is the main vertical list.

        TeX calls ``build_page`` only at fixed places, and only in outer
        vertical mode.  It must be the last thing its
        caller does: a token-list ``\\output`` may open its nest inside it.
        """
        if self._receives_outer_vlist():
            self._page_builder.build_page()

    def _open_output_nest(self) -> None:
        r"""Give the token-list ``\output`` its own vertical nest (§1025).

        TeX's ``fire_up`` does ``push_nest; mode:=-vmode;
        prev_depth:=ignore_depth``: what the routine contributes is collected
        apart from the interrupted list and handed back to the page builder
        when the routine ends.
        """
        from aspose_tex._engine.box_builder import VBoxBuilder
        from aspose_tex._engine.box_primitives import _badness_sink

        builder = VBoxBuilder(self._font_manager, badness_sink=_badness_sink(self._expander))
        frame = _BoxBuildFrame(
            builder=builder, vertical=True, group_depth=-1, destination=None,
            target=None, spread=None, vtop=False, saved_par_list=self._par_list,
            restore_mode_depth=self._mode_stack.depth,
            restore_tail_depth=len(self._tail_providers),
            saved_prev_depth=self._prev_depth, saved_spacefactor=self._spacefactor,
            saved_prev_graf=self._prev_graf, saved_last_line=self._last_paragraph_line,
            saved_math_state=self._isolate_vertical_math(),
        )
        self._box_construction_stack.append(frame)
        self._output_frame = frame
        self._mode_stack.push(ModeKind.INTERNAL_VERTICAL)
        self._par_list = None
        self._prev_depth = _PREVDEPTH_SENTINEL
        self._prev_graf = 0
        self._tail_providers.append(lambda: self._deferred_vertical_tail(builder))

    def _end_output_routine(self) -> None:
        r"""Close the ``\output`` nest and resume the page builder (§1026)."""
        frame = self._output_frame
        if frame is None:
            self._page_builder.finish_output_cycle(None)
            return
        if (self._mode_stack.current == ModeKind.HORIZONTAL
                and self._current_box_frame() is frame):
            self._end_paragraph(build=False)  # §1026 end_graf
        if frame in self._box_construction_stack:
            del self._box_construction_stack[self._box_construction_stack.index(frame):]
        while self._mode_stack.depth > frame.restore_mode_depth:
            self._mode_stack.pop()
        self._par_list = frame.saved_par_list
        self._prev_depth = frame.saved_prev_depth
        self._spacefactor = frame.saved_spacefactor
        self._prev_graf = frame.saved_prev_graf
        self._last_paragraph_line = frame.saved_last_line
        del self._tail_providers[frame.restore_tail_depth:]
        self._restore_vertical_math(frame.saved_math_state)
        self._output_frame = None
        self._page_builder.finish_output_cycle(list(frame.builder._nodes))

    def _append_to_hlist(self, node) -> None:
        """Append to the horizontal list; tail reads are live."""
        if self._par_list is None:
            raise EngineError("horizontal list is not active")
        self._par_list.append(node)

    def _append_horizontal_glue(self, node: GlueNode) -> None:
        r"""Append horizontal glue to the math list in math mode, else the hlist.

        TeX §1171: in ``mmode`` the horizontal glue primitives (``\hskip``,
        ``\hfil``, ``\hfill``, ``\hss``, ``\hfilneg``) run ``append_glue``,
        which appends a ``glue_node`` to the *current math list*, so the glue
        keeps its written position relative to the formula's atoms.  Appending
        it to the enclosing horizontal list instead makes every such glue jump
        ahead of the whole formula, because the formula is spliced into that
        list only at the ``$``-close — which put both of ``\displaylines``'
        centring ``\hfil``s on the same side of the row and doubled its
        horizontal offset.

        The math-builder half of the predicate is load-bearing:
        ``run_inline_math_in_box`` leaves MATH on the mode stack while it pumps
        tokens, so testing the mode alone would misroute glue at the boundary
        where the builder has just closed.

        Args:
            node: The glue node to append.
        """
        if (
            self._mode_stack.current in (ModeKind.MATH, ModeKind.MATH_DISPLAY)
            and self._math_builder is not None
        ):
            self._math_builder.add_glue(node.glue)
            return
        self._append_to_hlist(node)

    def _build_internal_quantities(self) -> InternalQuantityRegistry:
        """Construct the internal-quantity registry."""
        registry = InternalQuantityRegistry(self._mode_stack)
        hmode = frozenset({ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL})
        vmode = frozenset({ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL})

        registry.register(
            "spacefactor",
            QuantityKind.INT,
            getter=lambda: self._spacefactor,
            setter=self._set_spacefactor,
            allowed_modes=hmode,
        )
        registry.register(
            "prevdepth",
            QuantityKind.DIMEN,
            getter=lambda: self._prev_depth,
            setter=self._set_prevdepth,
            allowed_modes=vmode,
        )
        # §422: \prevgraf reads the enclosing vertical list's value in any
        # mode, so a paragraph after a display sees the lines so far.
        registry.register("prevgraf", QuantityKind.INT, getter=lambda: self._prev_graf)
        # \parshape is assigned by its primitive; this entry only reads the
        # live owner's line count (§423).
        registry.register(
            "parshape", QuantityKind.INT,
            getter=lambda: len(self._parshape or ()),
        )
        registry.register("badness", QuantityKind.INT, getter=lambda: self._badness)
        registry.register("lastskip", QuantityKind.SKIP, getter=self._read_last_skip,
                          glue_unit_getter=self._last_skip_unit)
        registry.register("lastpenalty", QuantityKind.INT, getter=self._read_last_penalty)
        registry.register("lastkern", QuantityKind.DIMEN, getter=self._read_last_kern)
        registry.register(
            "inputlineno",
            QuantityKind.INT,
            getter=lambda: self._reader.current_location.line,
        )
        registry.register("pagetotal", QuantityKind.DIMEN, getter=lambda: self._page_builder.page_total)
        registry.register("pagegoal", QuantityKind.DIMEN, getter=lambda: self._page_builder.page_goal)
        registry.register(
            "pagestretch",
            QuantityKind.DIMEN,
            getter=lambda: self._page_builder.page_stretch,
        )
        registry.register(
            "pagefilstretch",
            QuantityKind.DIMEN,
            getter=lambda: self._page_builder.page_filstretch,
        )
        registry.register(
            "pagefillstretch",
            QuantityKind.DIMEN,
            getter=lambda: self._page_builder.page_fillstretch,
        )
        registry.register(
            "pagefilllstretch",
            QuantityKind.DIMEN,
            getter=lambda: self._page_builder.page_filllstretch,
        )
        registry.register("pageshrink", QuantityKind.DIMEN, getter=lambda: self._page_builder.page_shrink)
        registry.register("pagedepth", QuantityKind.DIMEN, getter=lambda: self._page_builder.page_depth)
        # §1246 set_page_int: both are assignable, outside any save stack.
        registry.register(
            "deadcycles",
            QuantityKind.INT,
            getter=lambda: self._page_builder.dead_cycles,
            setter=lambda value: setattr(self._page_builder, "dead_cycles", int(value)),
        )
        registry.register(
            "insertpenalties",
            QuantityKind.INT,
            getter=lambda: self._page_builder.insert_penalties,
            setter=lambda value: setattr(self._page_builder, "insert_penalties", int(value)),
        )
        return registry

    # ------------------------------------------------------------------
    # Paragraph commands
    # ------------------------------------------------------------------

    def _begin_paragraph(self, indent: bool = True, *, par_skip: bool = True) -> None:
        r"""Switch from vertical to horizontal mode and start a new paragraph.

        TeX §1091 ``new_graf``: an indented paragraph starts with an empty box
        as wide as the *current* ``\parindent`` (zero and negative included),
        and the *current* ``\parskip`` goes on the vertical list ahead of it.
        The glue is contributed now (on a box's list only when that list is
        not empty), so a ``\parskip`` assignment inside the paragraph only
        reaches the next one, and on the main list ``build_page`` runs after
        ``\everypar`` is queued.  ``\prevgraf`` restarts at zero,
        and ``\everypar`` is inserted after the indent box, ahead of any token
        the caller backed up.

        Args:
            indent:   ``False`` for ``\noindent`` (no indent box).
            par_skip: ``False`` when the paragraph is resumed after a display
                rather than started (§1200/§1206: no ``new_graf``, so no
                ``\parskip``, no ``\everypar`` and ``\prevgraf`` kept).
        """
        outer = self._receives_outer_vlist()
        if par_skip:
            self._prev_graf = 0
            frame = self._current_box_frame()
            if frame is None or not frame.vertical or frame.builder._nodes:
                # §1091: `if (mode=vmode)or(head<>tail)` - at the top of the
                # page §1000 discards it.
                self._contribute(GlueNode(self._get_named_skip("parskip")))
        self._mode_stack.push(ModeKind.HORIZONTAL)
        parindent = self._get_named_dimen("parindent") if indent else None
        # §1091 / §1200: the language and minima the hyphenation step starts from.
        self._par_list = ParagraphList(
            parindent=parindent,
            language=normalize_language(self._get_named_int("language")),
            left_min=norm_min(self._get_named_int("lefthyphenmin")),
            right_min=norm_min(self._get_named_int("righthyphenmin")),
        )
        # push_nest's mode_line: the "a" of "in paragraph at lines a--b" (§663).
        self._par_list.start_line = self._reader.current_location.line
        self._spacefactor = 1000
        if par_skip:
            self._push_toks_if_any(257)  # \everypar
            if outer:
                self._page_builder.build_page()

    def _insert_par_before(self, token: Token) -> None:
        r"""Back-input *token* behind the current ``\par`` (§1095 head_for_vmode).

        A vertical command met in a paragraph is read again after ``\par``,
        so a redefined ``\par`` (plain's ``\endgraf`` idiom) runs exactly as
        in TeX.

        Raises:
            EngineError: if ``\par`` keeps failing to end the paragraph.
        """
        self._head_for_vmode_count += 1
        if self._head_for_vmode_count > _HEAD_FOR_VMODE_LIMIT:
            self._head_for_vmode_count = 0
            raise EngineError(
                f"\\par did not end the paragraph before \\{self._expander._diagnostic_cs_name(token)}"
            )
        self._expander.push_tokens([ControlSequenceToken("par"), token])

    def _back_input_new_graf(self, token: Token) -> None:
        r"""Start an indented paragraph for *token* met in vertical mode (§1090).

        TeX's ``back_input; new_graf(true)``: the token goes back to the input
        and is read again in the new paragraph, so a character, ``$``,
        ``\hskip`` or ``\unhbox`` (plain's ``\leavevmode``) lands after the
        ``\parindent`` box.

        Args:
            token: The token that cannot be handled in vertical mode.
        """
        self._expander.push_tokens([token])
        self._begin_paragraph()

    def _exec_par_cmd(self) -> None:
        """\\par — end the current paragraph; forbidden in math mode.

        Raises:
            EngineError: In math mode (TeX §1046/§1047 ``mmode+par_end`` runs
                ``insert_dollar_sign``: "Missing $ inserted") — a blank line
                inside ``$…$`` would otherwise lose material silently.
        """
        if (
            self._mode_stack.current in (ModeKind.MATH, ModeKind.MATH_DISPLAY)
            and self._math_builder is not None
        ):
            raise EngineError("Missing $ inserted (\\par is not allowed in math mode)")
        if self._mode_stack.current == ModeKind.HORIZONTAL:
            self._end_paragraph()
        elif self._mode_stack.current in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
            self._normal_paragraph()  # §1070 vmode+par_end
            self._build_page_if_outer()

    def _exec_indent(self) -> None:
        """\\indent — start paragraph with indentation."""
        if self._mode_stack.current in (
            ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL,
        ):
            self._begin_paragraph(indent=True)
        else:
            box = HlistNode(
                list=[], width=self._get_named_dimen("parindent"), height=0, depth=0,
                shift_amount=0, glue_sign=GlueSign.NORMAL,
                glue_order=GlueOrder.NORMAL, glue_set=0.0,
            )
            if self._mode_stack.current in (ModeKind.MATH, ModeKind.MATH_DISPLAY):
                self._math_builder.add_box(box)
            else:
                self._append_to_hlist(box)
                self._spacefactor = 1000

    def _exec_noindent(self) -> None:
        """\\noindent — start paragraph without indentation."""
        if self._mode_stack.current in (
            ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL,
        ):
            self._begin_paragraph(indent=False)

    def _end_paragraph(self, *, normal: bool = True, build: bool = True) -> None:
        """Finalise the current paragraph: line-break and contribute to page builder.

        Args:
            normal: Run ``normal_paragraph`` afterwards (§1096).  A display
                that interrupts the paragraph passes ``False``: §1145 breaks
                the lines but keeps the paragraph shape for the rest, and does
                not build the page.
            build:  Run ``build_page`` when the lines landed on the main list
                (§1094).  Callers that keep contributing afterwards pass
                ``False`` and trigger the build themselves.
        """
        if self._par_list is None:
            return

        diagnostics: list[str] = []
        disc_breaks: list[bool] = []
        par_list = self._par_list

        def hyphenate(nodes: list) -> list:
            # P7: entering the second pass closes \patterns (§891 init_trie).
            self._hyphenation.freeze()
            return hyphenate_paragraph(nodes, HyphenationContext(
                store=self._hyphenation,
                font_manager=self._font_manager,
                lccode=self._code_arrays.get_lccode,
                uchyph=self._get_named_int("uchyph"),
                language=par_list.language,
                left_min=par_list.left_min,
                right_min=par_list.right_min,
                missing_character=self._report_missing_character,
            ))

        line_reports: list[tuple[str, list]] = []
        lines = exec_par(
            par_list, self._linebreak_params(), self._font_manager,
            warnings=diagnostics, disc_breaks=disc_breaks, hyphenate=hyphenate,
            line_reports=line_reports,
        )
        for message in diagnostics:
            if message.startswith('! Infinite glue shrinkage'):
                # §824 replaces the eqtb glue pointer without an assignment
                # save: existing group restoration still owns its saved value.
                for name in ('leftskip', 'rightskip'):
                    glue = self._get_named_skip(name)
                    if glue.shrink and glue.shrink_order != GlueOrder.NORMAL:
                        entry = self._named_params.lookup(name)
                        self._register_set._bank.skip[entry.slot] = dataclasses.replace(
                            glue, shrink_order=GlueOrder.NORMAL)
                self._messages.append(message)
                logging.getLogger('aspose_tex').warning(message)
                continue
            category = OverfullBoxWarning if message.startswith("Overfull") else UnderfullBoxWarning
            warnings.warn(message, category, stacklevel=2)
        # §8: TeX's report of each such line (§663); the box display
        # that follows it in TeX's log is a known gap.
        for header, material in line_reports:
            for text in (
                f"{header} in paragraph at lines {par_list.start_line}--"
                f"{self._reader.current_location.line}",
                short_display(material, self._font_manager),
            ):
                logging.getLogger("aspose_tex").info(text)
                self._messages.append(text)

        for index, line in enumerate(lines):
            adjustments = self._extract_adjustments(line)
            self._contribute(line)
            if adjustments:
                self._splice_vertical_nodes(adjustments)
            if index < len(lines) - 1:
                penalty = self._interline_penalty(
                    index, len(lines), broken=disc_breaks[index], display_follows=not normal,
                )
                if penalty != 0:
                    self._contribute(PenaltyNode(penalty))

        # record the paragraph's last line box so a display that
        # interrupts the paragraph (`\emit_display`) can measure \predisplaysize
        # (§1146) from it.  Cleared by the reader after use.
        self._last_paragraph_line = lines[-1] if lines else None

        self._prev_graf += len(lines)

        self._par_list = None
        self._mode_stack.pop()
        self._head_for_vmode_count = 0
        if normal:
            self._normal_paragraph()  # §1096 end_graf
            if build:
                self._build_page_if_outer()  # §1094

    def _interline_penalty(
        self, index: int, count: int, *, broken: bool, display_follows: bool,
    ) -> int:
        r"""Return the §890 penalty between line ``index`` and the next one.

        ``cur_line`` counts on from ``\prevgraf`` (still its value before this
        paragraph's lines are added), so the first line after a display —
        which leaves ``\prevgraf`` at lines + 3 — gets ``\clubpenalty`` too
        

        Args:
            index: Zero-based line index within this paragraph piece.
            count: Number of lines in this paragraph piece.
            broken: Whether line ``index`` ends at a discretionary break.
            display_follows: Whether a display interrupts the paragraph after
                its last line (``\displaywidowpenalty`` replaces
                ``\widowpenalty``).

        Returns:
            The penalty sum; 0 means no penalty node is contributed.
        """
        cur_line = self._prev_graf + index + 1
        best_line = self._prev_graf + count + 1
        penalty = self._get_named_int("interlinepenalty")
        if cur_line == self._prev_graf + 1:
            penalty += self._get_named_int("clubpenalty")
        if cur_line + 2 == best_line:
            penalty += self._get_named_int(
                "displaywidowpenalty" if display_follows else "widowpenalty",
            )
        if broken:
            penalty += self._get_named_int("brokenpenalty")
        return penalty

    # ------------------------------------------------------------------
    # Vertical mode items
    # ------------------------------------------------------------------

    def _head_for_vmode(self) -> None:
        r"""End an open paragraph before a vertical-mode command (§1094-§1095).

        TeX's ``head_for_vmode``: ``\vskip``, ``\vfil`` and friends,
        ``\unvbox`` and ``\hrule`` met in a paragraph end it first, so the
        vertical material follows the paragraph's lines instead of being
        contributed ahead of them.  Restricted horizontal mode is left alone.
        """
        if self._mode_stack.current == ModeKind.HORIZONTAL:
            self._end_paragraph(build=False)

    def _contribute_vertical_glue(self, node: GlueNode) -> None:
        """Contribute vertical glue, ending an open paragraph first (§1094)."""
        self._head_for_vmode()
        self._contribute(node)

    def _exec_vskip(self) -> None:
        """\\vskip <glue> — insert vertical glue."""
        from aspose_tex._engine.dimparser import parse_glue
        glue = parse_glue(self._expander)
        self._contribute_vertical_glue(GlueNode(glue=glue))

    def _exec_vadjust(self) -> None:
        r"""Execute ``\vadjust{...}`` in the owning horizontal or math list."""
        from aspose_tex._engine.nodes import AdjustNode
        mode = self._mode_stack.current
        if mode in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
            raise EngineError("\\vadjust in vertical mode")
        material = self._execute_vbox().list
        # insert_group uses splitmaxdepth, zero by default in plain TeX.
        node = AdjustNode(list=material)
        if mode in (ModeKind.MATH, ModeKind.MATH_DISPLAY):
            self._math_builder.add_adjustment(node)
        else:
            self._append_to_hlist(node)

    @staticmethod
    def _extract_adjustments(box) -> list:
        """Remove direct carriers only; nested ordinary hboxes retain them."""
        from aspose_tex._engine.nodes import AdjustNode, InsertNode, MarkNode
        material = []
        kept = []
        for node in box.list:
            if isinstance(node, AdjustNode):
                material.extend(node.list)
            elif isinstance(node, (InsertNode, MarkNode)):
                material.append(node)
            else:
                kept.append(node)
        box.list = kept
        return material

    def _exec_kern_cmd(self) -> None:
        """\\kern <dimen> — mode-aware kern."""
        from aspose_tex._engine.dimparser import parse_dimen
        amount = parse_dimen(self._expander)
        mode = self._mode_stack.current
        if mode in (ModeKind.MATH, ModeKind.MATH_DISPLAY) and self._math_builder is not None:
            # TeX §1061 append_kern: in mmode the kern joins the current math
            # list, in place among the atoms (same reasoning as
            # _append_horizontal_glue).
            self._math_builder.add_kern(amount)
            return
        if mode in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
            self._append_to_hlist(KernNode(width=amount, explicit=True))
        else:
            self._contribute(KernNode(width=amount, explicit=True))

    def _exec_italic_correction(self) -> None:
        """\\/ — append the italic correction of the preceding character.

        TeX:The Program §1112 (``ital_corr``): if the tail of the current
        horizontal list is a char node, append a kern whose width is that
        character's ``char_italic`` — the *per-character* italic correction
        from the TFM italic table.  In every other horizontal position ``\\/``
        is a no-op: at the start of a list or after a kern/glue/box.  In math
        mode (§1111 ``mmode+ital_corr``) it appends a zero kern — the italic
        corrections there come from ``mlist_to_hlist`` (§H) — which
        separates the neighbouring symbols, so ``$\\rm f\\/i$`` forms no
        ligature.

        Note this is NOT ``\\fontdimen1\\font``.  ``\\fontdimen1`` is the
        font-wide slant *ratio* (0.25 for cmti10, 0.0 for cmr10); the italic
        correction differs per glyph within one font — measured against MiKTeX
        etex 24.4, cmti10 ``f`` is 2.11945pt but ``l`` is 1.03334pt, and cmr10
        ``f`` is 0.77779pt where ``\\fontdimen1`` is zero.  A ligature collapses
        into a single CharNode carrying the ligature's own code, so the
        correction is taken from the resulting glyph, as TeX does.
        """
        if self._mode_stack.current in (ModeKind.MATH, ModeKind.MATH_DISPLAY):
            if self._math_builder is not None:
                self._math_builder.add_kern(0)
            return
        if self._par_list is None:
            return
        last = self._par_list.last_node
        if not isinstance(last, CharNode):
            return
        metrics = self._font_manager.get_metrics(last.font_name)
        if metrics is None:
            return
        self._append_to_hlist(
            KernNode(width=metrics.char_metrics(last.char).italic,
                     explicit=False, italic_correction=True),
        )

    def _exec_hrule(self) -> None:
        """\\hrule [width <d>] [height <d>] [depth <d>]."""
        if self._mode_stack.current in (ModeKind.MATH, ModeKind.MATH_DISPLAY):
            raise EngineError("\\hrule is not allowed in math mode")
        from aspose_tex._engine.dimparser import _scan_keyword, parse_dimen
        width = RUNNING_DIMEN
        height = 26_214   # 0.4pt
        depth = 0
        while True:
            if _scan_keyword(self._expander, "width"):
                width = parse_dimen(self._expander)
            elif _scan_keyword(self._expander, "height"):
                height = parse_dimen(self._expander)
            elif _scan_keyword(self._expander, "depth"):
                depth = parse_dimen(self._expander)
            else:
                break
        rule = RuleNode(width=width, height=height, depth=depth)
        self._head_for_vmode()
        self._contribute(rule)

    def _exec_vrule_cmd(self) -> None:
        """\\vrule [width <d>] [height <d>] [depth <d>]."""
        from aspose_tex._engine.dimparser import _scan_keyword, parse_dimen
        width = 26_214   # 0.4pt
        height = RUNNING_DIMEN
        depth = RUNNING_DIMEN
        while True:
            if _scan_keyword(self._expander, "width"):
                width = parse_dimen(self._expander)
            elif _scan_keyword(self._expander, "height"):
                height = parse_dimen(self._expander)
            elif _scan_keyword(self._expander, "depth"):
                depth = parse_dimen(self._expander)
            else:
                break
        rule = RuleNode(width=width, height=height, depth=depth)
        mode = self._mode_stack.current
        if mode in (ModeKind.MATH, ModeKind.MATH_DISPLAY):
            self._math_builder.add_rule(rule)
        elif mode in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
            self._append_to_hlist(rule)
        else:
            self._contribute(rule)

    def _exec_penalty_cmd(self) -> None:
        """\\penalty <number> — mode-aware penalty."""
        from aspose_tex._engine.dimparser import parse_integer
        val = parse_integer(self._expander)
        mode = self._mode_stack.current
        if mode in (ModeKind.MATH, ModeKind.MATH_DISPLAY):
            self._math_builder.add_penalty(val)
        elif mode in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
            exec_penalty(val, self._par_list)  # type: ignore[arg-type]
            self._record_last_penalty(val)
        else:
            self._contribute(PenaltyNode(penalty=val))
            self._build_page_if_outer()  # §1103

    # ------------------------------------------------------------------
    # Code-array primitives (§5b —)
    # ------------------------------------------------------------------

    def _exec_catcode(self) -> None:
        """``\\catcode<8-bit char>=<int 0..15>``."""
        from aspose_tex._engine.dimparser import parse_integer
        char_code = parse_integer(self._expander, allow_negative=False)
        if not (0 <= char_code <= 255):
            raise EngineError(f"\\catcode: char code {char_code} out of range 0-255")
        self._eat_optional_equals()
        value = parse_integer(self._expander, allow_negative=False)
        if not (0 <= value <= 15):
            raise EngineError(f"\\catcode value {value} out of range 0-15")
        self._catcodes.set(chr(char_code), Catcode(value))
        self._expander.fire_after_assignment()

    def _exec_mathcode(self) -> None:
        """``\\mathcode<8-bit char>=<int 0..0x8000>``."""
        from aspose_tex._engine.dimparser import parse_integer
        char_code = parse_integer(self._expander, allow_negative=False)
        self._eat_optional_equals()
        value = parse_integer(self._expander, allow_negative=False)
        self._code_arrays.set_mathcode(char_code, value)
        self._expander.fire_after_assignment()

    def _exec_delcode(self) -> None:
        """``\\delcode<8-bit char>=<int -1..0xFFFFFF>``."""
        from aspose_tex._engine.dimparser import parse_integer
        char_code = parse_integer(self._expander, allow_negative=False)
        self._eat_optional_equals()
        value = parse_integer(self._expander)  # may be -1
        self._code_arrays.set_delcode(char_code, value)
        self._expander.fire_after_assignment()

    def _exec_sfcode(self) -> None:
        """``\\sfcode<8-bit char>=<int 0..32767>``."""
        from aspose_tex._engine.dimparser import parse_integer
        char_code = parse_integer(self._expander, allow_negative=False)
        self._eat_optional_equals()
        value = parse_integer(self._expander, allow_negative=False)
        self._code_arrays.set_sfcode(char_code, value)
        self._expander.fire_after_assignment()

    def _exec_lccode(self) -> None:
        """``\\lccode<8-bit char>=<int 0..255>``."""
        from aspose_tex._engine.dimparser import parse_integer
        char_code = parse_integer(self._expander, allow_negative=False)
        self._eat_optional_equals()
        value = parse_integer(self._expander, allow_negative=False)
        self._code_arrays.set_lccode(char_code, value)
        self._expander.fire_after_assignment()

    def _exec_uccode(self) -> None:
        """``\\uccode<8-bit char>=<int 0..255>``."""
        from aspose_tex._engine.dimparser import parse_integer
        char_code = parse_integer(self._expander, allow_negative=False)
        self._eat_optional_equals()
        value = parse_integer(self._expander, allow_negative=False)
        self._code_arrays.set_uccode(char_code, value)
        self._expander.fire_after_assignment()

    def _eat_optional_equals(self) -> None:
        """Consume an optional ``=`` token (with surrounding spaces)."""
        tok = self._expander.peek()
        while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
            self._next_token()
            tok = self._expander.peek()
        if isinstance(tok, CharToken) and tok.char == "=" and tok.catcode == Catcode.OTHER:
            self._next_token()

    # ------------------------------------------------------------------
    # Box primitives (delegated)
    # ------------------------------------------------------------------

    def _exec_hbox_cmd(self) -> None:
        """\\hbox — build an hbox and add to current list.

        if the box keyword (and any ``to``/``spread``) is followed
        by a begin-group (``{`` or ``\\bgroup``), open a deferred-close box-build
        frame; the eager ``exec_hbox`` scanner stays the fast path otherwise.
        """
        from aspose_tex._engine.box_primitives import _scan_box_keyword, exec_hbox
        adjusted = self._mode_stack.current in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL)
        destination = self._deliver_adjusted_hbox if adjusted else self._add_box_to_current_list
        tw, sp = _scan_box_keyword(self._expander)
        if self._peek_box_begin_group():
            self._open_group_box(
                vertical=False, vtop=False, target=tw, spread=sp,
                destination=destination,
            )
            return
        box = exec_hbox(self._expander, self._font_manager,
                        self._group_stack, self._box_regs,
                        target_width=tw, spread=sp)
        destination(box)

    def _deliver_adjusted_hbox(self, box: HlistNode) -> None:
        """Deliver a newly built vertical-list hbox and its §655 adjustments."""
        material = self._extract_adjustments(box)
        self._contribute(box)
        self._splice_vertical_nodes(material)
        self._build_page_if_outer()  # §1076: build only after the adjustments.

    def _exec_vbox_cmd(self) -> None:
        """\\vbox — build a vbox and add to current list (open-group)."""
        from aspose_tex._engine.box_primitives import _scan_box_keyword, exec_vbox
        th, sp = _scan_box_keyword(self._expander)
        if self._peek_box_begin_group():
            self._open_group_box(
                vertical=True, vtop=False, target=th, spread=sp,
                destination=self._add_box_to_current_list,
            )
            return
        box = exec_vbox(self._expander, self._font_manager,
                        self._group_stack, self._box_regs,
                        target_height=th, spread=sp)
        self._add_box_to_current_list(box)

    def _exec_vtop_cmd(self) -> None:
        """\\vtop — build a vtop and add to current list (open-group)."""
        from aspose_tex._engine.box_primitives import _scan_box_keyword, exec_vtop
        th, sp = _scan_box_keyword(self._expander)
        if self._peek_box_begin_group():
            self._open_group_box(
                vertical=True, vtop=True, target=th, spread=sp,
                destination=self._add_box_to_current_list,
            )
            return
        box = exec_vtop(self._expander, self._font_manager,
                        self._group_stack, self._box_regs,
                        target_height=th, spread=sp)
        self._add_box_to_current_list(box)

    def _exec_setbox_cmd(self) -> None:
        """\\setbox<n>=<box> — assign a box register.

        ``\\setbox<n>=\\hbox\\bgroup`` (begin-group after the box
        keyword) opens a deferred-close box-build frame whose destination writes
        register *n*; the eager ``_scan_box_value`` path stays for literal-brace
        ``\\setbox<n>=\\hbox{…}`` and ``\\box``/``\\copy``/``\\vsplit`` values.
        """
        from aspose_tex._engine.box_primitives import _scan_box_keyword
        from aspose_tex._engine.dimparser import parse_integer
        idx = parse_integer(self._expander)
        global_ = self._group_stack.is_global_pending
        self._eat_optional_equals()

        # Q2 lookahead: \hbox/\vbox/\vtop immediately followed (after optional
        # to/spread) by a begin-group → open-group frame writing register idx.
        tok = self._expander.peek()
        while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
            self._next_token()
            tok = self._expander.peek()
        if isinstance(tok, ControlSequenceToken) and tok.name in ("hbox", "vbox", "vtop"):
            self._next_token()  # consume the box keyword
            tw, sp = _scan_box_keyword(self._expander)
            if self._peek_box_begin_group():
                vertical = tok.name in ("vbox", "vtop")
                self._group_stack.consume_global()

                def _deliver(box, _idx=idx, _g=global_):
                    self._box_regs.setbox(_idx, box, global_=_g)

                self._open_group_box(
                    vertical=vertical, vtop=tok.name == "vtop",
                    target=tw, spread=sp, destination=_deliver,
                )
                self._expander.fire_after_assignment()
                return
            # Not open-group: build eagerly with the keywords already scanned.
            self._group_stack.consume_global()
            pending = self._expander._after_assignment_token
            if pending is not None:
                self._expander._after_assignment_token = None
                opening = self._next_token()
                self._expander.push_tokens([opening, pending])
            box = self._build_eager_box(tok.name, tw, sp)
            self._box_regs.setbox(idx, box, global_=global_)
            return

        box = self._scan_box_value("\\setbox")
        self._box_regs.setbox(idx, box, global_=global_)
        self._group_stack.consume_global()
        self._expander.fire_after_assignment()

    def _build_eager_box(self, name: str, tw: int | None, sp: int | None):
        """Build an \\hbox/\\vbox/\\vtop eagerly (keywords already scanned)."""
        from aspose_tex._engine.box_primitives import exec_hbox, exec_vbox, exec_vtop
        if name == "hbox":
            return exec_hbox(self._expander, self._font_manager, self._group_stack,
                             self._box_regs, target_width=tw, spread=sp)
        if name == "vbox":
            return exec_vbox(self._expander, self._font_manager, self._group_stack,
                             self._box_regs, target_height=tw, spread=sp)
        return exec_vtop(self._expander, self._font_manager, self._group_stack,
                         self._box_regs, target_height=tw, spread=sp)

    def _scan_box_value(self, command: str, *, adjustments: list | None = None) -> HlistNode | VlistNode | None:
        """Scan a box-producing primitive for ``\\setbox`` and movers."""
        from aspose_tex._engine.box_primitives import (
            _scan_box_keyword,
            exec_hbox,
            exec_vbox,
            exec_vsplit,
            exec_vtop,
        )
        tok = self._next_token()
        while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
            tok = self._next_token()
        if not isinstance(tok, ControlSequenceToken):
            raise EngineError(f"{command}: expected box primitive, got {tok!r}")
        if tok.name == "hbox":
            tw, sp = _scan_box_keyword(self._expander)
            box = exec_hbox(
                self._expander, self._font_manager, self._group_stack,
                self._box_regs, target_width=tw, spread=sp,
            )
            if adjustments is not None:
                adjustments.extend(self._extract_adjustments(box))
            return box
        if tok.name == "vbox":
            th, sp = _scan_box_keyword(self._expander)
            return exec_vbox(
                self._expander, self._font_manager, self._group_stack,
                self._box_regs, target_height=th, spread=sp,
            )
        if tok.name == "vtop":
            th, sp = _scan_box_keyword(self._expander)
            return exec_vtop(
                self._expander, self._font_manager, self._group_stack,
                self._box_regs, target_height=th, spread=sp,
            )
        if tok.name == "box":
            from aspose_tex._engine.dimparser import parse_integer
            return self._box_regs.getbox(parse_integer(self._expander))
        if tok.name == "copy":
            from aspose_tex._engine.dimparser import parse_integer
            return self._box_regs.copybox(parse_integer(self._expander))
        if tok.name == "lastbox":
            return self._remove_last_box()
        if tok.name == "vsplit":
            entry = self._named_params.lookup("splittopskip")
            splittopskip = (
                self._register_set.get_skip(entry.slot, _internal=True)
                if entry is not None else Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
            )
            return exec_vsplit(
                self._expander,
                self._box_regs,
                splittopskip=splittopskip,
                split_capture_callback=self._split_capture_callback,
            )
        raise EngineError(f"{command}: expected box primitive, got \\{self._expander._diagnostic_cs_name(tok)}")

    def _exec_box_cmd(self) -> None:
        """\\box — use and clear a box register."""
        from aspose_tex._engine.dimparser import parse_integer
        idx = parse_integer(self._expander)
        box = self._box_regs.getbox(idx)  # getbox already voids the register
        if box is not None:
            self._add_box_to_current_list(box)

    def _exec_copy_cmd(self) -> None:
        """\\copy — use a box register without clearing it."""
        from aspose_tex._engine.dimparser import parse_integer
        idx = parse_integer(self._expander)
        box = self._box_regs.copybox(idx)
        if box is not None:
            self._add_box_to_current_list(box)

    def _exec_shipout_cmd(self) -> None:
        """\\shipout<box> — ship a box through the active backend."""
        box = self._scan_box_value("\\shipout")
        if box is None:
            return
        if isinstance(box, HlistNode):
            box = VlistNode(
                list=[box],
                width=box.width,
                height=box.height,
                depth=box.depth,
                shift_amount=0,
                glue_sign=GlueSign.NORMAL,
                glue_order=GlueOrder.NORMAL,
                glue_set=0.0,
            )
        exec_shipout(
            box,
            page_number=self._page_builder.page_number,
            backend=self._page_builder._backend,
            page_builder=self._page_builder,
        )

    def _exec_hskip_cmd(self) -> None:
        """\\hskip<glue> — append horizontal glue (vertical mode: see §1090 dispatch)."""
        from aspose_tex._engine.dimparser import parse_glue
        self._append_horizontal_glue(GlueNode(parse_glue(self._expander)))

    def _exec_hglue_cmd(self) -> None:
        """\\hglue<glue> — top-level horizontal glue approximation."""
        self._exec_hskip_cmd()

    def _exec_vglue_cmd(self) -> None:
        """\\vglue<glue> — append vertical glue."""
        self._exec_vskip()

    def _exec_unhbox_cmd(self, *, copy: bool) -> None:
        """\\unhbox / \\unhcopy — splice an hbox register into the current hlist.

        In vertical mode :meth:`_dispatch_cs` first starts an indented
        paragraph (§1090), which is what plain's ``\\leavevmode`` relies on.
        """
        from aspose_tex._engine.box_primitives import exec_unbox
        for node in exec_unbox(self._expander, self._box_regs, copy=copy, vertical=False):
            self._append_to_hlist(node)

    def _exec_unvbox_cmd(self, *, copy: bool) -> None:
        """\\unvbox / \\unvcopy — splice a vbox register into the current vlist."""
        from aspose_tex._engine.box_primitives import exec_unbox
        if self._mode_stack.current in (
            ModeKind.RESTRICTED_HORIZONTAL, ModeKind.MATH, ModeKind.MATH_DISPLAY,
        ):
            raise EngineError("\\unvbox outside vertical mode")
        self._head_for_vmode()
        self._splice_vertical_nodes(
            exec_unbox(self._expander, self._box_regs, copy=copy, vertical=True),
        )

    def _splice_vertical_nodes(self, nodes: list) -> None:
        """Splice into the receiving vertical owner without logical depth writes."""
        frame = self._current_box_frame()
        if frame is not None and frame.vertical:
            frame.builder._nodes.extend(nodes)
            return
        self._page_builder.contribute_spliced(nodes)
        tail = self._page_builder.last_contributed_node
        if isinstance(tail, (GlueNode, LeadersNode)):
            self._record_last_skip(tail.glue)
        elif isinstance(tail, KernNode):
            self._record_last_kern(tail.width)
        elif isinstance(tail, PenaltyNode):
            self._record_last_penalty(tail.penalty)
        else:
            self._record_non_discardable()

    def _exec_unskip_cmd(self) -> None:
        """\\unskip — remove trailing glue from the current list if present."""
        from aspose_tex._engine.box_primitives import exec_unskip
        from aspose_tex._engine.nodes import GlueNode
        if self._math_owns_tail():
            from aspose_tex._engine.math_list import NoadKind
            self._math_builder.remove_tail(NoadKind.GLUE)
            return
        target = self._current_node_target()
        if hasattr(target, "remove_last_node"):  # PageBuilder (V-mode);
            target.remove_last_node(GlueNode, LeadersNode)
        else:  # ParagraphList (H-mode) — unchanged
            exec_unskip(target)

    def _exec_unkern_cmd(self) -> None:
        """\\unkern — remove trailing kern from the current list if present."""
        from aspose_tex._engine.box_primitives import exec_unkern
        from aspose_tex._engine.nodes import KernNode
        if self._math_owns_tail():
            from aspose_tex._engine.math_list import NoadKind
            self._math_builder.remove_tail(NoadKind.KERN)
            return
        target = self._current_node_target()
        if hasattr(target, "remove_last_node"):  # PageBuilder (V-mode);
            target.remove_last_node(KernNode)
        else:  # ParagraphList (H-mode) — unchanged
            exec_unkern(target)

    def _exec_unpenalty_cmd(self) -> None:
        """\\unpenalty — remove trailing penalty from the current list if present."""
        from aspose_tex._engine.box_primitives import exec_unpenalty
        from aspose_tex._engine.nodes import PenaltyNode
        if self._math_owns_tail():
            from aspose_tex._engine.math_list import NoadKind
            self._math_builder.remove_tail(NoadKind.PENALTY)
            return
        target = self._current_node_target()
        if hasattr(target, "remove_last_node"):  # PageBuilder (V-mode);
            target.remove_last_node(PenaltyNode)
        else:  # ParagraphList (H-mode) — unchanged
            exec_unpenalty(target)

    def _exec_lastbox_cmd(self) -> None:
        """\\lastbox — remove the trailing box and append it when used directly."""
        box = self._remove_last_box()
        if box is not None:
            self._add_box_to_current_list(box)

    def _exec_vsplit_cmd(self) -> None:
        """\\vsplit outside \\setbox — parse and discard the returned box."""
        from aspose_tex._engine.box_primitives import exec_vsplit
        entry = self._named_params.lookup("splittopskip")
        splittopskip = (
            self._register_set.get_skip(entry.slot, _internal=True)
            if entry is not None else Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
        )
        exec_vsplit(
            self._expander,
            self._box_regs,
            splittopskip=splittopskip,
            split_capture_callback=self._split_capture_callback,
        )

    def _exec_insert_cmd(self) -> None:
        r"""``\insert<n>{<vlist>}`` — contribute an insert node."""
        from aspose_tex._engine.box_primitives import exec_vbox
        from aspose_tex._engine.dimparser import parse_integer
        from aspose_tex._engine.nodes import InsertNode

        class_ = parse_integer(self._expander)
        self._box_regs._validate(class_)  # Reuse the box-class range contract.
        box = exec_vbox(
            self._expander,
            self._font_manager,
            self._group_stack,
            self._box_regs,
        )
        node = InsertNode(
            class_=class_,
            vlist=tuple(box.list),
            height=box.height,
            depth=box.depth,
            floating_penalty=self._get_named_int("floatingpenalty"),
            split_top_skip=self._get_named_skip("splittopskip"),
            split_max_depth=self._get_named_dimen("splitmaxdepth"),
        )
        if self._mode_stack.current in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
            # §655: direct carriers migrate when packing a line/adjusted hbox;
            # ordinary stored or nested hboxes keep them.
            self._append_to_hlist(node)
            return
        self._contribute(node)
        self._build_page_if_outer()  # §1100

    def _get_named_int(self, name: str) -> int:
        entry = self._named_params.lookup(name)
        if entry is None:
            return 0
        return self._register_set.get_count(entry.slot, _internal=True)

    def _get_named_dimen(self, name: str) -> int:
        entry = self._named_params.lookup(name)
        if entry is None:
            return 0
        return self._register_set.get_dimen(entry.slot, _internal=True)

    def _set_named_skip(self, name: str, value: Glue) -> None:
        """Write a named SKIP parameter slot (symmetric to ``_get_named_skip``).

        A no-op when the name is unregistered.

        Args:
            name:  Named-parameter identifier (e.g. ``"baselineskip"``).
            value: The glue to store.
        """
        entry = self._named_params.lookup(name)
        if entry is not None:
            self._register_set.set_skip(entry.slot, value, _internal=True)

    def _set_named_dimen(self, name: str, value: int, *, unbounded: bool = False) -> None:
        """Write a named DIMEN parameter slot (symmetric to the getter).

        Used by the engine to set quantities TeX computes internally (e.g.
        ``\\predisplaysize`` at display time, §1146).  A no-op when the name is
        unregistered.

        Args:
            name: Named-parameter identifier (e.g. ``"predisplaysize"``).
            value: The value in scaled points.
            unbounded: Store a value beyond ``\\maxdimen`` as TeX's
                ``eq_word_define`` does, instead of raising.
        """
        entry = self._named_params.lookup(name)
        if entry is not None:
            self._register_set.set_dimen(entry.slot, value, _internal=True, _unbounded=unbounded)

    def _init_display_params(self, shape: LinebreakParams) -> None:
        r"""Set live display geometry and pre-display ink extent at entry (§1145)."""
        indent, width = _line_geometry(shape, self._prev_graf + 2)
        self._set_named_dimen("displaywidth", width)
        self._set_named_dimen("displayindent", indent)
        last = self._last_paragraph_line
        if last is None:
            pre = -MAX_DIMEN
        else:
            ink = self._measure_predisplaysize(last)
            pre = MAX_DIMEN if ink is None else ink
        self._set_named_dimen("predisplaysize", pre, unbounded=True)

    def _init_display_prev_depth(self) -> None:
        r"""Give alignment collection the already-contributed pre-display depth."""
        last = self._last_paragraph_line
        self._pending_display_prev_depth = last.depth if last is not None else None
        self._last_paragraph_line = None

    def _linebreak_params(self) -> LinebreakParams:
        r"""Snapshot live paragraph parameters at its actual ending boundary."""
        return LinebreakParams(
            hsize=self._current_hsize(),
            tolerance=self._get_named_int("tolerance"),
            pretolerance=self._get_named_int("pretolerance"),
            linepenalty=_LINEPENALTY,
            adjdemerits=_ADJDEMERITS,
            leftskip=self._get_named_skip("leftskip"),
            rightskip=self._get_named_skip("rightskip"),
            parfillskip=self._get_named_skip("parfillskip"),
            hbadness=self._get_named_int("hbadness"),
            hfuzz=self._get_named_dimen("hfuzz"),
            overfull_rule=self._get_named_dimen("overfullrule"),
            hyphenpenalty=self._get_named_int("hyphenpenalty"),
            exhyphenpenalty=self._get_named_int("exhyphenpenalty"),
            doublehyphendemerits=self._get_named_int("doublehyphendemerits"),
            finalhyphendemerits=self._get_named_int("finalhyphendemerits"),
            hangindent=self._get_named_dimen("hangindent"),
            hangafter=self._get_named_int("hangafter"),
            parshape=tuple(self._parshape or ()),
            prevgraf=self._prev_graf,
        )

    def _measure_predisplaysize(self, line: HlistNode) -> int | None:
        r"""Pre-display extent of a finished line box (TeX §1146).

        Returns the natural extent to the last visible item, including the
        line shift and two entry text-font quads. Nonvisible trailing material
        does not update that extent. Complete the correction here so a valid
        visible width cannot be confused with the no-visible-node sentinel.

        Args:
            line: The pre-display paragraph's last line (an ``HlistNode``).

        Returns:
            The natural content width in sp, or ``None`` when *line* is not a
            measurable horizontal line.  A line without visible nodes returns
            ``-MAX_DIMEN``; once the running extent reaches ``MAX_DIMEN`` (or
            active glue makes it indeterminate) a later visible node gives
            ``MAX_DIMEN``.  The last visible node may carry the extent past
            ``MAX_DIMEN``, which TeX keeps (§1146).
        """
        from aspose_tex._engine.box_builder import _measure_hlist

        if not isinstance(line, HlistNode):
            return None
        # §1146-§1148: v runs from the shift plus two quads and stops
        # growing at max_dimen; only visible nodes update w.  Active glue
        # (§1148) sets v to max_dimen, so later ink saturates w; trailing
        # glue/kerns/penalties cannot turn a void line into ink.
        v = line.shift_amount + 2 * (self._display_entry_quad or 0)
        w = -MAX_DIMEN
        for node in line.list:
            if isinstance(node, (GlueNode, LeadersNode)):
                glue = node.glue
                if ((line.glue_sign == GlueSign.STRETCHING
                     and line.glue_order == glue.stretch_order and glue.stretch != 0)
                    or (line.glue_sign == GlueSign.SHRINKING
                        and line.glue_order == glue.shrink_order and glue.shrink != 0)):
                    v = MAX_DIMEN
            d = _measure_hlist([node], self._font_manager)[0]
            if isinstance(node, (CharNode, HlistNode, VlistNode, RuleNode, LeadersNode)):
                if v >= MAX_DIMEN:
                    return MAX_DIMEN
                v += d
                w = v
            elif v < MAX_DIMEN:
                v += d
        return w

    def _current_hsize(self) -> int:
        r"""Return the live ``\hsize`` in sp (named-param DIMEN slot 258).

        Reads the register directly (via :meth:`_get_named_dimen`) so group
        save/restore is honoured — ``{\hsize=3in <par>}`` breaks at 3in while
        the paragraph after the group breaks at the restored width.  Falls back
        to the ``_HSIZE`` plain-TeX default if ``\hsize`` is somehow
        unregistered (defensive; unreachable under normal construction).

        See.

        Returns:
            The current ``\hsize`` value in scaled points.
        """
        if self._named_params.lookup("hsize") is None:
            return _HSIZE
        return self._get_named_dimen("hsize")

    def _get_named_skip(self, name: str) -> Glue:
        entry = self._named_params.lookup(name)
        if entry is None:
            return Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
        return self._register_set.get_skip(entry.slot, _internal=True)

    def _exec_moveleft_cmd(self) -> None:
        """\\moveleft<dimen><box> — append a left-shifted box in vertical mode."""
        self._exec_move_cmd(left=True)

    def _exec_moveright_cmd(self) -> None:
        """\\moveright<dimen><box> — append a right-shifted box in vertical mode."""
        self._exec_move_cmd(left=False)

    def _exec_move_cmd(self, *, left: bool) -> None:
        """Shared implementation for vertical-mode box movement."""
        from aspose_tex._engine.box_primitives import apply_shift
        from aspose_tex._engine.dimparser import parse_dimen
        if self._mode_stack.current in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
            name = "\\moveleft" if left else "\\moveright"
            raise EngineError(f"{name} in horizontal mode")
        amount = parse_dimen(self._expander)
        adjustments = []
        box = self._scan_box_value("\\moveleft" if left else "\\moveright", adjustments=adjustments)
        if box is None:
            return
        self._contribute(apply_shift(box, -amount if left else amount, vertical=False))
        self._splice_vertical_nodes(adjustments)
        self._build_page_if_outer()  # §1076 box_end

    def _exec_leavevmode_cmd(self) -> None:
        """\\leavevmode — start an indented paragraph in vertical mode.

        The format-less stand-in for plain's ``\\unhbox\\voidb@x``, so it
        indents like plain's (§1090 ``new_graf(true)``).
        """
        if self._mode_stack.current in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
            self._begin_paragraph()

    def _exec_parshape_cmd(self) -> None:
        """\\parshape<n><indent><length>... — parse and store the shape."""
        from aspose_tex._engine.dimparser import parse_dimen, parse_integer
        self._eat_optional_equals()
        count = parse_integer(self._expander)
        if count < 0:
            raise EngineError("\\parshape count < 0")
        old = self._parshape
        if self._group_stack.is_global_pending:
            self._group_stack.retain_global(("parshape", None))
        else:
            self._group_stack.save(("parshape", None), lambda: setattr(self, "_parshape", old))
        if count == 0:
            self._parshape = None
        else:
            self._parshape = [
                (parse_dimen(self._expander), parse_dimen(self._expander))
                for _ in range(count)
            ]
        self._group_stack.consume_global()
        self._expander.fire_after_assignment()

    def _normal_paragraph(self) -> None:
        r"""Reset the paragraph shape locally, as TeX's ``normal_paragraph`` (§1070).

        ``\looseness``, ``\hangindent``, ``\hangafter`` and ``\parshape``
        return to 0, 0, 1 and empty, each only when it differs and always as a
        local assignment through its owner's save path.  A
        pending ``\global`` prefix belongs to the next assignment and is kept.
        """
        gs = self._group_stack
        with gs.local_assignment():
            for name, kind, reset in (
                ("looseness", "int", 0), ("hangindent", "dimen", 0), ("hangafter", "int", 1),
            ):
                entry = self._named_params.lookup(name)
                if kind == "int":
                    if self._register_set.get_count(entry.slot, _internal=True) != reset:
                        self._register_set.set_count(entry.slot, reset, _internal=True)
                elif self._register_set.get_dimen(entry.slot, _internal=True) != reset:
                    self._register_set.set_dimen(entry.slot, reset, _internal=True)
            if self._parshape is not None:
                old = self._parshape
                gs.save(("parshape", None), lambda: setattr(self, "_parshape", old))
                self._parshape = None

    def _current_node_target(self):
        """Return the mutable node container for the current TeX mode."""
        if self._mode_stack.current in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
            return self._par_list
        frame = self._current_box_frame()
        if frame is not None and frame.vertical:
            return frame.builder
        return self._page_builder

    def _math_owns_tail(self) -> bool:
        return bool(self._math_builder is not None and self._math_tail_depths
                    and len(self._tail_providers) == self._math_tail_depths[-1] + 1)

    def _remove_last_box(self) -> HlistNode | VlistNode | None:
        """Remove the trailing box from the current list."""
        from aspose_tex._engine.box_primitives import exec_lastbox
        target = self._current_node_target()
        if target is self._page_builder:
            # §1080: only the contribution list's tail can be taken.
            box = target.remove_last_node(HlistNode, VlistNode)
            if box is None and self._mode_stack.current == ModeKind.OUTER_VERTICAL:
                raise EngineError("\\lastbox in outer vertical mode")
            if box is not None:
                box.shift_amount = 0  # §1081,
            return box
        return exec_lastbox(target, self._mode_stack.current)

    def _exec_wd_cmd(self) -> None:
        """``\\wd<reg>=<dimen>`` — set a box register's width (§F)."""
        self._exec_box_dimension("\\wd", self._box_regs.set_wd)

    def _exec_ht_cmd(self) -> None:
        """``\\ht<reg>=<dimen>`` — set a box register's height (§F)."""
        self._exec_box_dimension("\\ht", self._box_regs.set_ht)

    def _exec_dp_cmd(self) -> None:
        """``\\dp<reg>=<dimen>`` — set a box register's depth (§F)."""
        self._exec_box_dimension("\\dp", self._box_regs.set_dp)

    def _exec_box_dimension(self, command: str, setter) -> None:
        r"""Dispatch ``\ht`` / ``\wd`` / ``\dp`` in command position (§F,
        corrected).

        In command position these primitives are ALWAYS assignments
        ``\ht<reg><optional-=><dimen>`` (TeX:The Program §1244 ``set_box_dimen``):
        scan the register index, eat the OPTIONAL ``=``, then ALWAYS scan a
        ``<dimen>`` and apply *setter* (one of ``BoxRegisterSet.set_ht`` /
        ``set_wd`` / ``set_dp``).  There is no bare-read no-op in command
        position — the operand read (e.g. ``\dimen0=\ht0``) is a SEPARATE call
        site handled by the dimparser ``_lookup_box_dimension`` arm.  This lets
        the equals-less ``\finph@nt`` form ``\ht\tw@\ht\z@`` (copy ``\ht\z@``'s
        value onto box 2) work: after ``reg=2`` and no ``=``, ``parse_dimen``
        reads ``\ht\z@`` as an ``<internal dimen>`` operand.
        """
        from aspose_tex._engine.dimparser import parse_dimen, parse_integer

        reg = parse_integer(self._expander, allow_negative=False)
        global_ = self._group_stack.is_global_pending
        self._group_stack.consume_global()
        self._eat_optional_equals_bool()  # '=' is optional; a dimen always follows.
        setter(reg, parse_dimen(self._expander), global_=global_)
        self._expander.fire_after_assignment()

    def _exec_raise_cmd(self) -> None:
        r"""``\raise <dimen> <box>`` — raise a box by *dimen*.

        Accepts the full TeX ``<box>`` operand grammar — ``\hbox{…}`` /
        ``\vbox{…}`` / ``\vtop{…}`` / ``\box<n>`` / ``\copy<n>`` — via the
        shared :func:`box_primitives._scan_next_box`, mirroring the eager
        restricted-horizontal ``\raise`` arm.
        """
        from aspose_tex._engine.box_primitives import _scan_next_box, apply_shift
        from aspose_tex._engine.dimparser import parse_dimen
        amount = parse_dimen(self._expander)
        box = _scan_next_box(
            self._expander, self._font_manager, self._group_stack, self._box_regs,
        )
        self._add_box_to_current_list(apply_shift(box, amount, vertical=True))

    def _exec_lower_cmd(self) -> None:
        r"""``\lower <dimen> <box>`` — lower a box by *dimen*.

        Accepts the full ``<box>`` operand grammar via the shared
        :func:`box_primitives._scan_next_box`.
        """
        from aspose_tex._engine.box_primitives import _scan_next_box, apply_shift
        from aspose_tex._engine.dimparser import parse_dimen
        amount = parse_dimen(self._expander)
        box = _scan_next_box(
            self._expander, self._font_manager, self._group_stack, self._box_regs,
        )
        self._add_box_to_current_list(apply_shift(box, -amount, vertical=True))

    def _exec_char_cmd(self) -> None:
        """\\char<n> — append a character in the current font."""
        from aspose_tex._engine.box_primitives import _check_char_code
        from aspose_tex._engine.dimparser import parse_integer
        code = parse_integer(self._expander)
        _check_char_code(code, "\\char")
        self._handle_char(CharToken(chr(code), Catcode.OTHER))

    def _exec_accent_cmd(self) -> None:
        """\\accent<n><char> — append TeX's direct accent/base list."""
        from aspose_tex._engine.box_primitives import exec_accent
        exec_accent(self._expander, self._font_manager, self._par_list)

    def _exec_discretionary_cmd(self) -> None:
        """\\discretionary{pre}{post}{nobreak} — append a discretionary node."""
        from aspose_tex._engine.box_primitives import exec_discretionary
        exec_discretionary(
            self._expander,
            self._font_manager,
            self._group_stack,
            self._box_regs,
            self._par_list,
        )

    def _exec_ignorespaces(self) -> None:
        """Skip expanded space tokens, retaining the first non-space (§1045)."""
        tok = self._expander._next_unexpandable()
        while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
            tok = self._expander._next_unexpandable()
        if tok is not None:
            self._expander.push_tokens([tok])

    def _exec_discretionary_hyphen(self) -> None:
        """Append the current font's discretionary hyphen (§1117)."""
        from aspose_tex._engine.box_primitives import _append_discretionary_hyphen
        _append_discretionary_hyphen(self._font_manager, self._par_list)

    def _exec_mark_cmd(self) -> None:
        """\\mark{<tokens>} — append a page mark sentinel."""
        node = self._marks.execute_mark(tuple(self._read_balanced_tokens("\\mark")))
        if self._mode_stack.current in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
            self._append_to_hlist(node)
        else:
            self._contribute(node)

    def _exec_leaders_cmd(self, kind: LeadersKind) -> None:
        """\\leaders family — append a leader shell to its owning list."""
        from aspose_tex._engine.leaders import parse_leaders
        vertical = self._mode_stack.current in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL)
        node = parse_leaders(
            self._expander,
            self._font_manager,
            self._group_stack,
            self._box_regs,
            kind,
            vertical=vertical, interp=self,
        )
        if self._mode_stack.current in (ModeKind.MATH, ModeKind.MATH_DISPLAY):
            self._math_builder.add_leaders(node)
            return
        if vertical:
            self._contribute(node)
        else:
            self._append_to_hlist(node)

    def _read_balanced_tokens(self, command: str) -> list[Token]:
        """Read a balanced ``{...}`` token list for token-list primitives."""
        self._expander._scan_left_brace(command)
        depth = 0
        tokens: list[Token] = []
        while True:
            tok = self._next_token()
            if tok is None:
                raise EngineError(f"Unexpected end of input inside {command}")
            if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
                depth += 1
                tokens.append(tok)
                continue
            if isinstance(tok, CharToken) and tok.catcode == Catcode.END_GROUP:
                if depth == 0:
                    return tokens
                depth -= 1
                tokens.append(tok)
                continue
            tokens.append(tok)

    def _next_font_cs(self, command: str) -> str:
        """Consume and resolve a ``<font>`` operand (§E).

        Accepts ``\\font`` (current font), a ``\\font``-defined CS, or
        ``\\nullfont`` via the shared :func:`resolve_font_cs` resolver.
        """
        from aspose_tex._fonts.font_manager import scan_font_id
        try:
            return scan_font_id(self._expander)
        except EngineError as exc:
            raise EngineError(f"{command}: {exc}") from exc

    def _eat_optional_equals_bool(self) -> bool:
        """Consume optional assignment equals and report whether it was present."""
        tok = self._expander.peek()
        while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
            self._next_token()
            tok = self._expander.peek()
        if isinstance(tok, CharToken) and tok.char == "=" and tok.catcode == Catcode.OTHER:
            self._next_token()
            return True
        return False

    def _fontdimen_tokens(self, expander: Expander) -> list[Token]:
        """Return tokens for ``\\the\\fontdimen<n><font>`` (accepts ``\\font``)."""
        from aspose_tex._engine.dimparser import parse_integer
        from aspose_tex._engine.registers import _dimen_to_tokens
        from aspose_tex._fonts.font_manager import scan_font_id
        n = parse_integer(expander)
        font_cs = scan_font_id(expander)
        return _dimen_to_tokens(self._font_manager.fontdimen(font_cs, n))

    def _exec_fontdimen_cmd(self) -> None:
        """\\fontdimen<n><font-cs>=<dimen> — assign a fontdimen entry."""
        from aspose_tex._engine.dimparser import parse_dimen, parse_integer
        n = parse_integer(self._expander)
        cs_name = self._next_font_cs("\\fontdimen")
        if not self._eat_optional_equals_bool():
            return
        self._font_manager.set_fontdimen(cs_name, n, parse_dimen(self._expander))
        self._expander.fire_after_assignment()

    def _exec_skewchar_cmd(self) -> None:
        """\\skewchar<font-cs>=<int> — assign a font's skew character."""
        from aspose_tex._engine.dimparser import parse_integer
        cs_name = self._next_font_cs("\\skewchar")
        self._eat_optional_equals()
        self._font_manager.set_skewchar(cs_name, parse_integer(self._expander))
        self._expander.fire_after_assignment()

    def _exec_hyphenchar_cmd(self) -> None:
        """\\hyphenchar<font-cs>=<int> — assign a font's hyphen character."""
        from aspose_tex._engine.dimparser import parse_integer
        cs_name = self._next_font_cs("\\hyphenchar")
        self._eat_optional_equals()
        self._font_manager.set_hyphenchar(cs_name, parse_integer(self._expander))
        self._expander.fire_after_assignment()

    def _exec_textfont_cmd(self) -> None:
        """``\\textfont<family>=<font-cs>`` math-family assignment."""
        self._exec_math_family_font("\\textfont", self._math_family_registry.set_text)

    def _exec_scriptfont_cmd(self) -> None:
        """``\\scriptfont<family>=<font-cs>`` math-family assignment."""
        self._exec_math_family_font("\\scriptfont", self._math_family_registry.set_script)

    def _exec_scriptscriptfont_cmd(self) -> None:
        """``\\scriptscriptfont<family>=<font-cs>`` math-family assignment."""
        self._exec_math_family_font(
            "\\scriptscriptfont",
            self._math_family_registry.set_scriptscript,
        )

    def _exec_math_family_font(self, command: str, setter) -> None:
        """Assign one math-family role and fire afterassignment."""
        from aspose_tex._engine.dimparser import parse_integer

        family = parse_integer(self._expander, allow_negative=False)
        self._eat_optional_equals()
        font_cs = self._next_font_cs(command)
        global_ = self._group_stack.is_global_pending
        setter(family, font_cs, global_=global_)
        # NFR-1 (§B): drop the sigma/xi resolution cache on any family-2/3
        # reassignment so mlist_to_hlist re-resolves the math fonts.
        if family in (2, 3):
            self._math_params.invalidate()
        self._group_stack.consume_global()
        self._expander.fire_after_assignment()

    def _add_box_to_current_list(self, box: HlistNode | VlistNode) -> None:
        """Add a completed box to the appropriate list based on current mode."""
        # an open-group \vbox\bgroup receives contributed boxes
        # directly into its builder.  (An open-group \hbox\bgroup installs a
        # ParagraphList as _par_list, so its boxes route via _append_to_hlist.)
        frame = self._current_box_frame()
        if (frame is not None and frame.vertical
                and self._mode_stack.current == ModeKind.INTERNAL_VERTICAL):
            self._contribute(box)
            return
        mode = self._mode_stack.current
        if mode in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
            self._contribute(box)
            self._build_page_if_outer()  # §1076 box_end
        elif mode in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
            self._append_to_hlist(box)
            self._spacefactor = 1000  # §1076 box_end, also for a void-sized box.
        elif (
            mode in (ModeKind.MATH, ModeKind.MATH_DISPLAY)
            and self._math_builder is not None
        ):
            # §B: an \hbox/\vbox built while a math builder is open (the
            # plain.tex \big-family \mathopen{\hbox{$…$}}) lands as an Ord-atom
            # noad nucleus, not silently dropped.
            self._math_builder.add_box(box)

    def run_inline_math_in_box(self, open_tok: CharToken) -> list:
        r"""Run a nested ``$…$`` inside an eager ``\hbox`` body (§C).

        The plain.tex ``\big``-family body is ``\hbox{$\left(…\right.$}``.  The
        eager :func:`box_primitives.exec_hbox` scanner reads the inner ``$`` from
        its own loop while the interpreter is still in MATH mode (the outer
        formula).  Routing that ``$`` straight through :meth:`_handle_math_shift`
        would *close the outer formula* (MATH-mode ``$`` is a close).

        This helper makes the nesting well-formed exactly as TeX does — the
        ``\hbox`` is the mode barrier: it pushes RESTRICTED_HORIZONTAL so the
        opening ``$`` takes the RH→MATH *open* branch (a fresh inner builder),
        pumps tokens through the main dispatch until the matching ``$`` closes
        that inner builder, then restores mode / ``_par_list`` / ``_math_builder``
        so the **outer** builder is the same object before and after.  The inner
        formula's nodes (contributed to a scratch list at its ``$``-close) are
        returned for the caller to splice into the hbox builder.

        Args:
            open_tok: The opening ``$`` (MATH_SHIFT) token already read by the
                hbox scanner.

        Returns:
            The hlist nodes produced by the inner ``$…$`` formula.
        """
        # (\endv v-template injection, revises C1): inside an
        # alignment cell, a top-level (brace-depth 0) alignment &/\cr/\crcr/\span
        # is the TeX \endv boundary (§1131).  Two cases, decided by the active
        # column's v-template (stashed by alignment._scan_cell):
        #   * NON-EMPTY v-template (e.g. \eqalign's `$\displaystyle{##}$` whose
        #     V=`}$…` straddles the open `{`+`$`): inject [*v_tokens, terminator]
        #     so V's `}$` closes the cell's braces+`$` via the normal $-close,
        #     THEN the terminator is read by the cell scanner = \endv.  Keep
        #     pumping; do NOT close here.
        #   * EMPTY/None v-template (the simple `$#$` case handled, or a
        #     bare cell whose template carries no v-part): close the formula and
        #     hand the terminator back, exactly as did (byte-identical).
        # Gated on _alignment_cell_depth so the \big-family $-in-\hbox
        # path (depth 0) stays byte-identical.
        from aspose_tex._engine.alignment import _resolve_terminator_name
        from aspose_tex._engine.par_primitives import ParagraphList

        in_cell = self._alignment_cell_depth > 0
        # the brace depth at which a top-level &/\cr fires the \endv
        # injection.  0 for a non-straddling template (\matrix `\hfil$…$\hfil`);
        # >0 for a u-template that opens a brace closed only by V (\eqalign
        # `$\displaystyle{##}$`).  A deeper brace is a genuine `{a&b}` shield.
        term_brace = self._alignment_cell_ubrace[-1] if (
            in_cell and self._alignment_cell_ubrace) else 0

        saved_par_list = self._par_list
        saved_group_depth = self._group_stack.depth
        saved_mode_depth = self._mode_stack.depth
        saved_math_group_base = self._math_group_base
        saved_math_parent_mode_depth = self._math_parent_mode_depth
        saved_display_group_open = self._display_group_open
        saved_display_resume = self._display_resume_paragraph
        saved_display_quad = self._display_entry_quad
        saved_display_depth = self._pending_display_prev_depth
        saved_display_alignment = self._pending_display_alignment
        saved_last_line = self._last_paragraph_line
        saved_eqno = (self._math_eqno_kind, self._math_eqno_equation)
        saved_math_builder = self._math_builder
        saved_tail_depth = len(self._tail_providers)
        saved_math_tail_depth = len(self._math_tail_depths)
        # a cell `$…$` is its own \left/\right scope.  \pmatrix is
        # `\left(\matrix{…}\right)`; the outer \left has already bumped the
        # shared math-shell _left_right_depth, so without isolating it each cell
        # would see depth>0 and raise "missing \right".  Save/restore around the
        # cell pump (only in an alignment cell, so the \big-family path at depth
        # 0 stays byte-identical).
        saved_lr_depth = self._math_shell._left_right_depth
        self._math_shell._left_right_depth = 0
        cell = ParagraphList()
        self._par_list = cell
        self._math_builder = None
        self._mode_stack.push(ModeKind.RESTRICTED_HORIZONTAL)
        brace_depth = 0
        try:
            # RH-mode $ → open a fresh inner math builder (not a close).
            self._handle_math_shift(open_tok)
            # Pump until the matching $ runs _close_math_builder (builder → None).
            for token in self._token_iter:
                if in_cell and brace_depth == term_brace:
                    is_term = (
                        (isinstance(token, CharToken)
                         and token.catcode == Catcode.ALIGNMENT)
                        or (isinstance(token, ControlSequenceToken)
                            and _resolve_terminator_name(token.name, self) is not None)
                    )
                    if is_term and self._inject_cell_vtemplate(token):
                        # v-template injected ahead of the terminator (Gap B):
                        # keep pumping — V's `}$` closes the math via $-close.
                        continue
                    if is_term:
                        # No v-template to inject (empty/None or already done):
                        # mirror the MATH-mode $-close (_handle_math_shift) — pop
                        # the MATH push, check \left/\right balance, translate +
                        # append the formula, hand the terminator back to the cell
                        # scanner (simple path; TeX \endv §1131).
                        self._math_shell.check_left_right_balanced()
                        self._close_math_builder()
                        self._expander.push_tokens([token])
                        break
                if isinstance(token, CharToken):
                    if token.catcode == Catcode.BEGIN_GROUP:
                        brace_depth += 1
                    elif token.catcode == Catcode.END_GROUP and brace_depth > 0:
                        brace_depth -= 1
                self._dispatch(token)
                if self._math_builder is None:
                    break
            else:
                raise EngineError("missing $ inserted in \\hbox math")
        finally:
            while self._group_stack.depth > saved_group_depth:
                self._group_stack.close_group()  # abort: discard deferred tokens
            while self._mode_stack.depth > saved_mode_depth:
                self._mode_stack.pop()
            self._par_list = saved_par_list
            self._math_builder = saved_math_builder
            self._math_group_base = saved_math_group_base
            self._math_parent_mode_depth = saved_math_parent_mode_depth
            self._display_group_open = saved_display_group_open
            self._display_resume_paragraph = saved_display_resume
            self._display_entry_quad = saved_display_quad
            self._pending_display_prev_depth = saved_display_depth
            self._pending_display_alignment = saved_display_alignment
            self._last_paragraph_line = saved_last_line
            self._math_eqno_kind, self._math_eqno_equation = saved_eqno
            del self._tail_providers[saved_tail_depth:]
            del self._math_tail_depths[saved_math_tail_depth:]
            self._math_shell._left_right_depth = saved_lr_depth
        return cell._nodes

    def _inject_cell_vtemplate(self, terminator) -> bool:
        r"""Inject the active cell's v-template ahead of *terminator*.

        At the TeX ``\endv`` boundary (a top-level ``&``/``\cr`` inside a math
        ``\halign`` cell), the column's v-template (``}$…`` for ``\eqalign``,
        ``$\hfil`` for ``\matrix``) must run *before* the terminator so its
        trailing ``$`` closes the cell's open math+braces.  This pushes
        ``[*v_tokens, terminator]`` (v-part first, terminator last) so the
        normal ``$``-close fires, then the terminator reaches the cell scanner.

        Consumed once per cell (``_alignment_cell_pushed_v``) so a cell with
        several ``$…$`` runs does not re-inject.

        Returns:
            ``True`` if a non-empty v-template was injected (caller keeps
            pumping); ``False`` if there is nothing to inject (caller falls back
            to the close-at-terminator path).
        """
        if not self._alignment_cell_vtemplate or self._alignment_cell_pushed_v[-1]:
            return False
        v_tokens = self._alignment_cell_vtemplate[-1]
        if not v_tokens:
            return False
        assembled = self._alignment_cell_assembled_close[-1]
        if assembled is not None:
            boundary, owner_depth = assembled
            if self._group_stack.depth != owner_depth:
                return False  # A brace in the body still shields this token.
            stack = self._expander._stack
            index = next((i for i, token in enumerate(stack) if token is boundary), None)
            if index is None:
                return False  # The original V has already run.
            queued_v = stack[index + 1:index + 1 + len(v_tokens)]
            if len(queued_v) != len(v_tokens) or any(
                queued is not original
                for queued, original in zip(queued_v, reversed(v_tokens), strict=True)
            ):
                return False  # A macro argument already consumed this V.
            # Relocate only the queued V, retaining the raw remainder for the
            # next cell/row. U has already executed, so its definitions govern
            # the macro that produced this terminator.
            del stack[index + 1:index + 1 + len(v_tokens)]
        self._alignment_cell_pushed_v[-1] = True
        self._expander.push_tokens([*v_tokens, terminator])
        return True

    # ------------------------------------------------------------------
    # Open-group box construction
    # ------------------------------------------------------------------

    def _current_box_frame(self) -> _BoxBuildFrame | None:
        """Return the innermost open-group box-build frame, or None."""
        return self._box_construction_stack[-1] if self._box_construction_stack else None

    def _current_box_builder(self):
        """Return the innermost open-group box builder, or None."""
        frame = self._current_box_frame()
        return frame.builder if frame is not None else None

    def _add_box_to_box_frame(
        self, frame: _BoxBuildFrame, box: HlistNode | VlistNode,
    ) -> None:
        """Contribute *box* into a vertical open-group frame's builder."""
        builder = frame.builder
        if isinstance(box, HlistNode):
            builder.add_hbox(box)
        else:
            builder.add_vbox(box)

    def _peek_box_begin_group(self) -> bool:
        """Return whether the box keyword is followed by a ``\\bgroup`` alias.

        the open-group (deferred-close) path triggers ONLY for a
        ``\\bgroup``-style begin-group — a control sequence whose meaning is a
        begin-group char (``\\let\\bgroup={``).  A literal ``{`` keeps the eager
        ``exec_hbox`` / ``exec_vbox`` scanner (byte-identical, Q4), so
        ``\\hbox{…}`` everywhere is unchanged.
        """
        # Skip the same blank/relax meanings as scan_left_brace, but retain
        # the first other token's identity for the destination choice.
        while True:
            tok = self._expander.get_x_token()
            meaning = self._expander._let_meaning(tok) if tok is not None else None
            if isinstance(meaning, PrimitiveMeaning) and meaning.name == "relax":
                continue
            if isinstance(meaning, CharToken) and meaning.catcode == Catcode.SPACE:
                continue
            if tok is not None:
                self._expander.push_tokens([tok])
            break
        if not isinstance(tok, ControlSequenceToken):
            return False
        meaning = self._expander.macros.get(tok.name)
        return (
            isinstance(meaning, CharToken)
            and meaning.catcode == Catcode.BEGIN_GROUP
        )

    def _open_group_box(
        self,
        *,
        vertical: bool,
        vtop: bool,
        target: int | None,
        spread: int | None,
        destination,
    ) -> None:
        """Open a deferred-close box.

        Consumes the begin-group already confirmed by :meth:`_peek_box_begin_group`,
        opens a paired ``BRACE`` save-frame, installs the builder, and returns to
        the main loop.  Subsequent contributions flow into the builder until the
        matching end-group fires :meth:`_close_group_box`.
        """
        from aspose_tex._engine.box_builder import HBoxBuilder, VBoxBuilder
        from aspose_tex._engine.box_primitives import _badness_sink

        # Capture the restore target BEFORE pushing this frame's mode so that
        # _close_group_box returns the mode stack to exactly where it was, even
        # if the frame opened on top of a delegated-cell RH push (alignment).
        restore_mode_depth = self._mode_stack.depth

        # Consume the begin-group token (a literal `{` or the `\bgroup` alias's
        # `{`).  _next_token resolves the alias; the char is discarded.
        self._next_token()
        self._group_stack.open_group(GroupKind.BRACE)

        if vertical:
            self._normal_paragraph()  # §1083, local to the box group
            builder = VBoxBuilder(self._font_manager, badness_sink=_badness_sink(self._expander))
        else:
            builder = HBoxBuilder(self._font_manager, badness_sink=_badness_sink(self._expander))

        frame = _BoxBuildFrame(
            builder=builder,
            vertical=vertical,
            group_depth=self._group_stack.depth,
            destination=destination,
            target=target,
            spread=spread,
            vtop=vtop,
            saved_par_list=self._par_list,
            restore_mode_depth=restore_mode_depth,
            restore_tail_depth=len(self._tail_providers),
            saved_prev_depth=self._prev_depth,
            saved_spacefactor=self._spacefactor,
            saved_prev_graf=self._prev_graf,
            saved_last_line=self._last_paragraph_line,
        )
        self._box_construction_stack.append(frame)

        if vertical:
            frame.saved_math_state = self._isolate_vertical_math()
            self._mode_stack.push(ModeKind.INTERNAL_VERTICAL)
            self._prev_depth = _PREVDEPTH_SENTINEL
            self._prev_graf = 0
            self._par_list = None
        else:
            # Horizontal open-group box: install a fresh ParagraphList so loose
            # chars / glue / boxes route into this cell via _append_to_hlist.
            self._mode_stack.push(ModeKind.RESTRICTED_HORIZONTAL)
            self._par_list = ParagraphList()
            self._spacefactor = 1000
        if vertical:
            self._tail_providers.append(lambda: self._deferred_vertical_tail(builder))
        else:
            paragraph = self._par_list
            self._tail_providers.append(lambda: paragraph.last_node)
            self._push_toks_if_any(260)  # §1083: \everyhbox in the new box group

    def _close_group_box(self, *, max_depth: int | None) -> None:
        """Finalise the innermost open-group box and deliver it."""
        from aspose_tex._engine.box_builder import append_overfull_rule
        from aspose_tex._engine.box_primitives import _warn_badness

        frame = self._box_construction_stack.pop()

        if frame.vertical:
            box = frame.builder.build(
                target_height=frame.target, spread=frame.spread,
                max_depth=max_depth,
            )
            if frame.vtop:
                box = self._apply_vtop(box)
        else:
            # Splice the ParagraphList nodes accumulated in horizontal mode into
            # the frame builder, then build.
            for node in self._par_list._nodes:
                if isinstance(node, (HlistNode, VlistNode)):
                    frame.builder.add_box(node)
                else:
                    frame.builder._nodes.append(node)
            box = frame.builder.build(target_width=frame.target, spread=frame.spread)
            _warn_badness(box, frame.builder.last_badness,
                          expander=self._expander, font_manager=self._font_manager)
            append_overfull_rule(
                box, frame.builder.last_badness, self._font_manager,
                hfuzz=self._get_named_dimen("hfuzz"),
                overfull_rule=self._get_named_dimen("overfullrule"),
            )

        # Restore the mode stack + paragraph list to the pre-open state.
        while self._mode_stack.depth > frame.restore_mode_depth:
            self._mode_stack.pop()
        self._par_list = frame.saved_par_list
        self._prev_depth = frame.saved_prev_depth
        self._spacefactor = frame.saved_spacefactor
        self._prev_graf = frame.saved_prev_graf
        self._last_paragraph_line = frame.saved_last_line
        if frame.saved_math_state is not None:
            self._restore_vertical_math(frame.saved_math_state)
        del self._tail_providers[frame.restore_tail_depth:]

        frame.destination(box)

    def _isolate_vertical_math(self):
        """Save the surrounding formula while a new vertical nest executes."""
        names = (
            "_math_builder", "_math_group_base", "_math_parent_mode_depth",
            "_display_group_open", "_math_eqno_kind", "_math_eqno_equation",
            "_pending_display_alignment", "_pending_display_prev_depth",
            "_display_entry_quad", "_display_resume_paragraph",
        )
        state = {name: getattr(self, name) for name in names}
        state["left_right_depth"] = self._math_shell._left_right_depth
        state["math_tail_depth"] = len(self._math_tail_depths)
        for name in names:
            setattr(self, name, False if name in ("_display_group_open", "_display_resume_paragraph") else None)
        self._math_shell._left_right_depth = 0
        return state

    def _restore_vertical_math(self, state) -> None:
        """Restore exactly the formula ownership captured at nest entry."""
        for name, value in state.items():
            if name.startswith("_"):
                setattr(self, name, value)
        self._math_shell._left_right_depth = state["left_right_depth"]
        del self._math_tail_depths[state["math_tail_depth"]:]

    @contextmanager
    def _internal_vertical_scope(self, builder):
        """Execute a synchronous internal list with isolated nest ownership."""
        frame = _BoxBuildFrame(
            builder=builder, vertical=True, group_depth=-1, destination=None,
            target=None, spread=None, vtop=False, saved_par_list=self._par_list,
            restore_mode_depth=self._mode_stack.depth,
            restore_tail_depth=len(self._tail_providers),
            saved_prev_depth=self._prev_depth, saved_spacefactor=self._spacefactor,
            saved_prev_graf=self._prev_graf, saved_last_line=self._last_paragraph_line,
            saved_math_state=self._isolate_vertical_math(),
        )
        box_depth = len(self._box_construction_stack)
        group_depth = self._group_stack.depth
        self._box_construction_stack.append(frame)
        self._mode_stack.push(ModeKind.INTERNAL_VERTICAL)
        self._par_list = None
        self._prev_depth = _PREVDEPTH_SENTINEL
        self._prev_graf = 0
        self._tail_providers.append(lambda: self._deferred_vertical_tail(builder))
        try:
            yield
        finally:
            while self._group_stack.depth > group_depth:
                self._group_stack.close_group()  # abort: discard aftergroup
            del self._box_construction_stack[box_depth:]
            while self._mode_stack.depth > frame.restore_mode_depth:
                self._mode_stack.pop()
            self._par_list = frame.saved_par_list
            self._prev_depth = frame.saved_prev_depth
            self._spacefactor = frame.saved_spacefactor
            self._prev_graf = frame.saved_prev_graf
            self._last_paragraph_line = frame.saved_last_line
            del self._tail_providers[frame.restore_tail_depth:]
            self._restore_vertical_math(frame.saved_math_state)

    def _execute_vbox(self, target_height=None, spread=None):
        """Build a brace-owned vbox through normal interpreter dispatch."""
        from aspose_tex._engine.box_builder import VBoxBuilder
        from aspose_tex._engine.box_primitives import _badness_sink, _warn_badness

        builder = VBoxBuilder(self._font_manager, badness_sink=_badness_sink(self._expander))
        with self._internal_vertical_scope(builder):
            self._expander._scan_left_brace("\\vbox")
            self._group_stack.open_group(GroupKind.BRACE)
            self._normal_paragraph()  # §1083 / §1099 / §1167, local to the box group
            owner_depth = self._group_stack.depth
            for token in self._token_iter:
                if (isinstance(token, CharToken) and token.catcode == Catcode.END_GROUP
                        and self._group_stack.depth == owner_depth):
                    if self._math_builder is not None:
                        raise EngineError("} cannot close the active math group")
                    if self._mode_stack.current == ModeKind.HORIZONTAL:
                        self._end_paragraph()
                    # §1086: \boxmaxdepth is read before the group closes.
                    box = builder.build(
                        target_height=target_height, spread=spread,
                        max_depth=self._get_named_dimen("boxmaxdepth"),
                    )
                    tokens, _kind = self._group_stack.close_group()
                    self._expander.push_tokens(tokens)
                    _warn_badness(box, builder.last_badness, "vbox",
                                  expander=self._expander, font_manager=self._font_manager)
                    return box
                self._dispatch(token)
            raise EngineError("Unexpected end of input inside \\vbox")

    def build_math_vcenter_box(self) -> HlistNode | VlistNode:
        r"""Build a math ``\vcenter`` field as an executed box.

        ``\vcenter`` takes a ``<box>``; plain.tex uses the implicit-vbox form
        ``\vcenter{…}`` (`\matrix`/`\eqalign`/`\cases`).  Building the field
        through the real box scanners — rather than as a math sub-formula
        — makes the inner ``\ialign``→``\halign`` execute as
        ``exec_halign``, so the alignment grid is actually built.  The finished
        box becomes the VCENTER atom's nucleus (``mlist_to_hlist`` axis-centres
        it).

        Three accepted field forms (peek after ``\vcenter``):
          * ``{…}``        → implicit ``\vbox`` (``exec_vbox`` reads the ``{``).
          * ``\vbox{…}``   → explicit vbox.
          * ``\hbox{…}``   → explicit hbox.

        Returns:
            The finished ``VlistNode`` / ``HlistNode``.

        Raises:
            EngineError: if ``\vcenter`` is not followed by a box or ``{``.
        """
        from aspose_tex._engine.box_primitives import (
            _scan_box_keyword,
            exec_hbox,
            exec_vbox,
        )

        # mark that the \halign built inside this \vcenter body is a
        # math alignment (\m@th/\ialign context), so its cells scan in MATH mode
        # (alignment._scan_cell routes through `scan_math_cell`).  Balanced in the
        # finally so an exception cannot strand the flag.
        self._alignment_math_context += 1
        try:
            while True:
                tok = self._expander.get_x_token()
                meaning = self._expander._let_meaning(tok) if tok is not None else None
                if isinstance(meaning, PrimitiveMeaning) and meaning.name == "relax":
                    continue
                if isinstance(meaning, CharToken) and meaning.catcode == Catcode.SPACE:
                    continue
                break
            if isinstance(meaning, PrimitiveMeaning) and meaning.name in ("vbox", "hbox"):
                tw, sp = _scan_box_keyword(self._expander)
                if meaning.name == "vbox":
                    return exec_vbox(
                        self._expander, self._font_manager, self._group_stack,
                        self._box_regs, target_height=tw, spread=sp,
                    )
                return exec_hbox(
                    self._expander, self._font_manager, self._group_stack,
                    self._box_regs, target_width=tw, spread=sp,
                )
            if isinstance(meaning, CharToken) and meaning.catcode == Catcode.BEGIN_GROUP:
                # Implicit vbox: exec_vbox consumes the opening `{`.
                self._expander.push_tokens([tok])
                return exec_vbox(
                    self._expander, self._font_manager, self._group_stack,
                    self._box_regs,
                )
            raise EngineError("\\vcenter expects a box or { }")
        finally:
            self._alignment_math_context -= 1

    def _apply_vtop(self, box: VlistNode) -> VlistNode:
        """Apply \\vtop reference-point semantics to a finished vbox."""
        from aspose_tex._engine.box_primitives import _first_baseline_height

        total = box.height + box.depth
        first_height = _first_baseline_height(box.list, box.height)
        box.height = first_height
        box.depth = max(0, total - first_height)
        return box

    # ------------------------------------------------------------------
    # Font commands
    # ------------------------------------------------------------------

    def _exec_font(self) -> None:
        """Execute one font assignment, clearing its prefix even on failure."""
        try:
            self._assign_font()
        finally:
            self._group_stack.consume_global()

    def _assign_font(self) -> None:
        """\\font\\cs=<tfm-name> [at <dimen> | scaled <number>]."""
        from aspose_tex._engine.dimparser import (
            _scan_keyword,
            parse_dimen,
        )
        # TeX's get_r_token: the name is read raw, never expanded,
        # so plain's \big macro can be redefined as a font.
        cs_tok = self._expander._next_raw()
        while isinstance(cs_tok, CharToken) and cs_tok.catcode == Catcode.SPACE:
            cs_tok = self._expander._next_raw()
        if not isinstance(cs_tok, ControlSequenceToken):
            raise EngineError(
                f"\\font must be followed by a control sequence, got {cs_tok!r}"
            )
        cs_name = cs_tok.name
        is_global = self._group_stack.is_global_pending
        from aspose_tex._engine.meanings import Binding
        with self._bindings.scanning_binding(
            cs_name, Binding(BindingKind.FONT, self._font_manager._nullfont_id),
            is_global=is_global,
        ):
            # Skip optional '='
            tok = self._expander.peek()
            if isinstance(tok, CharToken) and tok.char == "=" and tok.catcode == Catcode.OTHER:
                self._next_token()

            # Read TFM name
            tfm_name = self._scan_font_name()

            # Optional modifier
            at_sp: int | None = None
            scaled: int | None = None
            if _scan_keyword(self._expander, "at"):
                at_sp = parse_dimen(self._expander)
            elif _scan_keyword(self._expander, "scaled"):
                scaled = self._parse_font_scaled_integer()

            # Validate before publishing a new loaded record/binding/id_text.
            self._font_manager._load_tfm(tfm_name.removesuffix(".tfm"))
            self._font_manager.load_font(
                cs_name, tfm_name, at_sp=at_sp, scaled=scaled,
                default_hyphenchar=self._get_named_int("defaulthyphenchar"),
                default_skewchar=self._get_named_int("defaultskewchar"),
                is_global=is_global,
            )
        self._expander.fire_after_assignment()

    def _parse_font_scaled_integer(self) -> int:
        """Parse a ``\font ... scaled`` integer, including plain TeX helpers."""
        from aspose_tex._engine.dimparser import parse_integer

        tok = self._expander._next_raw()
        while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
            tok = self._expander._next_raw()
        if isinstance(tok, ControlSequenceToken) and tok.name == "magstephalf":
            return 1095
        if isinstance(tok, ControlSequenceToken) and tok.name == "magstep":
            step = parse_integer(self._expander, allow_negative=False)
            values = [1000, 1200, 1440, 1728, 2074, 2488]
            if 0 <= step < len(values):
                return values[step]
            raise EngineError(f"\\magstep{step} is not defined")
        if tok is not None:
            self._expander._stack.append(tok)
        return parse_integer(self._expander)

    def _scan_font_name(self) -> str:
        """Scan a font file name (sequence of letter/other chars)."""
        chars: list[str] = []
        while True:
            tok = self._expander.get_x_token()
            if tok is None:
                break
            if isinstance(tok, CharToken) and tok.catcode in (Catcode.LETTER, Catcode.OTHER):
                chars.append(tok.char)
            elif isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
                break
            else:
                self._expander._stack.append(tok)
                break
        if not chars:
            raise EngineError("Missing font name after \\font\\cs=")
        return "".join(chars)

    def _exec_nullfont(self) -> None:
        r"""Select the null font (all metrics zero).

        ``\nullfont`` is pre-registered by :class:`FontManager` at construction
        (TeX font 0 is always defined), so this only needs to select it.
        See.
        """
        self._font_manager.select_font_id(self._font_manager._nullfont_id)

    # ------------------------------------------------------------------
    # Document end
    # ------------------------------------------------------------------

    def _exec_bye(self) -> None:
        """\\bye — end the document (Plain TeX: \\par\\vfill\\supereject\\end)."""
        if self._mode_stack.current == ModeKind.HORIZONTAL:
            self._end_paragraph(build=False)
        self._contribute(make_vfill_glue())
        self._contribute(PenaltyNode(penalty=NEG_INF_PENALTY))
        self._build_page_if_outer()
        self._done = True

    def _exec_end(self) -> None:
        """\\end — terminate processing."""
        if self._mode_stack.current == ModeKind.HORIZONTAL:
            self._end_paragraph(build=False)
        self._done = True

    def _exec_eject_cmd(self) -> None:
        r"""\\eject — force a page break (plain TeX: ``\\par\\break``).

        Per plain.tex line 1104, ``\\def\\eject{\\par\\break}`` where
        ``\\break`` is ``\\penalty-10000``.  This is **not**
        ``\\vfil\\penalty-10000``; an author who wants page-fill stretch
        on a forced break must place ``\\vfil`` (or use ``\\filbreak``)
        themselves.  See.
        """
        if self._mode_stack.current == ModeKind.HORIZONTAL:
            self._end_paragraph(build=False)
        self._contribute(PenaltyNode(penalty=NEG_INF_PENALTY))
        self._build_page_if_outer()

    # ------------------------------------------------------------------
    # Horizontal list helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def _next_token(self) -> Token | None:
        """Read the next token from the expander (consuming it)."""
        return next(self._token_iter, None)

    def _peek_token(self) -> Token | None:
        """Peek at the next token without consuming."""
        return self._expander.peek()
