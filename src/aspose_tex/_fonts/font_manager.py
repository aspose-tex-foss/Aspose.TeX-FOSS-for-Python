"""Font table manager.

Manages TFM font loading, metric caching, and current-font tracking
with optional GroupStack integration for group-scoped font changes.

See for search path resolution and caching strategy.
"""
from __future__ import annotations

import importlib.resources
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from aspose_tex._fonts.font_metrics import FontMetrics
from aspose_tex._fonts.pfb_parser import PfbData, parse_pfb
from aspose_tex._fonts.tfm_parser import TfmData, parse_tfm
from aspose_tex.exceptions import EngineError, FontError

if TYPE_CHECKING:
    from aspose_tex._engine.group import GroupStack


@dataclass(slots=True)
class _LoadedFont:
    """Job-owned font identity, independent of its scoped names."""

    key: str
    number: int
    metrics: FontMetrics
    source_key: str
    id_text: str


def _undefined_font(reference: str) -> FontError:
    """Keep opaque identifiers out of diagnostics at compatibility boundaries."""
    return FontError("Unknown font identifier" if reference.startswith("\x00font:")
                     else f"\\{reference} is not a defined font")


class FontManager:
    """Manages font loading, caching, and current-font tracking.

    Font search order:
      1. Bundled ``aspose_tex/data/fonts/`` (accessed via importlib.resources).
      2. Directories in ``extra_search_paths`` (in order).

    Loaded records persist for the job. Font bindings and current selection
    participate in group save/restore when a GroupStack is supplied.

    Example::

        mgr = FontManager()
        mgr.load_font("tenrm", "cmr10")
        mgr.load_font("bigfont", "cmr10", at_sp=14 * 65536)
        mgr.select_font("tenrm")
        width = mgr.current_metrics.char_metrics(ord("A")).width
    """

    def __init__(
        self,
        extra_search_paths: list[Path] | None = None,
        group_stack: GroupStack | None = None,
    ) -> None:
        """
        Args:
            extra_search_paths: Additional directories searched after bundled data.
            group_stack:        GroupStack for font binding and selection scoping.
                                Pass None to disable group scoping.
        """
        self._cache: dict[str, TfmData] = {}
        self._pfb_cache: dict[str, PfbData | None] = {}
        self._fonts: dict[str, _LoadedFont] = {}
        self._font_bindings: dict[str, str] = {}
        self._loaded_fonts: dict[tuple[str, int], str] = {}
        self._current: str | None = None
        self._extra_paths: list[Path] = list(extra_search_paths or [])
        self._group_stack = group_stack
        self._missing_character_sink: Callable[[str, int], None] | None = None
        # \nullfont is font number 0 in TeX and is ALWAYS defined (TeXbook §16,
        # tex.web §552).  Register it eagerly so a <font> read (e.g.
        # ``\the\fontdimen1\nullfont``) succeeds before \nullfont is ever
        # selected as a command.  See (follow-up to §E).
        self._register_nullfont()
        # Preserve font 0's identity across aliases or a redefined CS spelling.
        # A real loaded font at size zero still has character slots.
        self._nullfont_id = self.font_id("nullfont")
        self._nullfont_metrics = self.get_metrics(self._nullfont_id)

    def _register_nullfont(self) -> None:
        r"""Eagerly register the always-defined ``\nullfont`` (TeX font 0).

        ``\nullfont`` carries cmr10's char table for fallback measurement but
        has all seven space/quad fontdimens forced to zero, so glue and kerns
        derived from it vanish.  Registering it at construction makes
        ``is_font("nullfont")`` and ``fontdimen("nullfont", n)`` work from a
        cold start, matching real TeX where font 0 is predefined.
        """
        self.load_font("nullfont", "cmr10", at_sp=0)
        for i in range(1, 8):
            self.set_fontdimen("nullfont", i, 0)

    # ------------------------------------------------------------------
    # Font loading (persistent records, scoped bindings —)
    # ------------------------------------------------------------------

    def load_font(
        self,
        cs_name: str,
        tfm_name: str,
        at_sp: int | None = None,
        scaled: int | None = None,
        *,
        default_hyphenchar: int = 45,
        default_skewchar: int = -1,
        is_global: bool | None = None,
    ) -> None:
        """Parse a TFM file and register a font control sequence.

        Exactly one of ``at_sp`` or ``scaled`` may be specified; if neither
        is given, the design size from the TFM header is used.

        Args:
            cs_name:  Control-sequence name (without backslash), e.g. ``"tenrm"``.
            tfm_name: TFM file name without extension, e.g. ``"cmr10"``.
            is_global: Captured assignment scope, or None for the current scope.
            at_sp:    Explicit size in scaled points (from ``at <dimen>``).
            scaled:   Scale factor * 1000 (from ``scaled <number>``).
                      E.g. 1200 → multiply design size by 1.2.

        Raises:
            FontError: If TFM file is not found or is corrupt.
            ValueError: If both at_sp and scaled are given.

        Example::

            mgr.load_font("tenrm", "cmr10")
            mgr.load_font("big",   "cmr10", at_sp=14 * 65536)
            mgr.load_font("mag",   "cmr10", scaled=1200)
        """
        if at_sp is not None and scaled is not None:
            raise ValueError("at_sp and scaled are mutually exclusive")
        tfm_name = tfm_name.removesuffix(".tfm")
        tfm = self._load_tfm(tfm_name)
        if at_sp is not None:
            size_sp = at_sp
        elif scaled is not None:
            size_sp = tfm.design_size_sp * scaled // 1000
        else:
            size_sp = tfm.design_size_sp
        source_key = next(key for key, value in self._cache.items() if value is tfm)
        identity = (source_key, size_sp)
        # Font zero is never interned with a real font at size zero.
        key = self._loaded_fonts.get(identity) if self._fonts else None
        if key is None:
            number = len(self._fonts)
            key = f"\x00font:{number}"
            metrics = FontMetrics(tfm, size_sp, tfm_name=Path(tfm_name).name)
            metrics.hyphenchar = default_hyphenchar
            metrics.skewchar = default_skewchar
            self._fonts[key] = _LoadedFont(key, number, metrics, source_key, cs_name)
            if number:
                self._loaded_fonts[identity] = key
        gs = self._group_stack
        self.bind_font(cs_name, key, is_global=(gs is None or gs.is_global_pending)
                       if is_global is None else is_global)
        self._fonts[key].id_text = cs_name
        if gs is not None:
            gs.consume_global()

    def font_id(self, cs_name: str) -> str:
        """Resolve a live binding to its persistent key.

        Args:
            cs_name: A font control sequence name.

        Raises:
            FontError: If no font is bound to the name.
        """
        try:
            return self._font_bindings[cs_name]
        except KeyError:
            raise _undefined_font(cs_name) from None

    def bind_font(self, cs_name: str, font_id: str, *, is_global: bool) -> None:
        """Bind a name to an existing key, saving only the binding.

        Args:
            cs_name: Target name.
            font_id: Persistent loaded-font key.
            is_global: Whether to invalidate pending restores.
        """
        if font_id not in self._fonts:
            raise FontError("Unknown font identifier")
        gs = self._group_stack
        if gs is not None:
            if is_global:
                gs.retain_global(("font", cs_name))
            else:
                old = self._font_bindings.get(cs_name)
                def restore() -> None:
                    if old is None:
                        self._font_bindings.pop(cs_name, None)
                    else:
                        self._font_bindings[cs_name] = old
                gs.save(("font", cs_name), restore)
        self._font_bindings[cs_name] = font_id

    def font_id_text(self, font_id: str) -> str:
        """Return the live printable identifier of a persistent font key."""
        record = self._fonts.get(font_id)
        if record is None:
            raise _undefined_font(font_id)
        # TeX's font_id_text uses the synthetic FONT spelling for an empty CS.
        return record.id_text or "FONT"

    def font_name_text(self, font_id: str) -> str:
        """Return the TFM name and optional non-design size for a font key."""
        from aspose_tex._engine.tex_arith import print_scaled
        record = self._fonts.get(font_id)
        if record is None:
            raise _undefined_font(font_id)
        if record.number == 0:
            return "nullfont"
        metrics = record.metrics
        text = metrics.tfm_name
        if metrics.at_size_sp != metrics.design_size_sp:
            text += f" at {print_scaled(metrics.at_size_sp)}pt"
        return text

    # ------------------------------------------------------------------
    # Font selection (local to groups — FR-8)
    # ------------------------------------------------------------------

    def select_font(self, cs_name: str) -> None:
        """Set the current font (invoked when a font CS is executed as a command).

        Saves the current-font name to the GroupStack before changing it,
        so the change is undone when the enclosing group closes.
        At global level (depth == 0 or no group_stack) the change is permanent.

        Args:
            cs_name: Previously loaded font control-sequence name.

        Raises:
            FontError: If cs_name has not been loaded via load_font.
        """
        self.select_font_id(cs_name if cs_name.startswith("\x00font:") else self.font_id(cs_name))

    def select_font_id(self, font_id: str) -> None:
        """Select an existing persistent font key, with ordinary assignment scope."""
        if font_id not in self._fonts:
            raise FontError("Unknown font identifier")
        gs = self._group_stack
        if gs is not None and not gs.is_global_pending:
            old = self._current

            def _restore(val: str | None = old) -> None:
                self._current = val

            gs.save(("current_font",), _restore)
        elif gs is not None:
            gs.retain_global(("current_font",))
        self._current = font_id
        if gs is not None:
            gs.consume_global()

    @property
    def current_metrics(self) -> FontMetrics | None:
        """FontMetrics for the current font, or None if no font is selected."""
        if self._current is None:
            return None
        return self.get_metrics(self._current)

    @property
    def current_font_id(self) -> str | None:
        """Return the persistent current font key, or None."""
        return self._current

    @property
    def current_cs(self) -> str | None:
        """Compatibility reader for current id_text, independent of its binding.

        Runtime font readers use current_font_id, since id_text can name a
        control sequence that has since been rebound or become undefined.
        """
        return self.font_id_text(self._current) if self._current is not None else None

    # ------------------------------------------------------------------
    # Font introspection
    # ------------------------------------------------------------------

    def is_font(self, cs_name: str) -> bool:
        """Return True if cs_name is currently bound to a loaded font."""
        return cs_name in self._font_bindings

    def alias_font(self, target: str, source: str, *, is_global: bool | None = None) -> None:
        r"""Bind *target* to the font of *source* (``\let\a=\tenrm``, D2).

        Both names share one :class:`FontMetrics`, so ``\fontdimen`` changes
        through either are seen by both.

        Args:
            target: New font control-sequence name.
            source: Name of a loaded font.

        Example::

            mgr.alias_font("rm", "tenrm")
        """
        key = source if source in self._fonts else self.font_id(source)
        gs = self._group_stack
        if is_global is None:
            is_global = gs is None or gs.is_global_pending
        self.bind_font(target, key, is_global=is_global)
        if gs is not None:
            gs.consume_global()

    def get_metrics(self, cs_name: str) -> FontMetrics | None:
        """Return FontMetrics for cs_name, or None if not loaded."""
        key = cs_name if cs_name.startswith("\x00font:") else self._font_bindings.get(cs_name)
        record = self._fonts.get(key)
        return record.metrics if record is not None else None

    def set_missing_character_sink(
        self, sink: Callable[[str, int], None] | None,
    ) -> None:
        """Install the job's missing-glyph diagnostic callback.

        Args:
            sink: Callback receiving font binding and byte code, or None.

        Example::

            missing = []
            mgr.set_missing_character_sink(lambda font, code: missing.append((font, code)))
        """
        self._missing_character_sink = sink

    def check_character(self, font_name: str, code: int) -> bool:
        """Admit a TFM character, reporting each missing construction attempt.

        Args:
            font_name: Loaded font binding (aliases retain font-0 identity).
            code: TeX character code.

        Returns:
            Whether the font contains the character, independent of outlines.

        Raises:
            FontError: If the font binding is unknown.

        Example::

            mgr.load_font("rm", "cmr10")
            assert mgr.check_character("rm", ord("A"))
        """
        metrics = self.get_metrics(font_name)
        if metrics is None:
            raise _undefined_font(font_name)
        if metrics is not self._nullfont_metrics and metrics.has_char(code):
            return True
        if self._missing_character_sink is not None:
            self._missing_character_sink(font_name, code)
        return False

    def font_def_info(self, cs_name: str) -> tuple[str, int, int, int] | None:
        """Return DVI font-definition data for a loaded font.

        Args:
            cs_name: Control-sequence name (e.g. ``"tenrm"``).

        Returns:
            ``(tfm_name, checksum, design_size_sp, at_size_sp)`` or ``None``
            if cs_name is not a loaded font.

        Example::

            info = mgr.font_def_info("tenrm")
            # ("cmr10", 1274110073, 655360, 655360)
        """
        m = self.get_metrics(cs_name)
        if m is None:
            return None
        return (m.tfm_name, m.checksum, m.design_size_sp, m.at_size_sp)

    # ------------------------------------------------------------------
    # fontdimen access (FR-10)
    # ------------------------------------------------------------------

    def fontdimen(self, cs_name: str, index: int) -> int:
        """Return fontdimen[index] for the named font in scaled points.

        Args:
            cs_name: Font control-sequence name.
            index:   1-based fontdimen index.

        Raises:
            FontError: If cs_name is not a loaded font.
        """
        metrics = self.get_metrics(cs_name)
        if metrics is None:
            raise _undefined_font(cs_name)
        return metrics.fontdimen(index)

    def set_fontdimen(self, cs_name: str, index: int, value_sp: int) -> None:
        """Override fontdimen[index] for the named font.

        Args:
            cs_name:  Font control-sequence name.
            index:    1-based fontdimen index.
            value_sp: New value in scaled points.

        Raises:
            FontError: If cs_name is not a loaded font.
        """
        metrics = self.get_metrics(cs_name)
        if metrics is None:
            raise _undefined_font(cs_name)
        metrics.set_fontdimen(index, value_sp)

    def skewchar(self, cs_name: str) -> int:
        """Return the per-font ``\\skewchar`` integer value."""
        metrics = self.get_metrics(cs_name)
        if metrics is None:
            raise _undefined_font(cs_name)
        return metrics.skewchar

    def set_skewchar(self, cs_name: str, value: int) -> None:
        """Set the per-font ``\\skewchar`` integer value."""
        metrics = self.get_metrics(cs_name)
        if metrics is None:
            raise _undefined_font(cs_name)
        gs = self._group_stack
        # §1253 stores font integers globally, independent of group prefixes.
        if gs is not None:
            gs.consume_global()
        metrics.skewchar = value

    def hyphenchar(self, cs_name: str) -> int:
        """Return the per-font ``\\hyphenchar`` integer value."""
        metrics = self.get_metrics(cs_name)
        if metrics is None:
            raise _undefined_font(cs_name)
        return metrics.hyphenchar

    def set_hyphenchar(self, cs_name: str, value: int) -> None:
        """Set the per-font ``\\hyphenchar`` integer value."""
        metrics = self.get_metrics(cs_name)
        if metrics is None:
            raise _undefined_font(cs_name)
        gs = self._group_stack
        if gs is not None:
            gs.consume_global()
        metrics.hyphenchar = value

    # ------------------------------------------------------------------
    # PFB lookup (See)
    # ------------------------------------------------------------------

    def find_pfb(self, tfm_name: str) -> bytes | None:
        """Locate and read a PFB file corresponding to a TFM name.

        Searches in the same locations as TFM files: bundled data first,
        then extra_search_paths.

        Args:
            tfm_name: TFM file stem without extension (e.g. "cmr10").

        Returns:
            Raw bytes of the PFB file, or None if not found.

        Example::

            raw = mgr.find_pfb("cmr10")
            if raw is not None:
                pfb = parse_pfb(raw)
        """
        if self.is_font(tfm_name):
            tfm_name = self.font_id(tfm_name)
        if tfm_name.startswith("\x00font:"):
            record = self._fonts.get(tfm_name)
            if record is None:
                return None
            if not record.source_key.startswith("bundled:"):
                path = Path(record.source_key).with_suffix(".pfb")
                return path.read_bytes() if path.exists() else None
            tfm_name = record.metrics.tfm_name

        pkg = importlib.resources.files("aspose_tex") / "data" / "fonts"
        resource = pkg / f"{tfm_name}.pfb"
        try:
            return resource.read_bytes()
        except FileNotFoundError:
            pass

        for search_dir in self._extra_paths:
            candidate = search_dir / f"{tfm_name}.pfb"
            if candidate.exists():
                try:
                    return candidate.read_bytes()
                except OSError as exc:
                    raise FontError(f"Cannot read {candidate}: {exc}") from exc

        return None

    def load_pfb(self, tfm_name: str) -> PfbData | None:
        """Locate, read, and parse a PFB file for the given TFM name.

        Convenience method that combines find_pfb + parse_pfb.
        Caches the parsed PfbData so repeated calls are O(1).

        Args:
            tfm_name: TFM file stem without extension (e.g. "cmr10").

        Returns:
            Parsed PfbData, or None if no PFB file exists for this font.

        Raises:
            FontError: If PFB file exists but is corrupt.
        """
        if self.is_font(tfm_name):
            tfm_name = self.font_id(tfm_name)
        if tfm_name in self._pfb_cache:
            return self._pfb_cache[tfm_name]

        raw = self.find_pfb(tfm_name)
        if raw is None:
            self._pfb_cache[tfm_name] = None
            return None

        pfb = parse_pfb(raw)
        self._pfb_cache[tfm_name] = pfb
        return pfb

    # ------------------------------------------------------------------
    # Internal: TFM lookup & caching
    # ------------------------------------------------------------------

    def _load_tfm(self, name: str) -> TfmData:
        """Resolve tfm_name to TfmData, using the cache.

        Search order: bundled data → extra_search_paths.

        Args:
            name: TFM name without extension, e.g. ``"cmr10"``.

        Returns:
            Cached or freshly parsed TfmData.

        Raises:
            FontError: If not found or corrupt.
        """
        name = os.path.normpath(name).replace("\\", "/")
        bundled_key = f"bundled:{name}"
        if bundled_key in self._cache:
            return self._cache[bundled_key]

        pkg = importlib.resources.files("aspose_tex") / "data" / "fonts"
        resource = pkg / f"{name}.tfm"
        try:
            raw = resource.read_bytes()
            tfm = parse_tfm(raw)
            self._cache[bundled_key] = tfm
            return tfm
        except FileNotFoundError:
            pass
        # FontError from parse_tfm propagates — a corrupt bundled TFM is a real error.

        for search_dir in self._extra_paths:
            candidate = search_dir / f"{name}.tfm"
            if not candidate.exists():
                continue
            path_key = str(candidate.resolve())
            if path_key in self._cache:
                return self._cache[path_key]
            try:
                raw = candidate.read_bytes()
            except OSError as exc:
                raise FontError(f"Cannot read {candidate}: {exc}") from exc
            tfm = parse_tfm(raw)
            self._cache[path_key] = tfm
            return tfm

        raise FontError(
            f"TFM file not found: {name}.tfm "
            f"(searched bundled data and {self._extra_paths})"
        )


