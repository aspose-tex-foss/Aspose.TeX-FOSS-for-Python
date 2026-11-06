"""TeX's fixed-point arithmetic (TeX: The Program §99-§108, §452).

One home for the integer routines tex.web uses to turn fractions into scaled
points, so the dimension scanner (:mod:`dimparser`) and the math-list
translator (:mod:`mlist_to_hlist`) round and truncate exactly as TeX does.
Python ints are unbounded, so none of TeX's overflow-avoiding splits are
needed; only the rounding direction and the remainder sign matter.
The §109 binary32 glue-ratio arithmetic also lives here.
"""

from __future__ import annotations

from collections.abc import Sequence
from struct import pack, unpack
from typing import Final

UNITY: Final[int] = 1 << 16
"""``unity`` (§101): 1.0 in TeX's 16.16 fixed point — sp per pt, mu per mu."""


def to_binary32(value: float) -> float:
    """Round *value* to IEEE-754 binary32 (§109).

    Example::

        to_binary32(0.1)  # -> 0.10000000149011612
    """
    return unpack("f", pack("f", value))[0]


def glue_ratio(numerator: int, denominator: int) -> float:
    """Return the binary32 quotient of binary32 operands (§658/§664/§672/§676).

    The denominator must be nonzero; either operand may be negative.

    Example::

        glue_ratio(39666195, 65536)  # -> 605.2581176757812
    """
    return to_binary32(to_binary32(numerator) / to_binary32(denominator))


def tex_round(value: float) -> int:
    """Round to the nearest integer, halves away from zero (Pascal §3).

    Example::

        tex_round(2.5), tex_round(-2.5)  # -> (3, -3)
    """
    return int(value + 0.5) if value >= 0 else int(value - 0.5)


def round_decimals(digits: Sequence[str]) -> int:
    """§102 ``round_decimals``: decimal fraction digits → nearest 2^-16 units.

    Only the first 17 digits are used; later ones cannot affect the result
    (§452).

    Example::

        round_decimals("3")   # -> 19661, so .3pt is 19661 sp
    """
    a = 0
    for d in reversed(digits[:17]):
        a = (a + int(d) * 2 * UNITY) // 10
    return (a + 1) // 2


def x_over_n(x: int, n: int) -> int:
    """§106 ``x_over_n``: ``x / n`` truncated toward zero, for ``n > 0``.

    Example::

        x_over_n(-7, 2)   # -> -3
    """
    q = abs(x) // n
    return q if x >= 0 else -q


def xn_over_d(x: int, n: int, d: int) -> int:
    """§107 ``xn_over_d``: ``x * n / d`` truncated toward zero, for ``n, d > 0``.

    Example::

        xn_over_d(-5, 3, 2)   # -> -7
    """
    return xn_over_d_remainder(x, n, d)[0]


def xn_over_d_remainder(x: int, n: int, d: int) -> tuple[int, int]:
    """§107 ``xn_over_d`` together with the ``remainder`` global it sets.

    The quotient truncates toward zero and the remainder carries the sign of
    ``x``, so ``quotient * d + remainder == x * n`` always holds.

    Example::

        xn_over_d_remainder(2, 7227, 254)   # -> (56, 230): 2cm is 56pt + 230/254
    """
    q, r = divmod(abs(x) * n, d)
    return (q, r) if x >= 0 else (-q, -r)


def print_scaled(s: int) -> str:
    """§103 ``print_scaled``: the shortest decimal that scans back to ``s``.

    ``s`` is a 16.16 fixed-point value; at least one digit follows the point.

    Example::

        print_scaled(218453)   # -> "3.33333"
        print_scaled(-32768)   # -> "-0.5"
    """
    sign = "-" if s < 0 else ""
    s = abs(s)
    digits = [f"{sign}{s // UNITY}."]
    s = 10 * (s % UNITY) + 5
    delta = 10
    while True:
        if delta > UNITY:
            s += 0o100000 - 50000  # round the last digit
        digits.append(str(s // UNITY))
        s = 10 * (s % UNITY)
        delta *= 10
        if s <= delta:
            return "".join(digits)
