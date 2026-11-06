r"""The hyphenation step of the second line-breaking pass (, §5).

When the first pass at ``\pretolerance`` fails, TeX hyphenates the words of the
paragraph before the second pass (tex.web §891-§918).  A word is tried after
every glue node outside math: §896 skips a non-letter prefix, §897-§898 collect
the letters of one font, §899 checks what follows, and §903-§918 rebuild the
word with the font's ligatures and kerns, inserting a discretionary at each
permitted position.

The reconstitution is a port of tex.web's ``reconstitute`` and its callers,
restricted to the engine's lig/kern model: only ``=:`` ligatures, no boundary
characters, and font kerns as ``KernNode(explicit=False)``.

Example::

    ctx = HyphenationContext(store, font_manager, lccode, uchyph=1, language=0,
                             left_min=2, right_min=3, missing_character=report)
    nodes = hyphenate_paragraph(nodes, ctx)
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from aspose_tex._engine.hyphenation import MAX_LETTERS, LanguageWhatsit
from aspose_tex._engine.linebreak import _math_mask
from aspose_tex._engine.nodes import (
    AdjustNode,
    CharNode,
    DiscretionaryNode,
    GlueNode,
    InsertNode,
    KernNode,
    LeadersNode,
    MarkNode,
    PenaltyNode,
    WhatsitNode,
)

if TYPE_CHECKING:
    from aspose_tex._engine.hyphenation import HyphenationStore
    from aspose_tex._fonts.font_manager import FontManager
    from aspose_tex._fonts.font_metrics import FontMetrics

# tex.web's non_char: "no character here" for cursors and boundaries.
_NON_CHAR: Final = 256
# §918: a replacement of more than 127 nodes drops the discretionary.
_MAX_REPLACE: Final = 127
# §899: nodes after the word that accept it (TeX's done4).
_WORD_ENDERS: Final = (WhatsitNode, GlueNode, LeadersNode, PenaltyNode,
                       InsertNode, AdjustNode, MarkNode)


@dataclasses.dataclass(frozen=True, slots=True)
class HyphenationContext:
    r"""Everything the hyphenation step reads from the job.

    Attributes:
        store: The job's pattern and exception store.
        font_manager: For ``\hyphenchar`` and the fonts' lig/kern programs.
        lccode: The live ``\lccode`` table.
        uchyph: ``\uchyph``; when not positive, a word starting with an
            uppercase letter (``\lccode`` differs) is not hyphenated.
        language: The paragraph's language (§1091), already normalised.
        left_min: The paragraph's ``\lefthyphenmin``, already ``norm_min``'d.
        right_min: The paragraph's ``\righthyphenmin``, already ``norm_min``'d.
        missing_character: Reports a hyphen character the font lacks (§915).

    Example::

        ctx = HyphenationContext(store, fm, lambda c: c, 1, 0, 2, 3, report)
    """

    store: HyphenationStore
    font_manager: FontManager
    lccode: Callable[[int], int]
    uchyph: int
    language: int
    left_min: int
    right_min: int
    missing_character: Callable[[str, int], None]


def hyphenate_paragraph(nodes: list, ctx: HyphenationContext) -> list:
    r"""Return *nodes* with discretionary hyphens inserted into eligible words.

    Words are tried after every glue node outside math, as TeX's second pass
    does (§866).  Nodes outside a rebuilt word are the same objects, and the
    input list is not changed.  A language whatsit switches the language and
    minima for the words that follow it (§1362).

    Args:
        nodes: The paragraph list, as handed to the line breaker.
        ctx: Store, fonts and parameters for this paragraph.

    Returns:
        A new list; equal to *nodes* when no word is hyphenated.

    Example::

        hyphenated = hyphenate_paragraph(paragraph_nodes, ctx)
    """
    in_math = _math_mask(nodes)
    state = [ctx.language, ctx.left_min, ctx.right_min]
    replacements: dict[int, tuple[int, list]] = {}
    for index, node in enumerate(nodes):
        if (isinstance(node, (GlueNode, LeadersNode)) and not in_math[index]
                and index + 1 < len(nodes)):
            found = _try_word(nodes, index + 1, ctx, list(state))
            if found is not None:
                start, end, rebuilt = found
                replacements[start] = (end, rebuilt)
        elif isinstance(node, WhatsitNode) and isinstance(node.data, LanguageWhatsit):
            state = [node.data.language, node.data.left_min, node.data.right_min]
    if not replacements:
        return list(nodes)
    result: list = []
    index = 0
    while index < len(nodes):
        if index in replacements:
            end, rebuilt = replacements[index]
            result.extend(rebuilt)
            index = end + 1
        else:
            result.append(nodes[index])
            index += 1
    return result


def _is_font_kern(node: object) -> bool:
    """TeX's ``kern_node`` with ``subtype = normal``: a lig/kern-table kern."""
    return (isinstance(node, KernNode) and not node.explicit
            and not node.italic_correction and not node.accent_kern)


