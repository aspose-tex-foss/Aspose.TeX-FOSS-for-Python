"""Font table manager.

Manages TFM font loading, metric caching, and current-font tracking
with optional GroupStack integration for group-scoped font changes.

See for search path resolution and caching strategy.
"""
from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import TYPE_CHECKING

from aspose_tex._fonts.font_metrics import FontMetrics
from aspose_tex._fonts.pfb_parser import PfbData, parse_pfb
from aspose_tex._fonts.tfm_parser import TfmData, parse_tfm
from aspose_tex.exceptions import FontError

if TYPE_CHECKING:
 from aspose_tex._engine.group import GroupStack


class FontManager:
 """Manages font loading, caching, and current-font tracking.

 Font search order:
 1. Bundled ``aspose_tex/data/fonts/`` (accessed via importlib.resources).
 2. Directories in ``extra_search_paths`` (in order).

 Font definitions (``load_font``) are always global — they never
 participate in group save/restore. Current-font selection
 (``select_font``) IS local to groups when a GroupStack is supplied.

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
 group_stack: GroupStack for current-font scoping (FR-8).
 Pass None to disable group scoping.
 """
 self._cache: dict[str, TfmData] = {}
 self._pfb_cache: dict[str, PfbData | None] = {}
 self._fonts: dict[str, FontMetrics] = {}
 self._current: str | None = None
 self._extra_paths: list[Path] = list(extra_search_paths or [])
 self._group_stack = group_stack

 # ------------------------------------------------------------------
 # Font loading (always global — FR-5, FR-6, FR-7)
 # ------------------------------------------------------------------

 def load_font(
 self,
 cs_name: str,
 tfm_name: str,
 at_sp: int | None = None,
 scaled: int | None = None,
 ) -> None:
 """Parse a TFM file and register a font control sequence.

 Exactly one of ``at_sp`` or ``scaled`` may be specified; if neither
 is given, the design size from the TFM header is used.

 Args:
 cs_name: Control-sequence name (without backslash), e.g. ``"tenrm"``.
 tfm_name: TFM file name without extension, e.g. ``"cmr10"``.
 at_sp: Explicit size in scaled points (from ``at <dimen>``).
 scaled: Scale factor * 1000 (from ``scaled <number>``).
 E.g. 1200 → multiply design size by 1.2.

 Raises:
 FontError: If TFM file is not found or is corrupt.
 ValueError: If both at_sp and scaled are given.

 Example::

 mgr.load_font("tenrm", "cmr10")
 mgr.load_font("big", "cmr10", at_sp=14 * 65536)
 mgr.load_font("mag", "cmr10", scaled=1200)
 """
 if at_sp is not None and scaled is not None:
 raise ValueError("at_sp and scaled are mutually exclusive")
 tfm = self._load_tfm(tfm_name)
 if at_sp is not None:
 size_sp = at_sp
 elif scaled is not None:
 size_sp = tfm.design_size_sp * scaled // 1000
 else:
 size_sp = tfm.design_size_sp
 self._fonts[cs_name] = FontMetrics(tfm, size_sp, tfm_name=tfm_name)

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
 if cs_name not in self._fonts:
 raise FontError(f"\\{cs_name} is not a defined font")
 gs = self._group_stack
 if gs is not None and not gs.is_global_pending:
 old = self._current

 def _restore(val: str | None = old) -> None:
 self._current = val

 gs.save(("current_font",), _restore)
 elif gs is not None:
 gs.consume_global()
 self._current = cs_name

 @property
 def current_metrics(self) -> FontMetrics | None:
 """FontMetrics for the current font, or None if no font is selected."""
 if self._current is None:
 return None
 return self._fonts.get(self._current)

 # ------------------------------------------------------------------
 # Font introspection
 # ------------------------------------------------------------------

 def is_font(self, cs_name: str) -> bool:
 """Return True if cs_name is a loaded font control sequence."""
 return cs_name in self._fonts

 def get_metrics(self, cs_name: str) -> FontMetrics | None:
 """Return FontMetrics for cs_name, or None if not loaded."""
 return self._fonts.get(cs_name)

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
 m = self._fonts.get(cs_name)
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
 index: 1-based fontdimen index.

 Raises:
 FontError: If cs_name is not a loaded font.
 """
 metrics = self._fonts.get(cs_name)
 if metrics is None:
 raise FontError(f"\\{cs_name} is not a defined font")
 return metrics.fontdimen(index)

 def set_fontdimen(self, cs_name: str, index: int, value_sp: int) -> None:
 """Override fontdimen[index] for the named font.

 Args:
 cs_name: Font control-sequence name.
 index: 1-based fontdimen index.
 value_sp: New value in scaled points.

 Raises:
 FontError: If cs_name is not a loaded font.
 """
 metrics = self._fonts.get(cs_name)
 if metrics is None:
 raise FontError(f"\\{cs_name} is not a defined font")
 metrics.set_fontdimen(index, value_sp)

 def skewchar(self, cs_name: str) -> int:
 """Return the per-font ``\\skewchar`` integer value."""
 metrics = self._fonts.get(cs_name)
 if metrics is None:
 raise FontError(f"\\{cs_name} is not a defined font")
 return metrics.skewchar

 def set_skewchar(self, cs_name: str, value: int) -> None:
 """Set the per-font ``\\skewchar`` integer value."""
 metrics = self._fonts.get(cs_name)
 if metrics is None:
 raise FontError(f"\\{cs_name} is not a defined font")
 gs = self._group_stack
 if gs is not None and not gs.is_global_pending:
 old = metrics.skewchar
 gs.save(("font_skewchar", cs_name), lambda: setattr(metrics, "skewchar", old))
 elif gs is not None:
 gs.consume_global()
 metrics.skewchar = value

 def hyphenchar(self, cs_name: str) -> int:
 """Return the per-font ``\\hyphenchar`` integer value."""
 metrics = self._fonts.get(cs_name)
 if metrics is None:
 raise FontError(f"\\{cs_name} is not a defined font")
 return metrics.hyphenchar

 def set_hyphenchar(self, cs_name: str, value: int) -> None:
 """Set the per-font ``\\hyphenchar`` integer value."""
 metrics = self._fonts.get(cs_name)
 if metrics is None:
 raise FontError(f"\\{cs_name} is not a defined font")
 gs = self._group_stack
 if gs is not None and not gs.is_global_pending:
 old = metrics.hyphenchar
 gs.save(("font_hyphenchar", cs_name), lambda: setattr(metrics, "hyphenchar", old))
 elif gs is not None:
 gs.consume_global()
 metrics.hyphenchar = value

 # ------------------------------------------------------------------
 # PFB lookup (See )
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
