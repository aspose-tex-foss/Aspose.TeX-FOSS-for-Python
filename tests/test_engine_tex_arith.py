"""Tests for TeX's fixed-point arithmetic helpers (TeX §102-§107)."""

from __future__ import annotations

import pytest

from aspose_tex._engine.tex_arith import (
    UNITY,
    print_scaled,
    round_decimals,
    x_over_n,
    xn_over_d,
    xn_over_d_remainder,
)


@pytest.mark.parametrize(
    ("digits", "expected"),
    [
        ("", 0),
        ("5", 32768),
        ("3", 19661),  # 0.3 * 2^16 = 19660.8 rounds up
        ("1", 6554),
        ("27", 17695),
        ("99999999", UNITY),  # rounds all the way to 1.0
        ("000007", 0),
        # only the first 17 digits count (§452)
        ("12345678912345678", 8091),
        ("123456789123456789999", 8091),
    ],
)
def test_round_decimals(digits: str, expected: int) -> None:
    assert round_decimals(digits) == expected


@pytest.mark.parametrize(
    ("x", "n", "expected"),
    [(7, 2, 3), (-7, 2, -3), (0, 5, 0), (655360, 18, 36408)],
)
def test_x_over_n_truncates_toward_zero(x: int, n: int, expected: int) -> None:
    assert x_over_n(x, n) == expected


@pytest.mark.parametrize(
    ("x", "n", "d", "expected"),
    [
        (2, 7227, 254, (56, 230)),
        (-2, 7227, 254, (-56, -230)),
        (5, 1000, 2000, (2, 1000)),
        (0, 7227, 100, (0, 0)),
    ],
)
def test_xn_over_d_remainder_sign_follows_x(
    x: int, n: int, d: int, expected: tuple[int, int]
) -> None:
    q, r = xn_over_d_remainder(x, n, d)
    assert (q, r) == expected
    assert q * d + r == x * n


def test_xn_over_d_is_the_quotient() -> None:
    assert xn_over_d(-5, 3, 2) == -7
    # MiKTeX 24.4: \hskip.3333em in cmr10 (quad 655361sp) is 218430sp (§455)
    assert xn_over_d(655361, round_decimals("3333"), UNITY) == 218430


@pytest.mark.parametrize(
    ("sp", "expected"),
    [  # MiKTeX 24.4 ``\the\dimen0`` for ``\dimen0=<sp>sp``, minus the ``pt``
        (0, "0.0"),
        (1, "0.00002"),
        (-1, "-0.00002"),
        (19661, "0.3"),
        (21845, "0.33333"),
        (-32768, "-0.5"),
        (65535, "0.99998"),
        (98304, "1.5"),
        (218453, "3.33333"),
        (655360, "10.0"),
        (1073741823, "16383.99998"),
    ],
)
def test_print_scaled_matches_miktex(sp: int, expected: str) -> None:
    assert print_scaled(sp) == expected