def _try_word(
    nodes: list, first: int, ctx: HyphenationContext, state: list[int],
) -> tuple[int, int, list] | None:
    """Hyphenate the word starting at or after *first* (§894-§903).

    Returns ``(start, end, rebuilt)`` meaning ``nodes[start:end + 1]`` is
    replaced by ``rebuilt``, or ``None`` when the word is left alone.
    """
    lccode = ctx.lccode
    # §896: skip to the node `ha` just before the first letter.
    index = first
    while True:
        if index >= len(nodes):
            return None
        node = nodes[index]
        if isinstance(node, CharNode):
            code = node.source[0] if node.source else node.char
            font = node.font_name
            lower = lccode(code)
            if lower != 0:
                if lower == code or ctx.uchyph > 0:
                    break
                return None
        elif isinstance(node, WhatsitNode):
            if isinstance(node.data, LanguageWhatsit):
                state[:] = [node.data.language, node.data.left_min, node.data.right_min]
        elif not _is_font_kern(node):
            return None
        index += 1
    language, left_min, right_min = state
    hyf_char = ctx.font_manager.hyphenchar(font)
    if not 0 <= hyf_char <= 255:
        return None
    ha = index - 1
    if left_min + right_min > MAX_LETTERS:
        return None

    # §897-§898: collect the letters of font `font` into hu/hc; hb is the last node.
    hu = [0]
    hc = [0]
    hb = -1
    bchar = _NON_CHAR
    while index < len(nodes):
        node = nodes[index]
        if isinstance(node, CharNode):
            if node.font_name != font:
                break
            if node.source:
                bchar = node.source[0]
                letters = [(c, lccode(c)) for c in node.source]
                if any(lower == 0 for _, lower in letters) or len(hu) - 1 + len(letters) > MAX_LETTERS:
                    break
                hu.extend(c for c, _ in letters)
                hc.extend(lower for _, lower in letters)
            else:
                bchar = node.char
                lower = lccode(node.char)
                if lower == 0 or len(hu) - 1 == MAX_LETTERS:
                    break
                hu.append(node.char)
                hc.append(lower)
            hb = index
            bchar = _NON_CHAR
        elif _is_font_kern(node):
            hb = index
            bchar = _NON_CHAR
        else:
            break
        index += 1
    hn = len(hu) - 1

    # §899: enough letters, and what follows must permit hyphenation.
    if hn < left_min + right_min:
        return None
    while index < len(nodes):
        node = nodes[index]
        if isinstance(node, KernNode):
            if not _is_font_kern(node):
                break
        elif isinstance(node, _WORD_ENDERS):
            break
        elif not isinstance(node, CharNode):
            return None
        index += 1

    positions = ctx.store.hyphen_positions(language, hc[1:], left_min, right_min)
    if not positions:
        return None
    hyf = [0] * (hn + 1)
    for position in positions:
        hyf[position] = 1

    # §903: a same-font character (or ligature) before the word joins the rebuild.
    before = nodes[ha]
    if isinstance(before, CharNode) and before.font_name == font:
        start, j = ha, 0
        hu[0] = before.char
        init = (before.source or (before.char,), bool(before.source))
    else:
        start, j = ha + 1, 1
        init = ((), False)
    metrics = ctx.font_manager.get_metrics(font)
    if metrics is None:
        return None
    builder = _Reconstitution(metrics, font, hu, hyf, init)
    rebuilt = builder.run(j, hn, bchar, hyf_char, ctx.missing_character)
    return start, hb, rebuilt


