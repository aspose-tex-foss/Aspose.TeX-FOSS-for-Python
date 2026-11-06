"""Math-list (noad) data model and builder ( / §A, §B).

This module owns the math-atom **structure** for milestone M4.  It replaces the
load-without-execute math shell's no-op operand consumers
with a real :class:`MathListBuilder` that constructs a list of **noads** (math
atoms) while the interpreter is in math mode.

The noad field set (§A) is deliberately **complete** for (scripts /
fractions / accents / radicals) and (delimiters / large operators):
those specs add only *layout* (the :mod:`mlist_to_hlist` translation), never
*parsing*.  This cascade emits no output nodes by itself — the
finished mlist is translated to an hlist by :mod:`mlist_to_hlist`.

References: TeX:The Program §681-§687 (noad records), §1150 (``scan_math``),
§1151-§1160 (math-char / class-routing primitives → noads), §1155 (class-7
variable family via ``\\fam``), §1176 (double script).  §A/§B.
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Callable
from typing import TYPE_CHECKING, Union

from aspose_tex._engine.dimparser import parse_dimen, parse_glue, parse_integer
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
    from aspose_tex._engine.code_arrays import CodeArrays
    from aspose_tex._engine.expansion import Expander
    from aspose_tex._engine.nodes import AdjustNode, HlistNode, LeadersNode, RuleNode, VlistNode
    from aspose_tex._engine.registers import Glue, RegisterSet
    from aspose_tex._fonts.math_family_registry import MathFamilyRegistry


# ---------------------------------------------------------------------------
# §A — Atom classes and noad kinds (TeX:The Program §681)
# ---------------------------------------------------------------------------


class MathClass(enum.IntEnum):
    """Math atom class (TeX:The Program §681; §A).

    Classes 0-7 are the spacing-table classes.  Class 7 in a ``\\mathcode`` is
    the *variable-family* marker (use ``\\fam``); the decoder resolves it to an
    :attr:`ORD` atom before a noad is built, so :attr:`INNER` (also numbered 7
    in TeX's noad enum) is never confused with the mathcode class-7 marker.
    Classes 8-12 are translation-time atom kinds the spacing table also reads.
    """

    ORD = 0  # ordinary        \mathord
    OP = 1  # large operator   \mathop
    BIN = 2  # binary op       \mathbin
    REL = 3  # relation        \mathrel
    OPEN = 4  # opening         \mathopen
    CLOSE = 5  # closing         \mathclose
    PUNCT = 6  # punctuation     \mathpunct
    INNER = 7  # inner           \mathinner / fractions / \left..\right
    RADICAL = 8  # \radical       (layout =; structure here)
    VCENTER = 9  # \vcenter
    ACCENT = 10  # \mathaccent     (layout =; structure here)
    OVER = 11  # \overline
    UNDER = 12  # \underline


class NoadKind(enum.IntEnum):
    """Discriminator for a :class:`Noad` (§A)."""

    ATOM = 0  # Ord/Op/Bin/Rel/Open/Close/Punct/Inner/Radical/Vcenter/Accent/Over/Under
    STYLE = 1  # \displaystyle / \textstyle / \scriptstyle / \scriptscriptstyle
    GLUE = 2  # \mskip / inter-atom glue carrier
    KERN = 3  # \mkern
    CHOICE = 4  # \mathchoice (four sub-mlists)
    FRACTION = 5  # \over / \atop / \above family (layout)
    BOUNDARY = 6  # \left / \right (layout)
    ADJUST = 7  # raw adjustment, no atom class
    RULE = 8  # raw rule, no atom class
    PENALTY = 9  # explicit penalty, no atom class


class LimitMode(enum.IntEnum):
    """Large-operator limit placement (TeX:The Program §750, App G rule 13).

    Set on an OP atom by ``\\limits`` / ``\\nolimits`` / ``\\displaylimits``
    (TeX §1158 ``limit_switch``).  :attr:`DISPLAY_LIMITS` is the ``\\mathop``
    default — limits stack above/below in display style and ride to the right
    otherwise; ``make_op`` reads this field.
    """

    DISPLAY_LIMITS = 0  # default for \mathop: limits in display, right otherwise
    LIMITS = 1  # \limits — always above/below
    NO_LIMITS = 2  # \nolimits — always to the right


# ``\over`` default fraction-bar thickness sentinel (resolved to
# ``default_rule_thickness`` at layout time —).  ``None`` thickness on
# a FRACTION noad means ``\atop`` (no bar); this sentinel means ``\over``.
DEFAULT_FRACTION_THICKNESS = -1


# ---------------------------------------------------------------------------
# §A — Math fields (TeX:The Program §682, §687)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class MathChar:
    """A symbol math field: family + position → glyph at translate time."""

    fam: int  # 0..15
    position: int  # 0..255 (char code in the family font)


@dataclasses.dataclass(frozen=True, slots=True)
class DelimiterCode:
    """A 27-bit ``\\delimiter`` operand ( reads; structure here).

    Carries the small (text-size) and large (extension) variant fam/position
    pairs decoded from the delcode / ``\\delimiter`` integer.
    """

    small_fam: int
    small_pos: int
    large_fam: int
    large_pos: int


@dataclasses.dataclass(slots=True)
class MathList:
    """A sub-formula math field: a nested noad list (→ boxed Ord at layout).

    ``style_override`` records a ``\\displaystyle`` / ``\\scriptstyle`` etc.
    set inside the group (consumed by the style propagation).
    """

    noads: list[Noad]
    style_override: str | None = None


# A math field is empty, a single symbol, a nested mlist, or an already-built
# box (the layout fills boxes in; parses the structure).
MathField = Union[None, MathChar, MathList, "HlistNode", "VlistNode"]

# Where a scanned math field goes (a noad's nucleus or script slot); called
# with the field once it is known (TeX §1151 saved(0)).
_FieldStore = Callable[[MathField], None]


# ---------------------------------------------------------------------------
# §A — The noad record (TeX:The Program §682, §686, §687)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(slots=True)
class Noad:
    """A single math-list atom (§A — field-complete for).

    owns the *structure*: every field a downstream layout spec reads
    is parsed and populated here.  add only the layout functions
    that consume :attr:`subscr` / :attr:`supscr` / :attr:`numerator` /
    :attr:`denominator` / :attr:`left_delim` / :attr:`right_delim` /
    :attr:`accent_fam` / :attr:`choices`.
    """

    kind: NoadKind
    math_class: MathClass = MathClass.ORD  # ATOM only
    nucleus: MathField = None
    subscr: MathField = None  # parsed here; laid out by
    supscr: MathField = None  # parsed here; laid out by
    # --- accent / radical / over-under (structure here, layout) ---
    accent_fam: int | None = None  # \mathaccent char family (ACCENT)
    accent_pos: int | None = None
    left_delim: DelimiterCode | None = None  # \radical / \left / fraction
    right_delim: DelimiterCode | None = None  # \right / fraction
    # --- fraction (structure here; bar/centering =) ---
    numerator: MathList | None = None
    denominator: MathList | None = None
    thickness: int | None = None  # \above <dimen>; DEFAULT_FRACTION_THICKNESS = \over; None = \atop
    adjustment: AdjustNode | None = None
    rule: RuleNode | None = None
    penalty: int = 0
    leaders: LeadersNode | None = None
    # --- style / glue / kern carriers ---
    style: str | None = None  # STYLE noad: "display"/"text"/"script"/"scriptscript"
    glue_value: int = 0  # GLUE noad: scalar payload, now only \nonscript's 0
    width: int = 0  # KERN noad: parsed mu value
    mu_glue: bool = False  # GLUE/KERN carries mu units
    # Ordinary GLUE may instead own a `leaders` shell; its glue
    # stays authoritative on that shell. Otherwise its payloads are `glue`
    # for a glue whose stretch/shrink must survive, and the scalar `glue_value`
    # for the \nonscript marker.  `glue` is in sp (\hfil and friends) unless
    # `mu_glue` is set, in which case it is an \mskip muglue converted per
    # style (§716).
    glue: Glue | None = None  # GLUE noad: sp glue, or mu glue when mu_glue
    nonscript: bool = False  # \nonscript marker on the following GLUE
    choices: tuple[MathList, MathList, MathList, MathList] | None = None  # CHOICE noad
    # --- large-operator limit placement (; OP atoms only) ---
    limits: LimitMode = LimitMode.DISPLAY_LIMITS  # \limits / \nolimits / \displaylimits


# ---------------------------------------------------------------------------
# §B — The math-list builder
# ---------------------------------------------------------------------------

_STYLE_NAMES = {
    "displaystyle": "display",
    "textstyle": "text",
    "scriptstyle": "script",
    "scriptscriptstyle": "scriptscript",
}

# \fam is named-parameter slot 296 (named_parameters.py).  Read via
# RegisterSet.get_count(296, _internal=True).
_FAM_SLOT = 296

# Class-routing primitives → forced MathClass (TeX:The Program §1156-§1160).
# Limit-switch primitives → LimitMode (TeX §1158; §E.1).
_LIMIT_MODES: dict[str, LimitMode] = {
    "limits": LimitMode.LIMITS,
    "nolimits": LimitMode.NO_LIMITS,
    "displaylimits": LimitMode.DISPLAY_LIMITS,
}

_CLASS_PRIMITIVES: dict[str, MathClass] = {
    "mathord": MathClass.ORD,
    "mathop": MathClass.OP,
    "mathbin": MathClass.BIN,
    "mathrel": MathClass.REL,
    "mathopen": MathClass.OPEN,
    "mathclose": MathClass.CLOSE,
    "mathpunct": MathClass.PUNCT,
    "mathinner": MathClass.INNER,
}


class MathListBuilder:
    """Builds a noad mlist while the interpreter is in math mode (§B).

    The interpreter's math-mode main loop drives this builder: characters route
    through :meth:`add_char`, ``\\mathchar`` / ``\\mathchardef`` through
    :meth:`add_mathchar`, the class-routing and structure primitives through the
    named ``add_*`` methods, and ``_`` / ``^`` through :meth:`add_subscript` /
    :meth:`add_superscript`.  The finished list is handed off via
    :meth:`take_mlist` at ``$``-close ( cascade #2 translates it).

    A nested ``{<mlist>}`` math field is built by the main loop as a sub-group
    of this builder (:meth:`scan_math_field`, :meth:`begin_group` /
    :meth:`end_group`); the group stack is internal (the interpreter sees one
    builder per formula).

    Args:
        expander:         Active token stream.
        code_arrays:      ``\\mathcode`` / ``\\delcode`` code arrays.
        family_registry:  Math-family font registry (resolved at layout time).
        register_set:     Register set, for reading ``\\fam`` (slot 296).

    Example:
        builder.add_char(ord("x"))
        mlist = builder.take_mlist()
    """

    __slots__ = (
        "_boundary_stack",
        "_choice_stack",
        "_code_arrays",
        "_expander",
        "_family_registry",
        "_fraction",
        "_group_stack",
        "_mlist",
        "_pending_class",
        "_pending_field",
        "_register_set",
    )

    def __init__(
        self,
        expander: Expander,
        code_arrays: CodeArrays,
        family_registry: MathFamilyRegistry,
        register_set: RegisterSet,
    ) -> None:
        self._expander = expander
        self._code_arrays = code_arrays
        self._family_registry = family_registry
        self._register_set = register_set
        self._mlist: list[Noad] = []
        # Pending FRACTION noad (TeX §1181): once a \over/\atop/\above fires, the
        # mlist-so-far becomes its numerator and the rest becomes its denominator;
        # the fraction noad replaces the whole list at hand-off.
        self._fraction: Noad | None = None
        # Saved (mlist, fraction, field store) frames for in-formula `{ … }`
        # sub-groups (TeX §1150 — a brace group in math mode is a self-contained
        # sub-mlist boxed as one Ord atom, so \over / scripts inside it stay
        # scoped).  The store is set when the group is a math *field* (a script,
        # radicand, accentee, …): the finished sub-mlist goes there instead.
        self._group_stack: list[
            tuple[list[Noad], Noad | None, _FieldStore | None, MathClass | None]
        ] = []
        # Saved left-delimiter codes for open `\left … \right` sub-groups (TeX
        # §1191): `\left` opens a math-left group whose inner mlist accumulates
        # (so `\over` / scripts inside scope to it), and `\right` closes it into
        # one INNER noad carrying both delimiters.  Parallel to `_group_stack`.
        self._boundary_stack: list[DelimiterCode | None] = []
        # §A: a class primitive (\mathopen/…) whose field is a `{…}`
        # group sets a *pending forced class* instead of scanning the field
        # eagerly; the main loop's begin_group/end_group build the group with
        # the full dispatch machinery.  begin_group moves this class onto the
        # group's frame and that group's end_group applies it to the resulting
        # atom (instead of the default ORD).  None when no class primitive is
        # awaiting its group.
        self._pending_class: MathClass | None = None
        # TeX §1151/§1186: a math field read as `{…}` (a script, a radicand, the
        # argument of \mathaccent/\overline/\underline) is not scanned eagerly.
        # The `{` goes back to the main loop, which builds the group with full
        # dispatch — so \, / \mkern / \hskip / \over / boxes inside it execute
        # — and begin_group moves this store onto the group's frame, where
        # end_group delivers the finished sub-mlist.  None when no field is
        # awaiting its group.
        self._pending_field: _FieldStore | None = None
        #: a \mathchoice arms a four-group capture instead of scanning
        # its branches eagerly.  Each entry is (group depth at arming, branch
        # mlists collected so far, 0-3); the main loop's begin_group/end_group
        # build each {…} branch with full dispatch (so \setbox/\finph@nt run),
        # and end_group diverts a finished group here only when it closes back
        # to the armed depth — a group nested inside a branch is not a branch
        #.  On the fourth branch the CHOICE noad is appended and the
        # entry popped; a \mathchoice inside a branch pushes its own entry.
        self._choice_stack: list[tuple[int, list[MathList]]] = []

    # ------------------------------------------------------------------
    # Hand-off
    # ------------------------------------------------------------------

    def take_mlist(self) -> list[Noad]:
        """Return the finished mlist and reset the builder.

        A pending ``\\over``/``\\atop``/``\\above`` fraction (TeX §1181) wraps the
        whole formula: the numerator is the part before the fraction op, the
        denominator the part after.  The finished list is then the single
        FRACTION noad.

        Raises:
            EngineError: if a ``\\mathchoice`` armed a four-group capture
                that never saw its four ``{…}`` branches — a runaway
                ``\\mathchoice`` (TeX:The Program §1174).
        """
        if self._choice_stack:
            raise EngineError("\\mathchoice needs four {…} groups")
        mlist = self._resolved_mlist()
        self._mlist = []
        self._fraction = None
        return mlist

    def _resolved_mlist(self) -> list[Noad]:
        if self._fraction is not None:
            self._fraction.denominator = MathList(self._mlist)
            return [self._fraction]
        return self._mlist

    @property
    def mlist(self) -> list[Noad]:
        """The resolved mlist (read-only view for tests; wraps a pending fraction)."""
        return self._resolved_mlist()

    @property
    def tail(self) -> Noad | None:
        """Return the physical current-list tail without resolving fractions.

        Example:
            ``builder.tail`` is ``None`` in an empty active math subgroup.
        """
        return self._mlist[-1] if self._mlist else None

    def remove_tail(self, kind: NoadKind) -> None:
        """Remove the physical tail only when it has the requested kind.

        Example:
            ``builder.remove_tail(NoadKind.GLUE)`` implements math unskip.
        """
        if self.tail is not None and self.tail.kind == kind:
            self._mlist.pop()

    # ------------------------------------------------------------------
    # §B — in-formula brace sub-groups (TeX §1150)
    # ------------------------------------------------------------------

    def begin_group(self) -> None:
        """Open a ``{`` math sub-group: start a fresh sub-mlist (TeX §1150).

        The sub-mlist accumulates until the matching :meth:`end_group`, which
        boxes it as one Ord atom.  This keeps ``\\over`` / scripts inside the
        braces scoped to the group (e.g. ``{a+b\\over c}`` is a single fraction
        atom, not a fraction over the whole formula).  If
        :meth:`scan_math_field` just handed this ``{`` back for a math field (a
        script, radicand, accentee), the field's store moves onto the group's
        frame and the finished sub-mlist fills that field instead (TeX §1151).

        Example::

            # Stream "x^{a\\,b}": after add_superscript() pushes the `{` back,
            builder.begin_group()   # the group remembers the supscr store
        """
        store = self._pending_field
        self._pending_field = None
        #: a class primitive's forced class belongs to THIS group, not
        # to the first group that closes — a {…} nested in the argument closes
        # first.
        forced = self._pending_class
        self._pending_class = None
        self._group_stack.append((self._mlist, self._fraction, store, forced))
        self._mlist = []
        self._fraction = None

    def end_group(self) -> bool:
        """Close a ``}`` math sub-group and deliver its sub-mlist.

        A field group (see :meth:`begin_group`) passes the sub-mlist to its
        field's store (TeX §1186); a ``\\mathchoice`` branch is collected
        ; any other group is appended as one Ord atom, of the pending
        forced class if a class primitive is awaiting it.

        Returns:
            ``True`` if a group was open (so the interpreter knows the brace
            was consumed by the math builder), ``False`` if the brace is
            unmatched at the math-builder level (a plain group-close handled
            elsewhere).

        Example::

            builder.begin_group()
            builder.add_char(ord("a"))
            builder.end_group()     # -> True; mlist ends with Ord{a}
        """
        if not self._group_stack:
            return False
        inner = self._resolved_mlist()
        self._mlist, self._fraction, store, forced = self._group_stack.pop()
        # A field group (TeX §1186 math_group) fills the field it was read for.
        # Checked first: a script group inside a \mathchoice branch or a
        # class-primitive argument is neither the branch nor the argument.
        if store is not None:
            store(_group_nucleus(inner))
            return True
        #: a \mathchoice branch closes here — collect it instead of
        # appending an atom.  Only a group closing back to the depth the
        # \mathchoice armed at is a branch; a {…} or class-primitive argument
        # inside a branch closes deeper and falls through.  On the
        # fourth branch, append the CHOICE noad and disarm.  Runs before the
        # forced-class block: a \mathchoice is not a class-primitive
        # argument, so the two never both fire on one end_group.
        if self._choice_stack and self._choice_stack[-1][0] == len(self._group_stack):
            branches = self._choice_stack[-1][1]
            branches.append(MathList(inner))
            if len(branches) == 4:
                self._choice_stack.pop()
                self._mlist.append(
                    Noad(NoadKind.CHOICE, choices=tuple(branches))  # type: ignore[arg-type]
                )
            return True
        # §1186: an Ord whose nucleus group holds just an accent noad becomes
        # that noad, so `{\hat x}^2` takes the §742 script path of `\hat x^2`.
        if (
            forced in (None, MathClass.ORD)
            and len(inner) == 1
            and inner[0].kind == NoadKind.ATOM
            and inner[0].math_class == MathClass.ACCENT
        ):
            self._mlist.append(inner[0])
            return True
        # §A.2: a class primitive (\mathopen/…) that deferred its `{…}`
        # field to the main loop forced its class onto this group's frame;
        # apply it here (else the bare-group default ORD).
        self._mlist.append(
            Noad(
                NoadKind.ATOM,
                forced if forced is not None else MathClass.ORD,
                nucleus=_group_nucleus(inner),
            )
        )
        return True

    @property
    def in_group(self) -> bool:
        """Whether the builder currently has an open ``{`` math sub-group."""
        return bool(self._group_stack)

    # ------------------------------------------------------------------
    # §B.1 / §B.2 — symbols
    # ------------------------------------------------------------------

    def add_char(self, char_code: int) -> None:
        """Route a catcode-11/12 character through its ``\\mathcode`` (FR-1).

        Decodes the 15-bit mathcode (class = bits 12-14, family = bits 8-11,
        position = bits 0-7).  A class-7 (variable-family) code becomes an Ord
        atom whose family is ``\\fam`` when ``0 ≤ \\fam ≤ 15``, else the code's
        family (TeX:The Program §1155).  The math-active (``0x8000``) case is
        handled by the interpreter before this is called.
        """
        code = self._code_arrays.get_mathcode(char_code)
        self._add_symbol_from_code(code, char_code)

    def add_mathchar(self, value: int) -> None:
        """Build a symbol noad from a ``\\mathchar`` / ``\\mathchardef`` value (FR-2).

        Same 15-bit decode as :meth:`add_char`; a class-7 value becomes an Ord
        atom with the ``\\fam`` family.
        """
        self._add_symbol_from_code(value, value & 0xFF)

    def add_delimiter(self) -> None:
        r"""``\delimiter <27-bit>`` used as a symbol — its small variant (§1160).

        Outside ``\left``/``\right`` a delimiter code is a math char whose
        15-bit mathcode is the code's upper bits (``cur_val div 4096``): plain's
        ``\lbrace`` (``\delimiter"4266308``) is an Open atom of the cmsy
        ``"66`` brace.

        Example::

            # Stream '"4266308':
            builder.add_delimiter()   # Noad(ATOM, OPEN, nucleus=MathChar(2, 0x66))
        """
        value = parse_integer(self._expander, allow_negative=False)
        self.add_mathchar(value // 4096)

    def _add_symbol_from_code(self, code: int, fallback_pos: int) -> None:
        cls = (code >> 12) & 0x7
        fam = (code >> 8) & 0xF
        pos = code & 0xFF
        if cls == 7:  # variable family (TeX §1155): atom is Ord, family from \fam
            cur_fam = self._current_fam()
            if 0 <= cur_fam <= 15:
                fam = cur_fam
            self._mlist.append(
                Noad(NoadKind.ATOM, MathClass.ORD, nucleus=MathChar(fam, pos))
            )
            return
        self._mlist.append(
            Noad(NoadKind.ATOM, MathClass(cls), nucleus=MathChar(fam, pos))
        )

    def _current_fam(self) -> int:
        """Read ``\\fam`` (named-parameter slot 296)."""
        return self._register_set.get_count(_FAM_SLOT, _internal=True)

    # ------------------------------------------------------------------
    # §B.3 — class-routing primitives
    # ------------------------------------------------------------------

    def add_class_primitive(self, name: str) -> None:
        """``\\mathord`` … ``\\mathinner`` — wrap a field in a forced class (FR-3).

        §A.1: the field shape decides the path.  A ``{…}`` group field
        (e.g. the plain.tex ``\\big``-family ``\\mathopen{\\hbox{$…$}}``) is
        **deferred to the main loop** — it sets :attr:`_pending_class` and pushes
        the ``{`` back so the interpreter's ``begin_group``/``end_group`` build
        the group with the full dispatch machinery (boxes, nested ``$…$``, macros
        all execute), and :meth:`end_group` applies the forced class.  A single
        symbol / ``\\mathchar`` field keeps the eager :meth:`scan_math_field`
        path (no behaviour change for the common ``\\mathord\\alpha`` case).

        The peek **expands** macros (``\\bigl`` → ``\\mathopen\\big`` → the
        ``{\\hbox{…}}`` group), so the deferred ``{`` is the post-expansion
        begin-group token, pushed back verbatim onto the expander.
        """
        math_class = _CLASS_PRIMITIVES[name]
        tok = self._next_non_space()
        if tok is None:
            raise EngineError("math field expected")
        if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
            # Deferred forced-class group: hand the `{` back to the main loop.
            self._pending_class = math_class
            self._expander.push_tokens([tok])
            return
        # Single-symbol field: resolve the already-read token directly (avoids a
        # redundant push/re-read), preserving the scan_math_field symbol path.
        nucleus = self._field_from_token(tok)
        self._mlist.append(Noad(NoadKind.ATOM, math_class, nucleus=nucleus))

    def add_box(self, box: HlistNode | VlistNode) -> None:
        """Append a built box (``\\hbox``/``\\vbox``) as one Ord-atom nucleus.

        A box constructed in math mode (e.g. the ``\\hbox`` inside the plain.tex
        ``\\big``-family expansion) is a self-contained sub-formula: it becomes an
        Ord atom whose nucleus is the box (:data:`MathField` already admits
        ``HlistNode`` / ``VlistNode``).  No further math layout is applied — the
        box is final (TeX:The Program §1073: a box in an mlist is an Ord noad).

        Args:
            box: The finished horizontal or vertical box to wrap as an atom.
        """
        self._mlist.append(Noad(NoadKind.ATOM, MathClass.ORD, nucleus=box))

    def add_limits(self, name: str) -> None:
        """``\\limits`` / ``\\nolimits`` / ``\\displaylimits`` — set the last OP atom's mode.

        TeX:The Program §1158 (``limit_switch``): a limit switch applies to the
        immediately preceding large operator.  Raise ``EngineError`` if the tail
        atom is not an OP atom (TeX's "Limit controls must follow a math
        operator" error).  Plain.tex's ``\\int … \\nolimits`` and the
        ``\\mathop``-class word operators rely on this.

        Args:
            name: One of ``"limits"`` / ``"nolimits"`` / ``"displaylimits"``.
        """
        if (
            not self._mlist
            or self._mlist[-1].kind != NoadKind.ATOM
            or self._mlist[-1].math_class != MathClass.OP
        ):
            raise EngineError("\\limits/\\nolimits not on a large operator")
        self._mlist[-1].limits = _LIMIT_MODES[name]

    # ------------------------------------------------------------------
    # §B.4 — scan_math (TeX:The Program §1150)
    # ------------------------------------------------------------------

    def scan_math_field(self, store: _FieldStore) -> None:
        """Read one TeX math field into *store*: a symbol or a ``{<mlist>}`` (FR-4).

        A single char/mathchar, or a ``\\mathchar`` / ``\\mathchardef``
        constant, is passed to *store* at once as a :class:`MathChar`.  A ``{``
        is handed back to the main loop instead (TeX §1151 ``push_math``): the
        group is built with full dispatch, so spacing primitives, ``\\over``,
        boxes and macros inside it execute, and :meth:`end_group` passes the
        finished :class:`MathList` to *store* (§1186).  An absent field raises
        ``EngineError('math field expected')``.

        Args:
            store: Receives the field; called now for a symbol, at the
                matching ``}`` for a group.

        Example::

            # Stream "{a\\,b}": the main loop builds the group, then the
            # closing brace calls the store with MathList([a, glue, b]).
            builder.scan_math_field(lambda f: setattr(noad, "supscr", f))
        """
        tok = self._next_non_space()
        if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
            self._pending_field = store
            self._expander.push_tokens([tok])
            return
        store(self._field_from_token(tok))

    def _field_from_token(self, tok) -> MathField:
        """Resolve an already-read *symbol* field token to a :class:`MathChar`.

        A letter/other char or a ``\\mathchardef`` constant becomes a
        :class:`MathChar`.  Any other token raises
        ``EngineError('math field expected')``.  A ``{`` never reaches here:
        both callers hand it to the main loop first.  Shared by
        :meth:`scan_math_field` and :meth:`add_class_primitive`'s symbol path.
        """
        if tok is None:
            raise EngineError("math field expected")
        if isinstance(tok, CharToken):
            if tok.catcode in (Catcode.LETTER, Catcode.OTHER):
                return self._mathchar_for_char(ord(tok.char))
            raise EngineError("math field expected")
        # ControlSequenceToken: a \mathchar/\mathchardef constant used as a
        # field — decode the constant directly so the field is a MathChar.
        if isinstance(tok, ControlSequenceToken):
            field = self._field_from_cs(tok)
            if field is not None:
                return field
        raise EngineError("math field expected")

    def _mathchar_for_char(self, char_code: int) -> MathChar:
        """Build the :class:`MathChar` a bare char maps to via its ``\\mathcode``."""
        code = self._code_arrays.get_mathcode(char_code)
        cls = (code >> 12) & 0x7
        fam = (code >> 8) & 0xF
        pos = code & 0xFF
        if cls == 7:
            cur_fam = self._current_fam()
            if 0 <= cur_fam <= 15:
                fam = cur_fam
        return MathChar(fam, pos)

    def _field_from_cs(self, tok: ControlSequenceToken) -> MathChar | None:
        """Resolve a CS field to a :class:`MathChar` if it is a math-char constant.

        ``\\mathchardef``-defined symbols (plain.tex ``\\alpha`` etc.) decode to a
        symbol field, as do ``\\mathchar <15-bit>`` and ``\\delimiter <27-bit>``
        (TeX §1151 scan_math: the delimiter's ``cur_val div 4096``, so
        ``\\mathopen\\lbrace`` gets the small brace).  Other control sequences
        return ``None``, and :meth:`_field_from_token` then raises
        ``EngineError('math field expected')``.
        """
        value: int | None = None
        if tok.name == "mathchar":
            value = parse_integer(self._expander, allow_negative=False)
        elif tok.name == "delimiter":
            value = parse_integer(self._expander, allow_negative=False) // 4096
        else:
            const = self._register_set.resolve_constant(tok.name)
            if const is not None and const[0] == "mathchardef":
                value = const[1]
        if value is not None:
            cls = (value >> 12) & 0x7
            fam = (value >> 8) & 0xF
            pos = value & 0xFF
            if cls == 7:
                cur_fam = self._current_fam()
                if 0 <= cur_fam <= 15:
                    fam = cur_fam
            return MathChar(fam, pos)
        return None

    # ------------------------------------------------------------------
    # §B.5 — scripts
    # ------------------------------------------------------------------

    def add_subscript(self) -> None:
        """Parse a subscript field and attach to the last atom (TeX §1176)."""
        self._attach_script("subscr")

    def add_superscript(self) -> None:
        """Parse a superscript field and attach to the last atom (TeX §1176)."""
        self._attach_script("supscr")

    def _attach_script(self, slot: str) -> None:
        target = self._script_target()
        if getattr(target, slot) is not None:
            kind = "subscript" if slot == "subscr" else "superscript"
            raise EngineError(f"double {kind}")
        self.scan_math_field(lambda field: setattr(target, slot, field))

    def _script_target(self) -> Noad:
        """Return the atom a script attaches to, creating an empty Ord if needed."""
        if self._mlist and self._mlist[-1].kind == NoadKind.ATOM:
            return self._mlist[-1]
        empty = Noad(NoadKind.ATOM, MathClass.ORD, nucleus=None)
        self._mlist.append(empty)
        return empty

    # ------------------------------------------------------------------
    # §B.6 — style / glue / kern / nonscript
    # ------------------------------------------------------------------

    def add_style(self, name: str) -> None:
        """``\\displaystyle`` / ``\\textstyle`` / ``\\scriptstyle`` / ``\\scriptscriptstyle``."""
        self._mlist.append(Noad(NoadKind.STYLE, style=_STYLE_NAMES[name]))

    def add_adjustment(self, node: AdjustNode) -> None:
        """Append raw adjustment material without introducing an atom class.

        Args:
            node: Zero-width carrier with the raw vertical material.

        Example::

            builder.add_adjustment(AdjustNode(list=[]))
        """
        self._mlist.append(Noad(NoadKind.ADJUST, adjustment=node))

    def add_rule(self, rule: RuleNode) -> None:
        """Append a classless raw rule to the current math list.

        Args:
            rule: Rule retaining its running dimension sentinels.
        """
        self._mlist.append(Noad(NoadKind.RULE, rule=rule))

    def add_penalty(self, penalty: int) -> None:
        """Append an explicit penalty to the current math list.

        Args:
            penalty: Integer break cost, including zero and forbidden breaks.
        """
        self._mlist.append(Noad(NoadKind.PENALTY, penalty=penalty))

    def add_leaders(self, leaders: LeadersNode) -> None:
        """Append leader glue to the current math list.

        Args:
            leaders: Shell owning its authoritative ordinary glue and payload.
        """
        self._mlist.append(Noad(NoadKind.GLUE, leaders=leaders))

    def add_glue(self, glue: Glue) -> None:
        r"""Append an ordinary horizontal glue node to the math list (§1171).

        TeX dispatches ``\hskip`` / ``\hfil`` / ``\hfill`` / ``\hss`` /
        ``\hfilneg`` in ``mmode`` to ``append_glue``, which puts a ``glue_node``
        in the *current math list*; §1196 passes it through in position and
        gives it no inter-atom spacing.  Appending such glue to the enclosing
        horizontal list instead makes it jump ahead of the whole formula, which
        is only spliced there at the ``$``-close.

        Distinct from :meth:`add_mskip`, whose value is in mu and is converted
        per style; this glue is already in scaled points and keeps its
        stretch/shrink orders verbatim.

        Args:
            glue: The glue to append, in scaled points.

        Example::

            builder.add_glue(Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL))
        """
        self._mlist.append(Noad(NoadKind.GLUE, glue=glue))

    def add_mskip(self) -> None:
        r"""``\mskip <muglue>`` — append a mu-glue carrier noad (FR-9).

        Scans a full ``<muglue>`` (TeX §1057/§1060 ``scan_glue(mu_val)``), so
        ``plus``/``minus`` and a ``\muskip`` register's stretch and shrink are
        kept.  The glue stays in mu on the noad's ``glue`` field and is
        converted per style at ``mlist_to_hlist`` time (§716).

        Example::

            # Stream "5mu plus 2mu minus 1fil":
            builder.add_mskip()   # GLUE noad, glue=Glue(327680, 131072, NORMAL, 65536, FIL)
        """
        glue = parse_glue(self._expander)
        self._mlist.append(Noad(NoadKind.GLUE, glue=glue, mu_glue=True))

    def add_mkern(self) -> None:
        """``\\mkern <mudimen>`` — append a mu-kern carrier noad (FR-9)."""
        value = parse_dimen(self._expander)
        self._mlist.append(Noad(NoadKind.KERN, width=value, mu_glue=True))

    def add_kern(self, width: int) -> None:
        r"""``\kern <dimen>`` in math mode — append an sp kern noad (TeX §1061).

        Unlike :meth:`add_mkern`, the width is already in scaled points and is
        not converted per style.

        Args:
            width: The kern width, in scaled points.

        Example::

            builder.add_kern(65536)   # \kern1pt
        """
        self._mlist.append(Noad(NoadKind.KERN, width=width))

    def add_nonscript(self) -> None:
        """``\\nonscript`` — mark the following glue for script suppression (FR-10)."""
        self._mlist.append(Noad(NoadKind.GLUE, glue_value=0, mu_glue=True, nonscript=True))

    # ------------------------------------------------------------------
    # §B.7 — placeholder structure builders (parse now, layout)
    # ------------------------------------------------------------------

    def add_fraction(self, name: str) -> None:
        """``\\over`` / ``\\atop`` / ``\\above`` (+ ``withdelims``) — structure only.

        The numerator is the mlist built so far; the denominator is the mlist
        built after (TeX:The Program §1181).  lays out the bar.
        """
        if self._fraction is not None:
            raise EngineError("ambiguous; you need another { and }")
        numerator = MathList(self._mlist)
        left_delim: DelimiterCode | None = None
        right_delim: DelimiterCode | None = None
        thickness: int | None
        if name in ("over", "overwithdelims"):
            thickness = DEFAULT_FRACTION_THICKNESS
        elif name in ("atop", "atopwithdelims"):
            thickness = None
        else:  # above / abovewithdelims
            if name == "abovewithdelims":
                left_delim = self._scan_delimiter()
                right_delim = self._scan_delimiter()
            thickness = parse_dimen(self._expander)
            self._begin_fraction(numerator, thickness, left_delim, right_delim)
            return
        if name.endswith("withdelims"):
            left_delim = self._scan_delimiter()
            right_delim = self._scan_delimiter()
        self._begin_fraction(numerator, thickness, left_delim, right_delim)

    def _begin_fraction(
        self,
        numerator: MathList,
        thickness: int | None,
        left_delim: DelimiterCode | None,
        right_delim: DelimiterCode | None,
    ) -> None:
        # The mlist-so-far is the numerator; the rest of the formula accumulates
        # into a fresh list that becomes the denominator at hand-off (§1181).
        self._fraction = Noad(
            NoadKind.FRACTION,
            math_class=MathClass.INNER,
            numerator=numerator,
            thickness=thickness,
            left_delim=left_delim,
            right_delim=right_delim,
        )
        self._mlist = []

    def add_boundary(self, name: str) -> None:
        """``\\left`` / ``\\right`` — open/close a math-left sub-group (TeX §1191).

        ``\\left<delim>`` opens a sub-group: the mlist-so-far is saved and a fresh
        inner mlist accumulates, so a ``\\over`` (and scripts) between ``\\left``
        and ``\\right`` scope to the group — ``\\left(a\\over b\\right)`` becomes
        ``\\left( {a\\over b} \\right)`` (one INNER atom whose nucleus is the
        fraction).  ``\\right<delim>`` closes it, appending a single
        ``Noad(ATOM, INNER, …)`` carrying both delimiters (sized by's
        rule-19 layout).  The depth bookkeeping stays in the math shell's
        ``check_left_right_balanced`` (preserved error contract).
        """
        delim = self._scan_delimiter()
        if name == "left":
            self._group_stack.append((self._mlist, self._fraction, None, None))
            self._boundary_stack.append(delim)
            self._mlist = []
            self._fraction = None
            return
        # \right: close the open math-left group into one INNER noad.
        inner = self._resolved_mlist()
        left_delim = self._boundary_stack.pop() if self._boundary_stack else None
        self._mlist, self._fraction, _store, _forced = self._group_stack.pop()
        self._mlist.append(
            Noad(
                NoadKind.ATOM,
                math_class=MathClass.INNER,
                nucleus=MathList(inner),
                left_delim=left_delim,
                right_delim=delim,
            )
        )

    def add_mathaccent(self) -> None:
        """``\\mathaccent <15-bit> <field>`` — structure only (layout)."""
        value = parse_integer(self._expander, allow_negative=False)
        self._append_with_field(
            Noad(
                NoadKind.ATOM,
                MathClass.ACCENT,
                accent_fam=(value >> 8) & 0xF,
                accent_pos=value & 0xFF,
            )
        )

    def add_radical(self) -> None:
        """``\\radical <27-bit> <field>`` — structure only (layout)."""
        value = parse_integer(self._expander, allow_negative=False)
        self._append_with_field(
            Noad(NoadKind.ATOM, MathClass.RADICAL, left_delim=_decode_delimiter(value))
        )

    def add_overline(self) -> None:
        """``\\overline <field>`` — structure only (layout)."""
        self._append_with_field(Noad(NoadKind.ATOM, MathClass.OVER))

    def add_underline(self) -> None:
        """``\\underline <field>`` — structure only (layout)."""
        self._append_with_field(Noad(NoadKind.ATOM, MathClass.UNDER))

    def _append_with_field(self, noad: Noad) -> None:
        """Append *noad* now and read its nucleus field into it (TeX §1163-§1165).

        The noad goes on the list before its field is read, as in TeX, so a
        ``{…}`` field built later by the main loop fills a noad that already
        sits in its place and a following script attaches to it.
        """
        self._mlist.append(noad)
        self.scan_math_field(lambda field: setattr(noad, "nucleus", field))

    def add_vcenter(self) -> None:
        r"""``\vcenter <box>`` — build the field as a real box ( C3).

        The field is built through the interpreter's box scanners (an executed
        ``\vbox``/``\hbox`` — implicit ``\vcenter{…}`` is a vbox), so an inner
        ``\ialign``→``\halign`` runs as ``exec_halign`` and the alignment grid is
        actually constructed.  The finished box is the VCENTER atom's nucleus
        (``MathField`` admits ``HlistNode``/``VlistNode``; ``mlist_to_hlist``
        axis-centres it).
        """
        interp = getattr(self._expander, "_interpreter", None)
        if interp is None:  # pragma: no cover - defensive; math runs with an interpreter
            raise EngineError("\\vcenter needs the interpreter")
        box = interp.build_math_vcenter_box()
        self._mlist.append(
            Noad(NoadKind.ATOM, MathClass.VCENTER, nucleus=box)
        )

    def add_mathchoice(self) -> None:
        r"""``\mathchoice{d}{t}{s}{ss}`` — arm a four-group capture.

        Does NOT scan the branches here.  Each ``{…}`` runs through the main
        loop's ``begin_group``/``end_group`` with full dispatch — so
        ``\setbox``/``\finph@nt``/box primitives inside ``\mathpalette`` /
        ``\mathph@nt`` execute; :meth:`end_group` diverts each finished
        sub-mlist into its :attr:`_choice_stack` entry and, on the fourth,
        appends the CHOICE noad.  The entry records the group depth here, so
        only the four groups at that depth are branches.  The four
        ``{`` that follow are left in the token stream for the main loop to
        open (TeX:The Program §1171 ``append_choices``
        likewise scans the branches one at a time as grouping ``math_choice``
        groups).
        """
        self._choice_stack.append((len(self._group_stack), []))

    # ------------------------------------------------------------------
    # delimiter scanning
    # ------------------------------------------------------------------

    def _scan_delimiter(self) -> DelimiterCode | None:
        """Read a ``<delimiter>`` operand: a char (via delcode) or ``\\delimiter``.

        TeX §1160 scan_delimiter: a letter/other char uses its ``\\delcode``; a
        ``\\delimiter`` (plain's ``\\lbrace``, ``\\langle`` …) scans its 27-bit
        code.  Anything else is no delimiter (``None``).
        """
        tok = self._next_non_space()
        if tok is None:
            raise EngineError("math delimiter expected")
        if isinstance(tok, ControlSequenceToken):
            if tok.name == "delimiter":
                return _decode_delimiter(parse_integer(self._expander, allow_negative=False))
            return None
        if isinstance(tok, CharToken):
            delcode = self._code_arrays.get_delcode(ord(tok.char))
            if delcode < 0:
                return None
            return _decode_delimiter(delcode)
        raise EngineError("math delimiter expected")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _next_non_space(self):
        """Return the next non-blank non-relax token, expanding macros (TeX §1151/§1160).

        Math-field and delimiter scanning expands: ``\\mathopen\\big(`` must
        expand ``\\big`` (a plain.tex macro) into its ``{\\hbox{…}}`` group, and
        ``\\left\\langle`` must expand a ``\\langle`` ``\\delimiter`` macro before
        its delcode/CS is read.  ``\\relax`` is skipped like a space, so plain's
        ``\\{`` (``\\relax\\ifmmode\\lbrace…``) reaches its ``\\delimiter``.  Uses
        the expander's unexpandable-token path so primitives and braces still
        arrive verbatim.
        """
        tok = self._expander._next_unexpandable()
        while (isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE) or (
            isinstance(tok, ControlSequenceToken) and tok.name == "relax"
        ):
            tok = self._expander._next_unexpandable()
        return tok


def _group_nucleus(inner: list[Noad]) -> MathField:
    """Return the nucleus a finished ``{…}`` atom group gets (TeX §1186).

    ``math_group``: a group whose list is one Ord noad with no scripts hands
    that noad's own nucleus up, so ``\\mathop{f}`` has the char ``f`` as its
    nucleus (with its italic correction, §749) and ``{\\hbox{f}}`` the box.
    Any other list stays a sub-mlist.  See amendment.
    """
    if len(inner) == 1:
        only = inner[0]
        if (
            only.kind == NoadKind.ATOM
            and only.math_class == MathClass.ORD
            and only.subscr is None
            and only.supscr is None
        ):
            return only.nucleus
    return MathList(inner)


def _decode_delimiter(value: int) -> DelimiterCode:
    """Decode a 27-bit ``\\delimiter`` / delcode integer (TeX:The Program §1160)."""
    small = (value >> 12) & 0xFFF
    large = value & 0xFFF
    return DelimiterCode(
        small_fam=(small >> 8) & 0xF,
        small_pos=small & 0xFF,
        large_fam=(large >> 8) & 0xF,
        large_pos=large & 0xFF,
    )
