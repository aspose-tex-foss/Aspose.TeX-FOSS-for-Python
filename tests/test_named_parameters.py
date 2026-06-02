"""Tests for NamedParameterRegistry + Appendix A catalog.

Two layers:

1. Direct unit tests on ``NamedParameterRegistry`` — register / lookup,
 duplicate-name and slot-collision errors, kind-mismatch on assignment,
 ``\\global`` flag, group save/restore.
2. End-to-end tests through ``TeXInterpreter`` — dispatch of every Appendix A
 entry (parametrised) with assignment + ``\\the`` round-trip.

Covers AC-3 (106 named params dispatchable; assign + read), AC-4
(NamedParameterRegistry test suite — dispatch by name, kind validation,
``\\global`` honored, group save/restore).
"""

from __future__ import annotations

import pytest

from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.group import GroupStack
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.named_parameters import (
 _APPENDIX_A_INT,
 _APPENDIX_A_TOKS,
 NamedParameterRegistry,
 ParamKind,
 _build_appendix_a_dimen,
 _build_appendix_a_muskip,
 _build_appendix_a_skip,
)
from aspose_tex._engine.registers import (
 _NUM_REGISTERS,
 Glue,
 GlueOrder,
 RegisterSet,
)
from aspose_tex._input import (
 CatcodeTable,
 InputReader,
 StringInputSource,
 Tokenizer,
)
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_env() -> tuple[Expander, RegisterSet, GroupStack, NamedParameterRegistry]:
 """Build a minimal pipeline plus a freshly-constructed registry."""
 return _make_env_for("")


def _make_env_for(
 text: str,
) -> tuple[Expander, RegisterSet, GroupStack, NamedParameterRegistry]:
 src = StringInputSource(text)
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 gs = GroupStack()
 regs = RegisterSet(group_stack=gs)
 exp = Expander(reader, tok, catcodes, register_provider=regs, group_stack=gs)
 exp._register_set = regs
 named = NamedParameterRegistry(regs, gs)
 regs._named_params = named
 exp._named_params = named
 return exp, regs, gs, named


def _run_interp(tex: str) -> TeXInterpreter:
 """Run TeX through the full interpreter, return it for state inspection."""
 interp = TeXInterpreter()
 device = DviDevice()
 interp.run_with_device(StringInputSource(tex + r"\bye"), device)
 return interp


# ---------------------------------------------------------------------------
# register / lookup / duplicate detection
# ---------------------------------------------------------------------------

class TestRegisterAndLookup:
 """Basic registry mechanics (FR-10, AC-3, AC-4)."""

 def test_register_and_lookup(self) -> None:
 _, _, _, named = _make_env()
 named.register("hsize", ParamKind.DIMEN, 258, default=30_785_886)
 entry = named.lookup("hsize")
 assert entry is not None
 assert entry.name == "hsize"
 assert entry.kind == ParamKind.DIMEN
 assert entry.slot == 258

 def test_lookup_missing_returns_none(self) -> None:
 _, _, _, named = _make_env()
 assert named.lookup("not_registered") is None

 def test_register_duplicate_name_raises(self) -> None:
 _, _, _, named = _make_env()
 named.register("hsize", ParamKind.DIMEN, 258, default=0)
 with pytest.raises(EngineError, match="already registered"):
 named.register("hsize", ParamKind.DIMEN, 259, default=0)

 def test_register_duplicate_slot_raises(self) -> None:
 _, _, _, named = _make_env()
 named.register("hsize", ParamKind.DIMEN, 258, default=0)
 with pytest.raises(EngineError, match="already used"):
 named.register("vsize_alt", ParamKind.DIMEN, 258, default=0)

 def test_register_same_slot_different_kind_ok(self) -> None:
 """Same slot index in different kinds is fine — separate banks."""
 _, _, _, named = _make_env()
 named.register("hsize", ParamKind.DIMEN, 258, default=0)
 # SKIP slot 258 ('baselineskip' in Appendix A) is independent.
 named.register("baselineskip_test", ParamKind.SKIP, 258, default=Glue(
 0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL,
 ))


