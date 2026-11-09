"""Tests for the sigma /xi math-font parameter provider (§A/B/C/D).

Covers AC-1 (sigma 22/xi 8 known TFM values), AC-2 / FR-4 (param-count validation,
never at assignment), NFR-1 (caching + invalidate), and AC-6
(MathFamilyRegistry.resolve_metrics + FontMetrics.param_count).

Known TFM values (probed from the bundled fonts at design size 10pt):
  cmsy10 sigma 22 axis_height          = 163840 sp
  cmsy10 sigma 5  math_x_height        = 282168 sp
  cmex10 xi 8  default_rule_thickness = 26213 sp
"""

from __future__ import annotations

import pytest

from aspose_tex._engine.group import GroupStack
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._fonts.math_family_registry import MathFamilyRegistry
from aspose_tex._fonts.math_font_parameters import (
    _SIGMA_PARAMS,
    _XI_PARAMS,
    MathFontParameters,
    MathStyle,
)
from aspose_tex.exceptions import EngineError

# Known TFM sigma /xi values at design size (10pt), in scaled points.
_CMSY10_AXIS_HEIGHT = 163840
_CMSY10_MATH_X_HEIGHT = 282168
_CMEX10_RULE_THICKNESS = 26213


def _setup() -> tuple[MathFontParameters, MathFamilyRegistry, FontManager]:
    groups = GroupStack()
    fonts = FontManager(group_stack=groups)
    fonts.load_font("tensy", "cmsy10")
    fonts.load_font("tenex", "cmex10")
    fonts.load_font("tenrm", "cmr10")
    registry = MathFamilyRegistry(groups, fonts)
    params = MathFontParameters(registry, fonts)
    return params, registry, fonts


class TestSigmaXiResolution:
    """AC-1: sigma 22 / xi 8 resolve to the known TFM values."""

    def test_axis_height_text_matches_cmsy10(self) -> None:
        params, registry, _fonts = _setup()
        registry.set_text(2, "tensy")

        assert params.axis_height(MathStyle.TEXT) == _CMSY10_AXIS_HEIGHT

    def test_default_rule_thickness_text_matches_cmex10(self) -> None:
        params, registry, _fonts = _setup()
        registry.set_text(3, "tenex")

        assert params.default_rule_thickness(MathStyle.TEXT) == _CMEX10_RULE_THICKNESS

    def test_math_x_height_aliases_param5(self) -> None:
        params, registry, _fonts = _setup()
        registry.set_text(2, "tensy")

        assert params.math_x_height(MathStyle.TEXT) == _CMSY10_MATH_X_HEIGHT

    def test_style_selects_slot(self) -> None:
        params, registry, fonts = _setup()
        fonts.load_font("scriptsy", "cmsy7")
        registry.set_text(2, "tensy")
        registry.set_script(2, "scriptsy")

        text = params.axis_height(MathStyle.TEXT)
        script = params.axis_height(MathStyle.SCRIPT)

        assert text == _CMSY10_AXIS_HEIGHT
        # cmsy7 is a smaller design size, so its axis height differs.
        assert script != text


class TestParamCountValidation:
    """AC-2 / FR-4: insufficient/unset symbol/extension font raises lazily."""

    def test_assignment_never_raises(self) -> None:
        _params, registry, _fonts = _setup()
        # Assigning a 7-param text font to family 2 must succeed silently
        # (load-without-execute contract).
        registry.set_text(2, "tenrm")

    def test_too_few_params_raises_on_read(self) -> None:
        params, registry, _fonts = _setup()
        registry.set_text(2, "tenrm")  # cmr10: 7 params < 22

        with pytest.raises(EngineError, match="is not a math symbol font"):
            params.num1(MathStyle.TEXT)

    def test_valid_symbol_font_does_not_raise(self) -> None:
        params, registry, _fonts = _setup()
        registry.set_text(2, "tensy")  # cmsy10: 22 params

        params.num1(MathStyle.TEXT)  # no raise

    def test_unset_family_raises_undefined(self) -> None:
        params, _registry, _fonts = _setup()

        with pytest.raises(EngineError, match="is undefined"):
            params.axis_height(MathStyle.TEXT)

    def test_extension_too_few_params_raises(self) -> None:
        params, registry, _fonts = _setup()
        # cmsy10 has 22 params >= 13, so use a font with <13 for family 3.
        registry.set_text(3, "tenrm")  # cmr10: 7 params < 13

        with pytest.raises(EngineError, match="is not a math extension font"):
            params.default_rule_thickness(MathStyle.TEXT)

    def test_error_role_matches_style(self) -> None:
        params, registry, _fonts = _setup()
        registry.set_script(2, "tenrm")

        with pytest.raises(EngineError, match=r"\\scriptfont 2 is not a math symbol font"):
            params.num1(MathStyle.SCRIPT)