class _Reconstitution:
    """tex.web §905-§918 over the word ``hu[0..hn]`` of one font."""

    __slots__ = ("_font", "_hu", "_hyf", "_hyphen_passed", "_init", "_metrics")

    def __init__(
        self, metrics: FontMetrics, font: str, hu: list[int], hyf: list[int],
        init: tuple[tuple[int, ...], bool],
    ) -> None:
        self._metrics = metrics
        self._font = font
        self._hu = hu
        self._hyf = hyf
        self._init = init
        self._hyphen_passed = 0

    def _item(self, code: int, source: list[int], ligature: bool) -> CharNode:
        if ligature:
            return CharNode(char=code, font_name=self._font, source=tuple(source))
        return CharNode(char=code, font_name=self._font)

    def reconstitute(self, j: int, n: int, bchar: int, hchar: int) -> tuple[int, list]:
        """Translate the cut prefix of ``hu[j..n]``; return its last index and nodes (§905-§911).

        Sets ``_hyphen_passed`` to the first odd position whose translation
        would change if a hyphen character followed it, else 0.
        """
        hu, hyf, metrics = self._hu, self._hyf, self._metrics
        self._hyphen_passed = 0
        cur_l = hu[j]
        if j == 0:
            source, ligature = list(self._init[0]), self._init[1]
        else:
            source, ligature = [cur_l], False
        if cur_l == _NON_CHAR:
            return j, []

        def cursor_right(at: int) -> tuple[int, int]:
            right = hu[at + 1] if at < n else bchar
            return right, hchar if hyf[at] & 1 else _NON_CHAR

        cur_r, cur_rh = cursor_right(j)
        kern = 0
        while True:
            test = cur_rh if cur_rh != _NON_CHAR else cur_r
            lig = kern_amount = None
            if test != _NON_CHAR:
                lig = metrics.ligature(cur_l, test)
                if lig is None:
                    kern_amount = metrics.kern(cur_l, test)
            if lig is None and kern_amount is None:
                if cur_rh == _NON_CHAR:
                    break
                cur_rh = _NON_CHAR
                continue
            if cur_rh != _NON_CHAR:
                # The hyphen would interact with cur_l: a break here changes it.
                self._hyphen_passed = j
                hchar = cur_rh = _NON_CHAR
                continue
            if hchar != _NON_CHAR and hyf[j] & 1:
                self._hyphen_passed = j
                hchar = _NON_CHAR
            if lig is None:
                kern = kern_amount
                break
            # §911 `=:`: the ligature replaces both; the cursor advances.
            cur_l, ligature = lig, True
            if j == n:
                break
            source.append(cur_r)
            j += 1
            cur_r, cur_rh = cursor_right(j)
        out: list = [self._item(cur_l, source, ligature)]
        if kern:
            out.append(KernNode(width=kern, explicit=False))
        return j, out

    def run(
        self, j: int, hn: int, bchar: int, hyf_char: int,
        missing_character: Callable[[str, int], None],
    ) -> list:
        """Rebuild ``hu[j..hn]`` with discretionaries at odd ``hyf`` (§913-§918)."""
        hu, hyf = self._hu, self._hyf
        out: list = []
        while True:
            lo = j
            m, items = self.reconstitute(j, hn, bchar, hyf_char)
            j = m + 1
            passed = self._hyphen_passed
            if passed == 0:
                out.extend(items)
                items = []
                if hyf[j - 1] & 1:
                    lo, passed = j, j - 1
            while passed > 0:
                # §914: develop both branches of a discretionary until they meet.
                major = list(items)
                i = passed
                hyf[i] = 0
                pre: list = []
                has_hyphen = self._metrics.has_char(hyf_char)
                if has_hyphen:
                    i += 1
                    saved, hu[i] = hu[i], hyf_char
                else:
                    missing_character(self._font, hyf_char)
                while lo <= i:
                    m, part = self.reconstitute(lo, i, _NON_CHAR, _NON_CHAR)
                    lo = m + 1
                    pre.extend(part)
                if has_hyphen:
                    hu[i] = saved
                    lo, i = i, i - 1
                post: list = []
                while lo < j:
                    while True:
                        m, part = self.reconstitute(lo, hn, bchar, _NON_CHAR)
                        lo = m + 1
                        post.extend(part)
                        if lo >= j:
                            break
                    while lo > j:
                        m, part = self.reconstitute(j, hn, bchar, _NON_CHAR)
                        j = m + 1
                        major.extend(part)
                if len(major) > _MAX_REPLACE:
                    out.extend(major)
                else:
                    out.append(DiscretionaryNode(pre=tuple(pre), post=tuple(post),
                                                 nobreak=tuple(major)))
                items = []
                passed = j - 1 if hyf[j - 1] & 1 else 0
            if j > hn:
                return out