# ---------------------------------------------------------------------------
# Post-construction on_set wiring ( / §Component 4c)
# ---------------------------------------------------------------------------

class TestSetOnSet:
 """``set_on_set`` rebinds the on_set hook of an already-registered entry."""

 def test_set_on_set_replaces_existing_callback(self) -> None:
 exp, _, _, named = _make_env_for(r"\pretolerance=42 ")
 calls: list[int] = []
 named.register(
 "pretolerance", ParamKind.INT, 256, default=0,
 on_set=lambda _v: calls.append(-1),
 )
 # Rebind to a different sink; the prior callback must not fire.
 named.set_on_set("pretolerance", lambda v: calls.append(v))
 from aspose_tex._input.token import ControlSequenceToken
 tok = next(iter(exp))
 assert isinstance(tok, ControlSequenceToken)
 named.dispatch_assignment(named.lookup("pretolerance"), exp)
 assert calls == [42]

 def test_set_on_set_clear_with_none(self) -> None:
 exp, _, _, named = _make_env_for(r"\pretolerance=7 ")
 seen: list[int] = []
 named.register(
 "pretolerance", ParamKind.INT, 256, default=0,
 on_set=lambda v: seen.append(v),
 )
 named.set_on_set("pretolerance", None)
 next(iter(exp)) # consume the CS token
 named.dispatch_assignment(named.lookup("pretolerance"), exp)
 assert seen == []
 assert named.lookup("pretolerance").on_set is None

 def test_set_on_set_unknown_name_raises(self) -> None:
 _, _, _, named = _make_env()
 with pytest.raises(EngineError, match="not registered"):
 named.set_on_set("not_a_param", lambda _v: None)

 def test_set_on_set_binds_to_late_constructed_target(self) -> None:
 """ motivation: hook a target that didn't exist at register time."""
 exp, _, _, named = _make_env_for(r"\pretolerance=99 ")
 named.register("pretolerance", ParamKind.INT, 256, default=0)
 assert named.lookup("pretolerance").on_set is None

 class LateTarget:
 flipped = False

 target = LateTarget()
 named.set_on_set(
 "pretolerance",
 lambda _v, t=target: setattr(t, "flipped", True),
 )
 next(iter(exp))
 named.dispatch_assignment(named.lookup("pretolerance"), exp)
 assert target.flipped is True

 def test_interpreter_wires_output_on_set_via_api(self) -> None:
 """End-to-end: \\output={...} flips PageBuilder._output_is_user_redefined."""
 interp = _run_interp(r"\output={\relax}")
 # The contract: user-written \output flips the page-trigger gate.
 assert interp._page_builder._output_is_user_redefined is True

 def test_interpreter_wires_maxdeadcycles_on_set_via_api(self) -> None:
 """End-to-end: \\maxdeadcycles=50 propagates to PageBuilderConfig."""
 interp = _run_interp(r"\maxdeadcycles=50 ")
 assert interp._page_builder._config.max_dead_cycles == 50


# ---------------------------------------------------------------------------
# Per-kind assignment + \the round-trip via the full interpreter
# ---------------------------------------------------------------------------