class TestCaching:
    """NFR-1: FontMetrics resolved once per (family, style); invalidate() drops it."""

    def test_resolves_once_across_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        params, registry, fonts = _setup()
        registry.set_text(2, "tensy")

        # Spy on the FontManager resolution that resolve_metrics delegates to:
        # the (family, style) cache must keep it to a single resolve.
        calls = {"n": 0}
        original = fonts.get_metrics

        def _spy(cs_name: str):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return original(cs_name)

        monkeypatch.setattr(fonts, "get_metrics", _spy)

        params.axis_height(MathStyle.TEXT)
        params.num1(MathStyle.TEXT)
        params.denom1(MathStyle.TEXT)

        assert calls["n"] == 1

    def test_reassignment_changes_cached_identity(self) -> None:
        params, registry, fonts = _setup()
        fonts.load_font("othersy", "cmsy7")
        registry.set_text(2, "tensy")

        first = params.axis_height(MathStyle.TEXT)
        registry.set_text(2, "othersy")
        # a changed family key must not reuse the previous metrics.
        assert params.axis_height(MathStyle.TEXT) != first

        params.invalidate()
        assert params.axis_height(MathStyle.TEXT) != first


class TestRegistryPromotion:
    """AC-6: resolve_metrics + FontMetrics.param_count."""

    def test_resolve_metrics_returns_assigned(self) -> None:
        _params, registry, fonts = _setup()
        registry.set_text(2, "tensy")

        metrics = registry.resolve_metrics(2, MathStyle.TEXT)

        assert metrics is fonts.get_metrics("tensy")

    def test_resolve_metrics_unset_returns_none(self) -> None:
        _params, registry, _fonts = _setup()

        assert registry.resolve_metrics(2, MathStyle.TEXT) is None

    def test_resolve_metrics_per_style(self) -> None:
        _params, registry, fonts = _setup()
        fonts.load_font("scriptsy", "cmsy7")
        registry.set_text(2, "tensy")
        registry.set_script(2, "scriptsy")
        registry.set_scriptscript(2, "scriptsy")

        assert registry.resolve_metrics(2, MathStyle.TEXT) is fonts.get_metrics("tensy")
        assert registry.resolve_metrics(2, MathStyle.SCRIPT) is fonts.get_metrics("scriptsy")
        assert (
            registry.resolve_metrics(2, MathStyle.SCRIPTSCRIPT)
            is fonts.get_metrics("scriptsy")
        )

    def test_param_count(self) -> None:
        _params, _registry, fonts = _setup()

        assert fonts.get_metrics("tensy").param_count == 22  # cmsy10
        assert fonts.get_metrics("tenex").param_count == 13  # cmex10
        assert fonts.get_metrics("tenrm").param_count == 7  # cmr10

    def test_param_count_unchanged_by_override(self) -> None:
        _params, _registry, fonts = _setup()
        m = fonts.get_metrics("tenrm")

        m.set_fontdimen(50, 1234)  # out-of-range override

        assert m.param_count == 7
        assert m.fontdimen(50) == 1234  # override still readable
        assert m.fontdimen(99) == 0  # untouched out-of-range still 0


class TestCanonicalTables:
    """AC-5: index→name map matches §A exactly (no invented indices)."""

    def test_sigma_indices(self) -> None:
        assert _SIGMA_PARAMS == {
            "math_x_height": 5,
            "math_quad": 6,
            "num1": 8,
            "num2": 9,
            "num3": 10,
            "denom1": 11,
            "denom2": 12,
            "sup1": 13,
            "sup2": 14,
            "sup3": 15,
            "sub1": 16,
            "sub2": 17,
            "sup_drop": 18,
            "sub_drop": 19,
            "delim1": 20,
            "delim2": 21,
            "axis_height": 22,
        }

    def test_xi_indices(self) -> None:
        assert _XI_PARAMS == {
            "default_rule_thickness": 8,
            "big_op_spacing1": 9,
            "big_op_spacing2": 10,
            "big_op_spacing3": 11,
            "big_op_spacing4": 12,
            "big_op_spacing5": 13,
        }


class TestPlainTexFamilyBlock:
    """AC-6 (FR-5): the Plain-TeX-style family assignment populates real handles."""

    def test_family_assignment_block_resolves(self) -> None:
        _params, registry, fonts = _setup()
        fonts.load_font("sevensy", "cmsy7")
        fonts.load_font("fivesy", "cmsy5")

        # \textfont2=\tensy \scriptfont2=\sevensy \scriptscriptfont2=\fivesy
        registry.set_text(2, "tensy")
        registry.set_script(2, "sevensy")
        registry.set_scriptscript(2, "fivesy")

        assert registry.resolve_metrics(2, MathStyle.TEXT) is fonts.get_metrics("tensy")
        assert registry.resolve_metrics(2, MathStyle.SCRIPT) is fonts.get_metrics("sevensy")