# ----------------------------------------------------------------------
# Shared <font> operand resolver (§E)
# ----------------------------------------------------------------------

def resolve_font_cs(font_manager: FontManager, cs_name: str | None) -> str:
    r"""Resolve a TeX ``<font>`` operand to a font control-sequence name.

    Implements TeX's ``<font>`` grammar (§E): the operand may be the
    ``\font`` control sequence (the current font), a ``\font``-defined CS, or
    ``\nullfont``.  Shared by the dimparser ``\fontdimen<n>\font`` arm and the
    interpreter's ``\the\fontdimen`` / ``\fontdimen…=`` / ``\skewchar`` /
    ``\hyphenchar`` operand readers so all of them accept ``\font``.

    Args:
        font_manager: The active font manager.
        cs_name:      The name of the already-consumed control-sequence operand
                      (without backslash), or ``None`` if the operand token was
                      not a control sequence.

    Returns:
        The resolved font control-sequence name.

    Raises:
        EngineError: If the operand is not a valid ``<font>`` (not a control
                     sequence, ``\font`` with no current font, or a CS that is
                     not a defined font).
    """
    if cs_name is None:
        raise EngineError("Missing font identifier")
    if font_manager.is_font(cs_name):
        return font_manager.font_id(cs_name)
    if cs_name == "font":
        current = font_manager.current_font_id
        if current is None:
            raise EngineError("\\font has no current font")
        return current
    if cs_name.startswith("\x00font:"):
        if cs_name in font_manager._fonts:
            return cs_name
        raise EngineError("Unknown font identifier")
    if cs_name == "nullfont":
        return font_manager.font_id("nullfont")
    raise EngineError(f"\\{cs_name} is not a font")