class TestPerKindDispatch:
 """One assignment + one \\the per kind (AC-3)."""

 def test_int_assign_and_the(self) -> None:
 # \pretolerance=99 followed by \the\pretolerance reads back "99".
 # Drive the parser directly to confirm the registry round-trips.
 exp, _, _, named = _make_env_for(r"\pretolerance=99 ")
 from aspose_tex._input.token import ControlSequenceToken

 tok = next(iter(exp))
 assert isinstance(tok, ControlSequenceToken) and tok.name == "pretolerance"
 named.register("pretolerance", ParamKind.INT, 256, default=0)
 entry = named.lookup("pretolerance")
 named.dispatch_assignment(entry, exp)
 # Read it back via dispatch_the
 toks = named.dispatch_the(entry, exp)
 assert "".join(t.char for t in toks) == "99"

 def test_dimen_assign_and_the_via_interpreter(self) -> None:
 """\\hsize=6.5in \\the\\hsize round-trips through the interpreter."""
 interp = _run_interp(r"\hsize=6.5in")
 # 6.5in = floor(6.5 * 4736286) = 30785859 (parser computes 6*in + 5/10*in)
 # Specifically: 6 * 4736286 + 5 * 4736286 // 10 = 28417716 + 2368143 = 30785859
 entry = interp._named_params.lookup("hsize")
 value = interp._register_set.get_dimen(entry.slot, _internal=True)
 assert value == 30_785_859

 def test_skip_assign_and_the_via_interpreter(self) -> None:
 """\\parskip=2pt plus 1pt round-trips through the interpreter."""
 interp = _run_interp(r"\parskip=2pt plus 1pt")
 entry = interp._named_params.lookup("parskip")
 glue = interp._register_set.get_skip(entry.slot, _internal=True)
 assert glue.width == 2 * 65536
 assert glue.stretch == 1 * 65536
 assert glue.stretch_order == GlueOrder.NORMAL

 def test_muskip_assign_and_the_via_interpreter(self) -> None:
 """\\thinmuskip=3mu round-trips via 'mu' unit (§4d)."""
 interp = _run_interp(r"\thinmuskip=3mu")
 entry = interp._named_params.lookup("thinmuskip")
 glue = interp._register_set.get_muskip(entry.slot, _internal=True)
 # 1mu == 65536sp per §4d — value-equivalent to 3pt.
 assert glue.width == 3 * 65536

 def test_toks_assign_and_the_via_interpreter(self) -> None:
 """\\output={\\relax} parses; the token list is stored verbatim."""
 interp = _run_interp(r"\output={\relax}")
 entry = interp._named_params.lookup("output")
 toks = interp._register_set.get_toks(entry.slot, _internal=True)
 # Toks payload contains the inner ControlSequenceToken('relax')
 from aspose_tex._input.token import ControlSequenceToken
 assert any(
 isinstance(t, ControlSequenceToken) and t.name == "relax" for t in toks
 )


class TestKindValidation:
 """Wrong-type assignment surfaces as EngineError from the value parser (AC-4)."""

 def test_dimen_no_unit_raises(self) -> None:
 """``\\hsize=42`` (no unit) — parse_dimen requires a unit token."""
 with pytest.raises(EngineError, match=r"[Dd]imension unit"):
 _run_interp(r"\hsize=42")

 def test_int_with_letters_only_raises(self) -> None:
 """``\\pretolerance=foo`` — parse_integer cannot find a digit."""
 with pytest.raises(EngineError, match=r"[Nn]umber expected"):
 _run_interp(r"\pretolerance=foo")


# ---------------------------------------------------------------------------
# \global flag + group save/restore (AC-4)
# ---------------------------------------------------------------------------

class TestGlobalAndGroupScope:
 """\\global flag honored; group save/restore inherited from RegisterSet."""

 def test_group_save_restore_dimen(self) -> None:
 """\\hsize=5in {\\hsize=4in} — outer value restored on group close."""
 interp = _run_interp(r"\hsize=5in {\hsize=4in }")
 entry = interp._named_params.lookup("hsize")
 value = interp._register_set.get_dimen(entry.slot, _internal=True)
 assert value == 5 * 4_736_286

 def test_global_flag_dimen(self) -> None:
 """\\global\\hsize=4in inside a group survives close."""
 interp = _run_interp(r"\hsize=5in {\global\hsize=4in }")
 entry = interp._named_params.lookup("hsize")
 value = interp._register_set.get_dimen(entry.slot, _internal=True)
 assert value == 4 * 4_736_286

 def test_group_save_restore_int(self) -> None:
 """\\pretolerance — INT-kind group save/restore."""
 interp = _run_interp(r"\pretolerance=42 {\pretolerance=7 }")
 entry = interp._named_params.lookup("pretolerance")
 assert interp._register_set.get_count(entry.slot, _internal=True) == 42

 def test_group_save_restore_skip(self) -> None:
 """\\parskip — SKIP-kind group save/restore."""
 interp = _run_interp(r"\parskip=2pt {\parskip=5pt }")
 entry = interp._named_params.lookup("parskip")
 glue = interp._register_set.get_skip(entry.slot, _internal=True)
 assert glue.width == 2 * 65536


