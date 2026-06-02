"""TeX interpreter: mode machine, primitive dispatch, component wiring.

Implements: the central integration layer
that connects Expander, FontManager, RegisterSet, GroupStack, PageBuilder, and
output devices into a working end-to-end pipeline.

See and for design rationale.
"""
from __future__ import annotations

import warnings
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
 from aspose_tex.presentation import OutputDevice

from aspose_tex._engine.alignment import build_stub_handlers
from aspose_tex._engine.box_primitives import _PREVDEPTH_SENTINEL
from aspose_tex._engine.box_registers import BoxRegisterSet
from aspose_tex._engine.code_arrays import CodeArrays
from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.group import GroupKind, GroupStack
from aspose_tex._engine.inserts import InsertAccumulator
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
 exec_write,
)
from aspose_tex._engine.linebreak import LinebreakParams
from aspose_tex._engine.marks import MarksRegistry
from aspose_tex._engine.math_shell import _build_math_shell_registry
from aspose_tex._engine.named_parameters import (
 NamedParameterRegistry,
 _register_appendix_a,
)
from aspose_tex._engine.nodes import (
 NEG_INF_PENALTY,
 RUNNING_DIMEN,
 CharNode,
 GlueNode,
 GlueSign,
 HlistNode,
 KernNode,
 LeadersKind,
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
from aspose_tex._engine.registers import Glue, GlueOrder, RegisterSet
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._fonts.math_family_registry import MathFamilyRegistry
from aspose_tex._input.catcode import Catcode, CatcodeTable
from aspose_tex._input.reader import FileInputSource, InputReader, InputSource
from aspose_tex._input.token import CharToken, ControlSequenceToken, Token
from aspose_tex._input.tokenizer import Tokenizer
from aspose_tex.exceptions import EngineError, InputError

# ---------------------------------------------------------------------------
# ModeKind enum ( FR-1)
# ---------------------------------------------------------------------------

class ModeKind(Enum):
 """TeX processing modes ( FR-1, FR-1/FR-2).

 Math modes are load-without-execute in M3: math-mode bodies parse through
 the shell surface, emit no nodes, and leave real math typesetting
 to M4.

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
# ModeStack ( FR-1)
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

 def push(self, mode: ModeKind) -> None:
 """Push a new mode onto the stack."""
 self._stack.append(mode)

 def pop(self) -> ModeKind:
 """Pop and return the top mode.

 Raises:
 EngineError: If only OUTER_VERTICAL remains (cannot pop the base).
 """
 if len(self._stack) <= 1:
 raise EngineError("Cannot pop base mode")
 return self._stack.pop()


# ---------------------------------------------------------------------------
# Plain TeX defaults (hardcoded for M1)
# ---------------------------------------------------------------------------

_HSIZE = 30_785_886 # 6.5 in
_VSIZE = 42_152_952 # 8.9 in
_PARINDENT = 1_310_720 # 20 pt
_BASELINESKIP = 786_432 # 12 pt
_TOPSKIP = 655_360 # 10 pt
_MAXDEPTH = 262_144 # 4 pt
_LINESKIPLIMIT = 0
_LINESKIP = 65_536 # 1 pt
_PRETOLERANCE = 100
_TOLERANCE = 200
_LINEPENALTY = 10
_ADJDEMERITS = 10_000
_PARFILLSKIP = Glue(0, 65_536, GlueOrder.FIL, 0, GlueOrder.NORMAL)
_LEFTSKIP = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
_RIGHTSKIP = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
_MAX_DEAD_CYCLES = 25


# ---------------------------------------------------------------------------
# \pageno register adapter
# ---------------------------------------------------------------------------

class _Count0PagenoRegister:
 """Adapts ``RegisterSet`` to the ``PageNumberRegister`` protocol.

 \\pageno is defined by plain.tex as ``\\countdef\\pageno=0`` — i.e. an
 alias for ``\\count0``. The interpreter sets up that alias before
 constructing the output routine; this adapter gives ``PlainOutputRoutine``
 and ``PageBuilder`` read/write access to the same slot.
 """

 __slots__ = ("_rs",)

 def __init__(self, register_set: RegisterSet) -> None:
 self._rs = register_set

 def get_pageno(self) -> int:
 """Return current \\pageno (== \\count0)."""
 return self._rs.get_count(0)

 def set_pageno(self, value: int) -> None:
 """Set \\pageno (== \\count0)."""
 self._rs.set_count(0, value)


# ---------------------------------------------------------------------------
# TeXInterpreter ( FR-2, FR-7, FR-10)
# ---------------------------------------------------------------------------

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
 return device.get_bytes() # type: ignore[return-value]

 def run_with_device(
 self,
 source: InputSource,
 device: OutputDevice,
 *,
 mag: int = 1000,
 ) -> None:
 """Process TeX source, directing output to the given device.

 This is the internal entry point used by ``TeXJob``. It replaces the
 hardwired DVI pipeline in ``run()`` with a device-agnostic flow.

 Args:
 source: TeX input source.
 device: Output device (provides the backend writer).
 mag: Magnification * 1000.
 """
 # Step 1 — fresh state
 group_stack = GroupStack()
 # Catcodes share the group stack so \catcode changes are group-scoped
 # ( / FR-5). Required for AC-1.
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
 # \the\<named-param> resolves through the registry. The Appendix A
 # catalog is populated later, after PageBuilderConfig exists, because
 # vsize/topskip/maxdepth need an on_set mirror onto it (
 # §"Migration plan", ).
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
 box_provider=box_regs,
 job_name_provider=lambda: self._job_name,
 code_arrays_provider=lambda: self._code_arrays,
 )
 # Allow dimparser to resolve register/alias/chardef constant references
 # (parse_integer / parse_dimen) and to read \mag for true* units.
 expander._register_set = register_set
 expander._named_params = named_params
 expander._interpreter = self

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
 hsize=_HSIZE, # / : \hsize mirror seed (page-box width).
 )

 # \pageno is an alias for \count0, initialised to 1 (plain.tex line 1144).
 register_set.define_alias("pageno", "count", 0)
 register_set.set_count(0, 1)
 pageno_register = _Count0PagenoRegister(register_set)

 # Populate the Appendix A catalog now that PageBuilderConfig exists,
 # so vsize / maxdepth / topskip can carry on_set mirror callbacks
 # (§"Migration plan", ).
 _register_appendix_a(named_params, page_config=config)

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
 insert_accumulator = InsertAccumulator(group_stack)
 expander._marks_provider = marks_registry
 page_builder = PageBuilder(
 config, backend, output_routine,
 pageno_register=pageno_register,
 marks_registry=marks_registry,
 box_registers=box_regs,
 insert_accumulator=insert_accumulator,
 named_params=named_params,
 expander=expander,
 font_manager=font_manager,
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
 self._code_arrays = code_arrays
 self._named_params = named_params
 self._box_regs = box_regs
 self._page_builder = page_builder
 self._marks = marks_registry
 self._mode_stack = ModeStack()
 self._math_family_registry = MathFamilyRegistry(group_stack, font_manager)
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
 self._spacefactor = 1000
 self._prev_depth = -65_536_000
 self._prev_graf = 0
 self._badness = 0
 self._last_skip = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
 self._last_penalty = 0
 self._last_kern = 0
 self._sfcodes: dict[int, int] = {
 ord("."): 3000,
 ord("!"): 3000,
 ord("?"): 3000,
 }
 self._after_space = False
 self._page_number = 1
 self._done = False
 self._parindent = _PARINDENT
 # \hsize is read live from named-param slot 258 at \par time via
 # _current_hsize() — no stale instance cache.
 self._hangindent = 0
 self._hangafter = 1
 self._parshape: list[tuple[int, int]] | None = None
 self._split_capture_callback = self._marks.capture_split
 self._internal_quantities = self._build_internal_quantities()

 # Step 6 — main loop
 self._token_iter = iter(expander)
 if self._load_format not in (False, None):
 self.load_format(str(self._load_format))
 for token in self._token_iter:
 if self._done and not page_builder.output_cycle_pending:
 break
 self._dispatch(token)
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

 page_builder.end_of_document()
 self._token_iter = iter(expander)
 while page_builder.output_cycle_pending:
 token = next(self._token_iter, None)
 if token is None:
 raise EngineError("output routine ended before finish sentinel")
 self._dispatch(token)
 device.finalize()

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
 ``extra_format_paths``, then the current working directory. A missing
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
 # Primitive registry ( FR-7)
 # ------------------------------------------------------------------

 def _build_primitives(self) -> dict[str, object]:
 """Build the primitive dispatch table.

 Returns:
 A dict mapping CS names to zero-arg handler callables.
 """
 primitives: dict[str, object] = {
 # No-op
 "relax": lambda: None,
 " ": self._exec_control_space,
 # Private output-cycle sentinel; unreachable from TeX source
 # because the control-sequence name starts with NUL.
 SENTINEL_FINISH_OUTPUT_CS: self._page_builder._finish_output_cycle,
 # Group commands (moved from Expander per )
 "begingroup": self._exec_begingroup,
 "endgroup": self._exec_endgroup,
 "aftergroup": self._exec_aftergroup,
 # Paragraph commands
 "par": self._exec_par_cmd,
 "indent": self._exec_indent,
 "noindent": self._exec_noindent,
 # Horizontal glue helpers
 "hfil": lambda: self._append_to_hlist(make_hfil_glue()),
 "hfill": lambda: self._append_to_hlist(make_hfill_glue()),
 "hfilneg": lambda: self._append_to_hlist(make_hfilneg_glue()),
 "hss": lambda: self._append_to_hlist(make_hss_glue()),
 # Vertical primitives
 "vfil": lambda: self._contribute(make_vfil_glue()),
 "vfill": lambda: self._contribute(make_vfill_glue()),
 "vfilneg": lambda: self._contribute(make_vfilneg_glue()),
 "vss": lambda: self._contribute(make_vss_glue()),
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
 "hangindent": self._exec_hangindent_cmd,
 "hangafter": self._exec_hangafter_cmd,
 "parshape": self._exec_parshape_cmd,
 "char": self._exec_char_cmd,
 "accent": self._exec_accent_cmd,
 "discretionary": self._exec_discretionary_cmd,
 "vrule": self._exec_vrule_cmd,
 "fontdimen": self._exec_fontdimen_cmd,
 "skewchar": self._exec_skewchar_cmd,
 "hyphenchar": self._exec_hyphenchar_cmd,
 "textfont": self._exec_textfont_cmd,
 "scriptfont": self._exec_scriptfont_cmd,
 "scriptscriptfont": self._exec_scriptscriptfont_cmd,
 "eqno": lambda: self._math_shell.exec_eqno_or_leqno("eqno"),
 "leqno": lambda: self._math_shell.exec_eqno_or_leqno("leqno"),
 "mark": self._exec_mark_cmd,
 "insert": self._exec_insert_cmd,
 # `\/` is a real TeX primitive (italic correction = `\kern\fontdimen1\font`)
 # — plain.tex does not redefine it as a macro. The no-op is
 # functionally correct for upright text in M3; the real italic kern
 # is deferred until italic fonts land in M4 (§"Primitive
 # shortcut catalogue" row 6 — retirement reclassified as
 # "real-primitive implementation" rather than "retire to macro",
 # because there is no plain.tex macro to take over). TODO .
 "/": lambda: None,
 "leaders": lambda: self._exec_leaders_cmd(LeadersKind.NORMAL),
 "cleaders": lambda: self._exec_leaders_cmd(LeadersKind.C),
 "xleaders": lambda: self._exec_leaders_cmd(LeadersKind.X),
 # Vertical mode items
 "vskip": self._exec_vskip,
 "kern": self._exec_kern_cmd,
 "hrule": self._exec_hrule,
 "penalty": self._exec_penalty_cmd,
 # \vsize / \topskip / \maxdepth: dispatched through
 # NamedParameterRegistry as of ; their on_set mirrors keep
 # PageBuilderConfig in sync (§"Migration plan").
 # Code-array primitives (§5b — )
 "catcode": self._exec_catcode,
 "mathcode": self._exec_mathcode,
 "delcode": self._exec_delcode,
 "sfcode": self._exec_sfcode,
 "lccode": self._exec_lccode,
 "uccode": self._exec_uccode,
 # Font commands ( — stubs for now)
 "font": self._exec_font,
 "nullfont": self._exec_nullfont,
 # Document end
 "bye": self._exec_bye,
 "end": self._exec_end,
 # I/O primitives ( — )
 "message": lambda: exec_message(self),
 "write": lambda: exec_write(self),
 "immediate": lambda: exec_immediate(self),
 "errmessage": lambda: exec_errmessage(self),
 "dump": lambda: exec_dump(self),
 "openin": lambda: exec_openin(self),
 "openout": lambda: exec_openout(self),
 "closein": lambda: exec_closein(self),
 "closeout": lambda: exec_closeout(self),
 "read": lambda: exec_read(self),
 }
 primitives.update(build_stub_handlers())
 return primitives

 # ------------------------------------------------------------------
 # Main dispatch ( FR-2)
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
 return

 if cat == Catcode.END_GROUP:
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
 if cat in (Catcode.SUBSCRIPT, Catcode.SUPERSCRIPT):
 self._math_shell.consume_math_field()
 return
 if cat in (Catcode.LETTER, Catcode.OTHER, Catcode.ACTIVE):
 self._dispatch_char_in_math(token)
 return

 if cat in (Catcode.LETTER, Catcode.OTHER):
 if mode in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
 self._handle_char(token)
 elif mode == ModeKind.OUTER_VERTICAL:
 self._begin_paragraph()
 self._dispatch(token) # re-dispatch in H mode
 elif mode == ModeKind.INTERNAL_VERTICAL:
 raise EngineError("Character token in internal vertical mode")
 return

 if cat == Catcode.SPACE:
 if mode == ModeKind.HORIZONTAL:
 self._handle_space()
 # In V / IV / RH: discard (TeX rule)
 return

 if cat == Catcode.ACTIVE:
 self._dispatch_active_char(token)
 return

 # Other catcodes are still outside the M3 text-mode surface.

 def _handle_math_shift(self, token: CharToken) -> None:
 """Open or close inline/display math on ``$`` ( cascade #1)."""
 mode = self._mode_stack.current

 if mode in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
 self._begin_paragraph()
 self._dispatch_char(token)
 return

 if mode == ModeKind.HORIZONTAL:
 if self._peek_is_math_shift():
 self._consume_peeked_token()
 self._mode_stack.push(ModeKind.MATH_DISPLAY)
 self._push_toks_if_any(259)
 return
 self._mode_stack.push(ModeKind.MATH)
 self._push_toks_if_any(258)
 return

 if mode == ModeKind.RESTRICTED_HORIZONTAL:
 if self._peek_is_math_shift():
 raise EngineError("display math is not allowed in restricted horizontal mode")
 self._mode_stack.push(ModeKind.MATH)
 self._push_toks_if_any(258)
 return

 if mode == ModeKind.MATH:
 if self._peek_is_math_shift():
 raise EngineError("mismatched $$ in inline math")
 self._mode_stack.pop()
 self._math_shell.check_left_right_balanced()
 return

 if mode == ModeKind.MATH_DISPLAY:
 if not self._peek_is_math_shift():
 raise EngineError("$$ display-math close expected")
 self._consume_peeked_token()
 self._mode_stack.pop()
 self._math_shell.check_left_right_balanced()
 return

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
 """Dispatch an active character through the macro table ( Q4)."""
 from aspose_tex._engine.macro import MacroDefinition

 meaning = self._expander.macros.get(token.char)
 if meaning is None:
 loc = self._reader.current_location
 raise EngineError(f"Undefined active character: {token.char} at {loc}")
 if isinstance(meaning, MacroDefinition):
 self._expander.push_tokens(list(meaning.replacement))
 return
 self._expander.push_tokens([meaning])

 def _dispatch_char_in_math(self, token: CharToken) -> None:
 """Consume a character token in math mode without node emission."""
 from aspose_tex._engine.macro import MacroDefinition

 code = self._code_arrays.get_mathcode(ord(token.char))
 if code != 0x8000:
 return
 meaning = self._expander.macros.get(token.char)
 if meaning is None:
 raise EngineError("math-active char without macro")
 if isinstance(meaning, MacroDefinition):
 self._expander.push_tokens(list(meaning.replacement))
 return
 self._expander.push_tokens([meaning])

 def _dispatch_cs(self, token: ControlSequenceToken) -> None:
 """Dispatch a ControlSequenceToken."""
 name = token.name

 # 1. Primitive registry
 handler = self._primitives.get(name)
 if handler is not None:
 handler()
 return

 # Math-shell dispatch ( / §"Components → 1 →
 # `_dispatch_cs` math-mode arm"): math-mode-only primitives such as
 # \over / \mathopen / \mathaccent are consulted ONLY when the current
 # mode is MATH or MATH_DISPLAY; outside math mode they fall through
 # so the standard "Undefined control sequence" path runs.
 if (
 self._mode_stack.current in (ModeKind.MATH, ModeKind.MATH_DISPLAY)
 and self._math_shell.dispatch_if_known(name)
 ):
 return

 # 2. InternalQuantityRegistry. It supersedes the
 # older Appendix A placeholder entries for page-state names.
 internal_entry = self._internal_quantities.lookup(name)
 if internal_entry is not None:
 self._internal_quantities.dispatch_assignment(internal_entry, self._expander)
 return

 # 3. NamedParameterRegistry (§5c — ). Sits between
 # primitives and font check so user macros (Expander expands first)
 # still win, but \hsize / \tolerance / etc. parse without falling
 # through to the "Undefined control sequence" branch.
 named_entry = self._named_params.lookup(name)
 if named_entry is not None:
 self._named_params.dispatch_assignment(named_entry, self._expander)
 return

 # 4. Font CS
 if self._font_manager.is_font(name):
 self._font_manager.select_font(name)
 return

 # 5. Register command
 if self._register_set.execute(name, self._expander):
 return

 # 6. \chardef / \mathchardef constant — emit char in H mode (§5c).
 # Integer-coercion paths (e.g. ``\catcode`\~=\active``) are handled by
 # parse_integer's resolve_constant fallback.
 const = self._register_set.resolve_constant(name)
 if const is not None:
 kind, value = const
 if kind == "chardef":
 self._handle_chardef_constant(value)
 return
 if kind == "mathchardef" and self._mode_stack.current in (
 ModeKind.MATH,
 ModeKind.MATH_DISPLAY,
 ):
 return
 # Outside math mode, behave as a no-op (integer coercion already
 # handled by parse_integer fallback).
 return

 # 7. Unknown CS — include SourceLocation in message
 loc = self._reader.current_location
 raise EngineError(
 f"Undefined control sequence \\{name} at {loc}"
 )

 def _handle_chardef_constant(self, code: int) -> None:
 """Treat a \\chardef constant as a character in H/RH mode (§5c).

 In OUTER_VERTICAL / INTERNAL_VERTICAL the engine starts a paragraph
 first and re-dispatches; in HORIZONTAL / RESTRICTED_HORIZONTAL it
 synthesises a ``CharToken(chr(code), Catcode.OTHER)`` and routes
 through ``_handle_char`` so that lig/kern/spacefactor still apply.
 """
 mode = self._mode_stack.current
 if mode in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
 self._begin_paragraph()
 self._handle_chardef_constant(code)
 return
 synthetic = CharToken(chr(code), Catcode.OTHER)
 self._handle_char(synthetic)

 # ------------------------------------------------------------------
 # Group commands (moved from Expander per )
 # ------------------------------------------------------------------

 def _exec_begingroup(self) -> None:
 """\\begingroup — open a SEMI_SIMPLE group."""
 self._group_stack.open_group(GroupKind.SEMI_SIMPLE)

 def _exec_endgroup(self) -> None:
 """\\endgroup — close a SEMI_SIMPLE group."""
 aftergroup_tokens, _kind = self._group_stack.close_group()
 if aftergroup_tokens:
 self._expander.push_tokens(aftergroup_tokens)

 def _exec_aftergroup(self) -> None:
 """\\aftergroup — read next token and queue for after-group insertion."""
 tok = self._next_token()
 if tok is None:
 raise EngineError("\\aftergroup: missing token")
 self._group_stack.push_aftergroup(tok)

 # ------------------------------------------------------------------
 # Character processing
 # ------------------------------------------------------------------

 def _handle_char(self, token: CharToken) -> None:
 """Process a character token in H/RH mode: create CharNode, apply lig/kern."""
 metrics = self._font_manager.current_metrics
 if metrics is None:
 raise EngineError("No font selected")
 font_name = self._font_manager._current # type: ignore[attr-defined]
 char_code = ord(token.char)

 # Ligature loop
 while True:
 next_tok = self._expander.peek()
 if not (isinstance(next_tok, CharToken)
 and next_tok.catcode in (Catcode.LETTER, Catcode.OTHER)):
 break
 next_code = ord(next_tok.char)
 lig = metrics.ligature(char_code, next_code)
 if lig is None:
 break
 next(self._token_iter) # consume
 char_code = lig

 # Emit CharNode
 node = CharNode(char=char_code, font_name=font_name)
 self._append_to_hlist(node)

 # Kern check
 next_tok = self._expander.peek()
 if (isinstance(next_tok, CharToken)
 and next_tok.catcode in (Catcode.LETTER, Catcode.OTHER)):
 next_code = ord(next_tok.char)
 kern_amount = metrics.kern(char_code, next_code)
 if kern_amount is not None and kern_amount != 0:
 self._append_to_hlist(KernNode(width=kern_amount, explicit=False))

 # Spacefactor update
 self._update_spacefactor(char_code)
 self._after_space = False

 def _handle_space(self) -> None:
 """Process a space token in H mode: insert inter-word GlueNode."""
 if self._after_space:
 return
 self._after_space = True

 metrics = self._font_manager.current_metrics
 if metrics is None:
 return
 font_name = self._font_manager._current # type: ignore[attr-defined]

 sf = self._spacefactor
 if sf >= 2000:
 extra = self._font_manager.fontdimen(font_name, 7)
 space = self._font_manager.fontdimen(font_name, 2) + extra
 else:
 space = self._font_manager.fontdimen(font_name, 2)
 stretch = self._font_manager.fontdimen(font_name, 3)
 shrink = self._font_manager.fontdimen(font_name, 4)

 # Spacefactor stretch modification (TeX §1042)
 if sf != 1000:
 stretch = stretch * sf // 1000

 glue = Glue(space, stretch, GlueOrder.NORMAL, shrink, GlueOrder.NORMAL)
 self._append_to_hlist(GlueNode(glue=glue))

 def _exec_control_space(self) -> None:
 """Control-space primitive used by plain.tex active tie macros."""
 if self._mode_stack.current in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
 self._begin_paragraph()
 if self._mode_stack.current in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
 self._handle_space()

 def _update_spacefactor(self, char_code: int) -> None:
 """Update spacefactor after typesetting a character (TeX §1034)."""
 sfcode = self._get_sfcode(char_code)
 if sfcode > 1000:
 self._spacefactor = sfcode
 elif sfcode < 1000 and self._spacefactor > 1000:
 self._spacefactor = 1000
 else:
 self._spacefactor = sfcode if sfcode != 0 else self._spacefactor

 def _get_sfcode(self, char_code: int) -> int:
 """Return the space factor code for a character (IniTeX defaults)."""
 if 65 <= char_code <= 90: # A-Z
 return 999
 return self._sfcodes.get(char_code, 1000)

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
 self._page_builder._prev_depth = int_value
 self._page_builder._page_depth = int_value

 def _set_badness(self, value: int) -> None:
 """Record the last hbox/vbox glue-setting badness."""
 self._badness = value

 def _record_last_skip(self, glue: Glue) -> None:
 self._last_skip = glue
 self._last_penalty = 0
 self._last_kern = 0

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
 """Contribute to the page builder while maintaining internal quantities."""
 if isinstance(node, GlueNode):
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
 # prev_depth <- ignore_depth (-1000 pt sentinel)
 # Mirrors PageBuilder._prev_depth update inside contribute()
 # ( v5 Component 6) and matches exec_vbox's in-vbox
 # _track_rule / _track_splice convention so the
 # \prevdepth named-parameter registry read returns -1000 pt
 # after a vertical-mode \hrule regardless of whether the
 # rule contributed in outer-V-mode or inside a \vbox{...}
 # group. See v6 §Component 2.
 self._prev_depth = _PREVDEPTH_SENTINEL

 def _append_to_hlist(self, node) -> None:
 """Append to the current horizontal list and maintain last-node caches."""
 if self._par_list is None:
 raise EngineError("horizontal list is not active")
 if isinstance(node, GlueNode):
 self._record_last_skip(node.glue)
 elif isinstance(node, PenaltyNode):
 self._record_last_penalty(node.penalty)
 elif isinstance(node, KernNode):
 self._record_last_kern(node.width)
 else:
 self._record_non_discardable()
 self._par_list.append(node)

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
 registry.register(
 "prevgraf",
 QuantityKind.INT,
 getter=lambda: self._prev_graf,
 allowed_modes=vmode,
 )
 registry.register("badness", QuantityKind.INT, getter=lambda: self._badness)
 registry.register("lastskip", QuantityKind.SKIP, getter=lambda: self._last_skip)
 registry.register("lastpenalty", QuantityKind.INT, getter=lambda: self._last_penalty)
 registry.register("lastkern", QuantityKind.DIMEN, getter=lambda: self._last_kern)
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
 registry.register("deadcycles", QuantityKind.INT, getter=lambda: self._page_builder.dead_cycles)
 registry.register(
 "insertpenalties",
 QuantityKind.INT,
 getter=lambda: self._page_builder.insert_penalties,
 )
 return registry

 # ------------------------------------------------------------------
 # Paragraph commands
 # ------------------------------------------------------------------

 def _begin_paragraph(self, indent: bool = True) -> None:
 """Switch from vertical to horizontal mode and start a new paragraph."""
 self._mode_stack.push(ModeKind.HORIZONTAL)
 parindent = self._parindent if indent else 0
 self._par_list = ParagraphList(parindent=parindent)
 self._spacefactor = 1000
 self._after_space = False

 def _exec_par_cmd(self) -> None:
 """\\par — end the current paragraph."""
 if self._mode_stack.current == ModeKind.HORIZONTAL:
 self._end_paragraph()

 def _exec_indent(self) -> None:
 """\\indent — start paragraph with indentation."""
 if self._mode_stack.current in (
 ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL,
 ):
 self._begin_paragraph(indent=True)

 def _exec_noindent(self) -> None:
 """\\noindent — start paragraph without indentation."""
 if self._mode_stack.current in (
 ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL,
 ):
 self._begin_paragraph(indent=False)

 def _end_paragraph(self) -> None:
 """Finalise the current paragraph: line-break and contribute to page builder."""
 if self._par_list is None:
 return

 # TODO M4 : read interpreter._hangindent / _hangafter / _parshape.
 params = LinebreakParams(
 # Read \hsize LIVE from the register at \par time ( /
 # ) so user \hsize assignments reach break selection; the
 # register read is group-aware (correct under {\hsize=… \par}).
 hsize=self._current_hsize(),
 tolerance=_TOLERANCE,
 pretolerance=_PRETOLERANCE,
 linepenalty=_LINEPENALTY,
 adjdemerits=_ADJDEMERITS,
 leftskip=_LEFTSKIP,
 rightskip=_RIGHTSKIP,
 parfillskip=_PARFILLSKIP,
 )

 lines = exec_par(self._par_list, params, self._font_manager)

 # Parskip glue (plain TeX: 0pt plus 1pt) is added BETWEEN paragraphs,
 # not before the first box on a page (TeX: The Program §1098 — the
 # equivalent guard is `prevdepth >= -1000pt`). Suppressing it here
 # keeps the leading parskip out of the body MVL on \eject-terminated
 # pages where NORMAL is the highest stretch order; otherwise the
 # spurious glue would absorb stretch and shift paragraph 1 down by
 # ratio*1pt. Surfaced by / (same upstream-injection
 # pattern as the deleted exec_eject \vfil contribution).
 if not self._page_builder.is_at_top_of_page:
 parskip = GlueNode(Glue(0, 65_536, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
 self._contribute(parskip)

 for line in lines:
 self._contribute(line)

 self._prev_graf += len(lines)

 self._par_list = None
 self._mode_stack.pop()

 # ------------------------------------------------------------------
 # Vertical mode items
 # ------------------------------------------------------------------

 def _exec_vskip(self) -> None:
 """\\vskip <glue> — insert vertical glue."""
 from aspose_tex._engine.dimparser import parse_glue
 glue = parse_glue(self._expander)
 self._contribute(GlueNode(glue=glue))

 def _exec_kern_cmd(self) -> None:
 """\\kern <dimen> — mode-aware kern."""
 from aspose_tex._engine.dimparser import parse_dimen
 amount = parse_dimen(self._expander)
 mode = self._mode_stack.current
 if mode in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
 self._append_to_hlist(KernNode(width=amount, explicit=True))
 else:
 self._contribute(KernNode(width=amount, explicit=True))

 def _exec_hrule(self) -> None:
 """\\hrule [width <d>] [height <d>] [depth <d>]."""
 from aspose_tex._engine.dimparser import _scan_keyword, parse_dimen
 width = RUNNING_DIMEN
 height = 26_214 # 0.4pt
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
 mode = self._mode_stack.current
 if mode == ModeKind.HORIZONTAL:
 self._end_paragraph()
 self._contribute(rule)

 def _exec_vrule_cmd(self) -> None:
 """\\vrule [width <d>] [height <d>] [depth <d>]."""
 from aspose_tex._engine.dimparser import _scan_keyword, parse_dimen
 width = 26_214 # 0.4pt
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
 if mode in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
 self._append_to_hlist(rule)
 else:
 self._contribute(rule)

 def _exec_penalty_cmd(self) -> None:
 """\\penalty <number> — mode-aware penalty."""
 from aspose_tex._engine.dimparser import parse_integer
 val = parse_integer(self._expander)
 mode = self._mode_stack.current
 if mode in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
 exec_penalty(val, self._par_list) # type: ignore[arg-type]
 self._record_last_penalty(val)
 else:
 self._contribute(PenaltyNode(penalty=val))

 # ------------------------------------------------------------------
 # Code-array primitives (§5b — )
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
 value = parse_integer(self._expander) # may be -1
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
 """\\hbox — build an hbox and add to current list."""
 from aspose_tex._engine.box_primitives import exec_hbox
 box = exec_hbox(self._expander, self._font_manager,
 self._group_stack, self._box_regs)
 self._add_box_to_current_list(box)

 def _exec_vbox_cmd(self) -> None:
 """\\vbox — build a vbox and add to current list."""
 from aspose_tex._engine.box_primitives import exec_vbox
 box = exec_vbox(self._expander, self._font_manager,
 self._group_stack, self._box_regs)
 self._add_box_to_current_list(box)

 def _exec_vtop_cmd(self) -> None:
 """\\vtop — build a vtop and add to current list."""
 from aspose_tex._engine.box_primitives import exec_vtop
 box = exec_vtop(self._expander, self._font_manager,
 self._group_stack, self._box_regs)
 self._add_box_to_current_list(box)

 def _exec_setbox_cmd(self) -> None:
 """\\setbox<n>=<box> — assign a box register."""
 from aspose_tex._engine.dimparser import parse_integer
 idx = parse_integer(self._expander)
 self._eat_optional_equals()
 box = self._scan_box_value("\\setbox")
 self._box_regs.setbox(idx, box)
 self._expander.fire_after_assignment()

 def _scan_box_value(self, command: str) -> HlistNode | VlistNode | None:
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
 return exec_hbox(
 self._expander, self._font_manager, self._group_stack,
 self._box_regs, target_width=tw, spread=sp,
 )
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
 raise EngineError(f"{command}: expected box primitive, got \\{tok.name}")

 def _exec_box_cmd(self) -> None:
 """\\box — use and clear a box register."""
 from aspose_tex._engine.dimparser import parse_integer
 idx = parse_integer(self._expander)
 box = self._box_regs.getbox(idx) # getbox already voids the register
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
 """\\hskip<glue> — append horizontal glue, starting a paragraph in V-mode."""
 from aspose_tex._engine.dimparser import parse_glue
 if self._mode_stack.current in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
 self._begin_paragraph()
 self._append_to_hlist(GlueNode(parse_glue(self._expander)))

 def _exec_hglue_cmd(self) -> None:
 """\\hglue<glue> — M3 top-level horizontal glue approximation."""
 self._exec_hskip_cmd()

 def _exec_vglue_cmd(self) -> None:
 """\\vglue<glue> — append vertical glue."""
 self._exec_vskip()

 def _exec_unhbox_cmd(self, *, copy: bool) -> None:
 """\\unhbox / \\unhcopy — splice an hbox register into the current hlist."""
 from aspose_tex._engine.box_primitives import exec_unbox
 if self._mode_stack.current in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
 raise EngineError("\\unhbox in vertical mode")
 for node in exec_unbox(self._expander, self._box_regs, copy=copy, vertical=False):
 self._append_to_hlist(node)

 def _exec_unvbox_cmd(self, *, copy: bool) -> None:
 """\\unvbox / \\unvcopy — splice a vbox register into the current vlist."""
 from aspose_tex._engine.box_primitives import exec_unbox
 if self._mode_stack.current in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
 raise EngineError("\\unvbox in horizontal mode")
 for node in exec_unbox(self._expander, self._box_regs, copy=copy, vertical=True):
 self._contribute(node)

 def _exec_unskip_cmd(self) -> None:
 """\\unskip — remove trailing glue from the current list if present."""
 from aspose_tex._engine.box_primitives import exec_unskip
 from aspose_tex._engine.nodes import GlueNode
 target = self._current_node_target()
 if hasattr(target, "remove_last_node"): # PageBuilder (V-mode); 
 target.remove_last_node(GlueNode)
 else: # ParagraphList (H-mode) — unchanged
 exec_unskip(target)

 def _exec_unkern_cmd(self) -> None:
 """\\unkern — remove trailing kern from the current list if present."""
 from aspose_tex._engine.box_primitives import exec_unkern
 from aspose_tex._engine.nodes import KernNode
 target = self._current_node_target()
 if hasattr(target, "remove_last_node"): # PageBuilder (V-mode); 
 target.remove_last_node(KernNode)
 else: # ParagraphList (H-mode) — unchanged
 exec_unkern(target)

 def _exec_unpenalty_cmd(self) -> None:
 """\\unpenalty — remove trailing penalty from the current list if present."""
 from aspose_tex._engine.box_primitives import exec_unpenalty
 from aspose_tex._engine.nodes import PenaltyNode
 target = self._current_node_target()
 if hasattr(target, "remove_last_node"): # PageBuilder (V-mode); 
 target.remove_last_node(PenaltyNode)
 else: # ParagraphList (H-mode) — unchanged
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

 if self._mode_stack.current == ModeKind.RESTRICTED_HORIZONTAL:
 raise EngineError("\\insert is not allowed inside an hbox")
 class_ = parse_integer(self._expander)
 self._box_regs._validate(class_) # Reuse the box-class range contract.
 box = exec_vbox(
 self._expander,
 self._font_manager,
 self._group_stack,
 self._box_regs,
 )
 self._contribute(
 InsertNode(
 class_=class_,
 vlist=tuple(box.list),
 height=box.height,
 depth=box.depth,
 floating_penalty=self._get_named_int("floatingpenalty"),
 split_top_skip=self._get_named_skip("splittopskip"),
 split_max_depth=self._get_named_dimen("splitmaxdepth"),
 )
 )

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

 def _current_hsize(self) -> int:
 r"""Return the live ``\hsize`` in sp (named-param DIMEN slot 258).

 Reads the register directly (via :meth:`_get_named_dimen`) so group
 save/restore is honoured — ``{\hsize=3in <par>}`` breaks at 3in while
 the paragraph after the group breaks at the restored width. Falls back
 to the ``_HSIZE`` plain-TeX default if ``\hsize`` is somehow
 unregistered (defensive; unreachable under normal construction).

 See / .

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
 box = self._scan_box_value("\\moveleft" if left else "\\moveright")
 if box is None:
 return
 self._contribute(apply_shift(box, amount if left else -amount, vertical=False))

 def _exec_leavevmode_cmd(self) -> None:
 """\\leavevmode — start an unindented paragraph in vertical mode."""
 if self._mode_stack.current in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
 self._begin_paragraph(indent=False)

 def _exec_hangindent_cmd(self) -> None:
 """\\hangindent<dimen> — store M3 paragraph-shape state."""
 from aspose_tex._engine.dimparser import parse_dimen
 self._eat_optional_equals()
 old = self._hangindent
 self._group_stack.save(("hangindent", None), lambda: setattr(self, "_hangindent", old))
 self._hangindent = parse_dimen(self._expander)
 self._expander.fire_after_assignment()

 def _exec_hangafter_cmd(self) -> None:
 """\\hangafter<int> — store M3 paragraph-shape state."""
 from aspose_tex._engine.dimparser import parse_integer
 self._eat_optional_equals()
 old = self._hangafter
 self._group_stack.save(("hangafter", None), lambda: setattr(self, "_hangafter", old))
 self._hangafter = parse_integer(self._expander)
 self._expander.fire_after_assignment()

 def _exec_parshape_cmd(self) -> None:
 """\\parshape<n><indent><length>... — parse and store M3 state."""
 from aspose_tex._engine.dimparser import parse_dimen, parse_integer
 self._eat_optional_equals()
 count = parse_integer(self._expander)
 if count < 0:
 raise EngineError("\\parshape count < 0")
 old = self._parshape
 self._group_stack.save(("parshape", None), lambda: setattr(self, "_parshape", old))
 if count == 0:
 self._parshape = None
 else:
 self._parshape = [
 (parse_dimen(self._expander), parse_dimen(self._expander))
 for _ in range(count)
 ]
 self._expander.fire_after_assignment()

 def _current_node_target(self):
 """Return the mutable node container for the current TeX mode."""
 if self._mode_stack.current in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
 return self._par_list
 return self._page_builder

 def _remove_last_box(self) -> HlistNode | VlistNode | None:
 """Remove the trailing box from the current list."""
 from aspose_tex._engine.box_primitives import exec_lastbox
 target = self._current_node_target()
 return exec_lastbox(target, self._mode_stack.current)

 def _exec_wd_cmd(self) -> None:
 """\\wd — get/set box width (M1 stub: consumes register index)."""
 from aspose_tex._engine.dimparser import parse_integer
 parse_integer(self._expander)

 def _exec_ht_cmd(self) -> None:
 """\\ht — get/set box height (M1 stub: consumes register index)."""
 from aspose_tex._engine.dimparser import parse_integer
 parse_integer(self._expander)

 def _exec_dp_cmd(self) -> None:
 """\\dp — get/set box depth (M1 stub: consumes register index)."""
 from aspose_tex._engine.dimparser import parse_integer
 parse_integer(self._expander)

 def _exec_raise_cmd(self) -> None:
 """\\raise <dimen> <box> — raise a box."""
 from aspose_tex._engine.dimparser import parse_dimen
 amount = parse_dimen(self._expander)
 from aspose_tex._engine.box_primitives import exec_hbox
 box = exec_hbox(self._expander, self._font_manager,
 self._group_stack, self._box_regs)
 box = HlistNode(
 list=box.list, width=box.width, height=box.height,
 depth=box.depth, shift_amount=-amount,
 glue_sign=box.glue_sign, glue_set=box.glue_set,
 glue_order=box.glue_order,
 )
 self._add_box_to_current_list(box)

 def _exec_lower_cmd(self) -> None:
 """\\lower <dimen> <box> — lower a box."""
 from aspose_tex._engine.dimparser import parse_dimen
 amount = parse_dimen(self._expander)
 from aspose_tex._engine.box_primitives import exec_hbox
 box = exec_hbox(self._expander, self._font_manager,
 self._group_stack, self._box_regs)
 box = HlistNode(
 list=box.list, width=box.width, height=box.height,
 depth=box.depth, shift_amount=amount,
 glue_sign=box.glue_sign, glue_set=box.glue_set,
 glue_order=box.glue_order,
 )
 self._add_box_to_current_list(box)

 def _ensure_horizontal(self) -> None:
 """Enter horizontal mode when a text primitive appears in vertical mode."""
 if self._mode_stack.current in (
 ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL,
 ):
 self._begin_paragraph()

 def _exec_char_cmd(self) -> None:
 """\\char<n> — append a character in the current font."""
 from aspose_tex._engine.box_primitives import exec_char
 self._ensure_horizontal()
 exec_char(self._expander, self._font_manager, self._par_list)

 def _exec_accent_cmd(self) -> None:
 """\\accent<n><char> — append a kerned accent/base hbox."""
 from aspose_tex._engine.box_primitives import exec_accent
 self._ensure_horizontal()
 exec_accent(self._expander, self._font_manager, self._par_list)

 def _exec_discretionary_cmd(self) -> None:
 """\\discretionary{pre}{post}{nobreak} — append a discretionary node."""
 from aspose_tex._engine.box_primitives import exec_discretionary
 self._ensure_horizontal()
 exec_discretionary(
 self._expander,
 self._font_manager,
 self._group_stack,
 self._box_regs,
 self._par_list,
 )

 def _exec_mark_cmd(self) -> None:
 """\\mark{<tokens>} — append a page mark sentinel."""
 node = self._marks.execute_mark(tuple(self._read_balanced_tokens("\\mark")))
 if self._mode_stack.current in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
 self._append_to_hlist(node)
 else:
 self._contribute(node)

 def _exec_leaders_cmd(self, kind: LeadersKind) -> None:
 """\\leaders family — append a leader shell to the current hlist."""
 from aspose_tex._engine.leaders import parse_leaders
 self._ensure_horizontal()
 node = parse_leaders(
 self._expander,
 self._font_manager,
 self._group_stack,
 self._box_regs,
 kind,
 )
 self._append_to_hlist(node)

 def _read_balanced_tokens(self, command: str) -> list[Token]:
 """Read a balanced ``{...}`` token list for token-list primitives."""
 tok = self._next_token()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = self._next_token()
 if not (isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP):
 raise EngineError(f"{command}: expected {{...}}")
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
 """Consume and validate a font control sequence operand."""
 tok = self._next_token()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = self._next_token()
 if not isinstance(tok, ControlSequenceToken):
 raise EngineError(f"{command}: expected font cs, got {tok!r}")
 if not self._font_manager.is_font(tok.name):
 raise EngineError(f"{command}: \\{tok.name} is not a font")
 return tok.name

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
 """Return tokens for ``\\the\\fontdimen<n><font-cs>``."""
 from aspose_tex._engine.dimparser import parse_integer
 from aspose_tex._engine.registers import _sp_to_tokens
 n = parse_integer(expander)
 tok = expander._next_unexpandable()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = expander._next_unexpandable()
 if not isinstance(tok, ControlSequenceToken):
 raise EngineError(f"\\fontdimen: expected font cs, got {tok!r}")
 if not self._font_manager.is_font(tok.name):
 raise EngineError(f"\\fontdimen: \\{tok.name} is not a font")
 return _sp_to_tokens(self._font_manager.fontdimen(tok.name, n))

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
 self._group_stack.consume_global()
 self._expander.fire_after_assignment()

 def _add_box_to_current_list(self, box: HlistNode | VlistNode) -> None:
 """Add a completed box to the appropriate list based on current mode."""
 mode = self._mode_stack.current
 if mode in (ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL):
 self._contribute(box)
 elif mode in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
 self._append_to_hlist(box)

 # ------------------------------------------------------------------
 # Font commands
 # ------------------------------------------------------------------

 def _exec_font(self) -> None:
 """\\font\\cs=<tfm-name> [at <dimen> | scaled <number>]."""
 from aspose_tex._engine.dimparser import (
 _scan_keyword,
 parse_dimen,
 )
 cs_tok = self._next_token()
 if not isinstance(cs_tok, ControlSequenceToken):
 raise EngineError(
 f"\\font must be followed by a control sequence, got {cs_tok!r}"
 )
 cs_name = cs_tok.name

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

 self._font_manager.load_font(cs_name, tfm_name, at_sp=at_sp, scaled=scaled)
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
 tok = self._expander.peek()
 if tok is None:
 break
 if isinstance(tok, CharToken) and tok.catcode in (Catcode.LETTER, Catcode.OTHER):
 self._next_token()
 chars.append(tok.char)
 elif isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 self._next_token() # consume trailing space
 break
 else:
 break
 if not chars:
 raise EngineError("Missing font name after \\font\\cs=")
 return "".join(chars)

 def _exec_nullfont(self) -> None:
 """Select the null font (all metrics zero)."""
 if not self._font_manager.is_font("nullfont"):
 self._font_manager.load_font("nullfont", "cmr10", at_sp=0)
 for i in range(1, 8):
 self._font_manager.set_fontdimen("nullfont", i, 0)
 self._font_manager.select_font("nullfont")

 # ------------------------------------------------------------------
 # Document end
 # ------------------------------------------------------------------

 def _exec_bye(self) -> None:
 """\\bye — end the document (Plain TeX: \\par\\vfill\\supereject\\end)."""
 if self._mode_stack.current == ModeKind.HORIZONTAL:
 self._end_paragraph()
 self._contribute(make_vfill_glue())
 self._contribute(PenaltyNode(penalty=NEG_INF_PENALTY))
 self._done = True

 def _exec_end(self) -> None:
 """\\end — terminate processing."""
 if self._mode_stack.current == ModeKind.HORIZONTAL:
 self._end_paragraph()
 self._done = True

 def _exec_eject_cmd(self) -> None:
 r"""\\eject — force a page break (plain TeX: ``\\par\\break``).

 Per plain.tex line 1104, ``\\def\\eject{\\par\\break}`` where
 ``\\break`` is ``\\penalty-10000``. This is **not**
 ``\\vfil\\penalty-10000``; an author who wants page-fill stretch
 on a forced break must place ``\\vfil`` (or use ``\\filbreak``)
 themselves. See .
 """
 if self._mode_stack.current == ModeKind.HORIZONTAL:
 self._end_paragraph()
 self._contribute(PenaltyNode(penalty=NEG_INF_PENALTY))

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