def scan_font_id(expander) -> str:
    """Read an expanded font operand, including a math-family slot.

    Args:
        expander: Scanner wired to the active interpreter.

    Returns:
        A persistent font key.

    Raises:
        EngineError: If the operand is not a font.
    """
    from aspose_tex._input.catcode import Catcode
    from aspose_tex._input.token import CharToken
    tok = expander.get_x_token()
    while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
        tok = expander.get_x_token()
    tok = expander.primitive_token(tok)
    return _resolve_font_operand(expander, tok)


def _resolve_font_operand(expander, tok) -> str:
    """Resolve a consumed operand by meaning, preserving frozen primitives."""
    from aspose_tex._engine.dimparser import parse_integer
    from aspose_tex._input.token import ControlSequenceToken, FontRefToken, PrimitiveRefToken
    interp = expander._interpreter
    manager = interp._font_manager
    name = tok.name if isinstance(tok, ControlSequenceToken) else None
    if isinstance(tok, FontRefToken):
        return resolve_font_cs(manager, name)
    if not isinstance(tok, PrimitiveRefToken) and name is not None:
        if manager.is_font(name):
            return manager.font_id(name)
        if expander._bindings is not None and expander._bindings.binding_of(name) is not None:
            raise EngineError("Missing font identifier")
    if name in ("textfont", "scriptfont", "scriptscriptfont"):
        family = parse_integer(expander, allow_negative=False)
        getter = getattr(interp._math_family_registry, "get_" + name.removesuffix("font"))
        return getter(family) or manager._nullfont_id
    if isinstance(tok, PrimitiveRefToken):
        if name == "nullfont":
            return manager._nullfont_id
        if name == "font":
            if manager.current_font_id is None:
                raise EngineError("\\font has no current font")
            return manager.current_font_id
        raise EngineError("Missing font identifier")
    return resolve_font_cs(manager, name)