# ---------------------------------------------------------------------------
# Appendix A full coverage — parametrised round-trip per entry (AC-3)
# ---------------------------------------------------------------------------

def _appendix_a_entries() -> (
 list[tuple[str, ParamKind, int, object]]
):
 """Return every Appendix A entry as (name, kind, slot, default).

 added ``vsize`` / ``maxdepth`` (DIMEN slots 256-257) and
 ``topskip`` (SKIP slot 256), bringing the catalog to its full 109
 entries (the legacy ``_exec_*`` handlers having been retired).
 """
 out: list[tuple[str, ParamKind, int, object]] = []
 for name, slot, default in _APPENDIX_A_INT:
 out.append((name, ParamKind.INT, slot, default))
 for name, slot, default in _build_appendix_a_dimen():
 out.append((name, ParamKind.DIMEN, slot, default))
 for name, slot, default in _build_appendix_a_skip():
 out.append((name, ParamKind.SKIP, slot, default))
 for name, slot, default in _build_appendix_a_muskip():
 out.append((name, ParamKind.MUSKIP, slot, default))
 for name, slot, default in _APPENDIX_A_TOKS:
 out.append((name, ParamKind.TOKS, slot, default))
 return out


_APPENDIX_A_ALL = _appendix_a_entries()


def test_appendix_a_count_is_98() -> None:
 """Appendix A catalog covers 98 named scalar parameters after .

 The baseline was 109 (53 INT, 29 DIMEN, 15 SKIP, 3 MUSKIP, 9 TOKS).
 retired 11 placeholders shadowed by InternalQuantityRegistry:
 INT 307 \\deadcycles + 308 \\insertpenalties (51 INT remain) and DIMEN
 276..284 \\pagetotal..\\prevdepth (20 DIMEN remain).
 """
 assert len(_APPENDIX_A_ALL) == 98
 names = {entry[0] for entry in _APPENDIX_A_ALL}
 # vsize / maxdepth / topskip migrated into the registry by .
 assert "vsize" in names
 assert "maxdepth" in names
 assert "topskip" in names
 # : shadowed entries are no longer in the catalog.
 for retired in (
 "deadcycles",
 "insertpenalties",
 "pagetotal",
 "pagegoal",
 "pagestretch",
 "pagefilstretch",
 "pagefillstretch",
 "pagefilllstretch",
 "pageshrink",
 "pagedepth",
 "prevdepth",
 ):
 assert retired not in names


@pytest.mark.parametrize(
 "name,kind,slot,default", _APPENDIX_A_ALL, ids=lambda x: str(x)
)
def test_appendix_a_default_seeded(name, kind, slot, default) -> None:
 """Every registered entry has its IniTeX default after interpreter init."""
 interp = _run_interp("") # empty body — just \bye
 entry = interp._named_params.lookup(name)
 assert entry is not None, f"{name} not registered"
 assert entry.kind == kind
 assert entry.slot == slot
 rs = interp._register_set
 if kind == ParamKind.INT:
 assert rs.get_count(slot, _internal=True) == default
 elif kind == ParamKind.DIMEN:
 assert rs.get_dimen(slot, _internal=True) == default
 elif kind == ParamKind.SKIP:
 assert rs.get_skip(slot, _internal=True) == default
 elif kind == ParamKind.MUSKIP:
 assert rs.get_muskip(slot, _internal=True) == default
 elif kind == ParamKind.TOKS:
 assert rs.get_toks(slot, _internal=True) == list(default)


