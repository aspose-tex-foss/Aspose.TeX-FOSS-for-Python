"""Per-list cumulative set-glue rounding (TeX §625/§634)."""
from __future__ import annotations

from aspose_tex._engine.nodes import GlueSign, HlistNode, VlistNode
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._engine.tex_arith import tex_round, to_binary32


class GlueSetter:
    """Set-glue state of one traversed box, recreated on each recursive visit.

    Every glue and leaders node uses this setter in list order. Nested boxes
    own separate state so rounding errors cannot accumulate between lists.

    Example::

        setter = GlueSetter(GlueSign.STRETCHING, GlueOrder.FIL, 0.5)
        setter.set_size(Glue(0, 3, GlueOrder.FIL, 0, GlueOrder.NORMAL))  # -> 2
    """

    __slots__ = ("_cur_g", "_cur_glue", "_order", "_ratio", "_sign")

    def __init__(self, sign: GlueSign, order: GlueOrder, ratio: float) -> None:
        self._sign = sign
        self._order = order
        self._ratio = ratio
        self._cur_glue = 0.0
        self._cur_g = 0

    @classmethod
    def for_box(cls, box: HlistNode | VlistNode) -> GlueSetter:
        """Return a fresh setter for the glue parameters of *box*."""
        return cls(box.glue_sign, box.glue_order, box.glue_set)

    def set_size(self, glue: Glue) -> int:
        """Return the size in sp of the next glue or leaders of this list."""
        if self._sign == GlueSign.STRETCHING and glue.stretch_order == self._order:
            self._cur_glue = to_binary32(self._cur_glue + to_binary32(glue.stretch))
        elif self._sign == GlueSign.SHRINKING and glue.shrink_order == self._order:
            self._cur_glue = to_binary32(self._cur_glue - to_binary32(glue.shrink))
        else:
            return glue.width
        # TeX's vet_glue clamps the binary32 product before Pascal round (§625).
        product = max(-1e9, min(1e9, to_binary32(self._ratio * self._cur_glue)))
        new = tex_round(product)
        size = glue.width + new - self._cur_g
        self._cur_g = new
        return size