@pytest.mark.parametrize(
 "name,kind",
 [
 # One sample per kind, exercising assignment + \the round-trip.
 ("tolerance", ParamKind.INT),
 ("hsize", ParamKind.DIMEN),
 ("parskip", ParamKind.SKIP),
 ("thinmuskip", ParamKind.MUSKIP),
 ("everypar", ParamKind.TOKS),
 ],
)
def test_appendix_a_assign_and_read(name, kind) -> None:
 """Per-kind end-to-end assignment + register-state read."""
 if kind == ParamKind.INT:
 interp = _run_interp(rf"\{name}=42")
 entry = interp._named_params.lookup(name)
 assert interp._register_set.get_count(entry.slot, _internal=True) == 42
 elif kind == ParamKind.DIMEN:
 interp = _run_interp(rf"\{name}=7pt")
 entry = interp._named_params.lookup(name)
 assert (
 interp._register_set.get_dimen(entry.slot, _internal=True) == 7 * 65536
 )
 elif kind == ParamKind.SKIP:
 interp = _run_interp(rf"\{name}=3pt plus 2pt")
 entry = interp._named_params.lookup(name)
 glue = interp._register_set.get_skip(entry.slot, _internal=True)
 assert glue.width == 3 * 65536 and glue.stretch == 2 * 65536
 elif kind == ParamKind.MUSKIP:
 interp = _run_interp(rf"\{name}=4mu")
 entry = interp._named_params.lookup(name)
 assert (
 interp._register_set.get_muskip(entry.slot, _internal=True).width
 == 4 * 65536
 )
 elif kind == ParamKind.TOKS:
 interp = _run_interp(rf"\{name}={{\relax}}")
 entry = interp._named_params.lookup(name)
 toks = interp._register_set.get_toks(entry.slot, _internal=True)
 from aspose_tex._input.token import ControlSequenceToken
 assert any(
 isinstance(t, ControlSequenceToken) and t.name == "relax"
 for t in toks
 )


# ---------------------------------------------------------------------------
# RegisterBank size (AC-5: 320-bump)
# ---------------------------------------------------------------------------

def test_register_bank_size_is_320() -> None:
 """§3a — pool extends from 256 to 320 entries per family."""
 assert _NUM_REGISTERS == 320


def test_user_facing_index_check_unchanged() -> None:
 """``set_count(256)`` without ``_internal=True`` still rejects (TeX contract)."""
 regs = RegisterSet()
 with pytest.raises(EngineError, match="out of range 0-255"):
 regs.set_count(256, 0)


def test_internal_slot_check_accepts_319() -> None:
 """``_check_internal_slot`` accepts the full 0-319 range."""
 regs = RegisterSet()
 regs.set_count(319, 42, _internal=True)
 assert regs.get_count(319, _internal=True) == 42


def test_internal_slot_check_rejects_320() -> None:
 regs = RegisterSet()
 with pytest.raises(EngineError, match="out of range 0-319"):
 regs.set_count(320, 0, _internal=True)


# ---------------------------------------------------------------------------
# Macro-override regression — user \def wins over named-param dispatch (Risk #2)
# ---------------------------------------------------------------------------

class TestNamedParamOverriddenByUserMacro:
 """When a user redefines a named-param CS as a macro, the macro wins."""

 def test_user_def_hsize_wins(self) -> None:
 """``\\def\\hsize{junk}`` shadows the registry: subsequent ``\\hsize=5in``
 is processed as ``junk=5in`` — Expander expands the macro first."""
 # ``junk`` is undefined; we just confirm the name-param path is NOT
 # taken (i.e. the dimen slot is not written).
 with pytest.raises(EngineError, match=r"[Uu]ndefined control sequence"):
 _run_interp(r"\def\hsize{\junk}\hsize=5in")
