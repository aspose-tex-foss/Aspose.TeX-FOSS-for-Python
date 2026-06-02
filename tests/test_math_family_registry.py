from __future__ import annotations

import pytest

from aspose_tex._engine.group import GroupKind, GroupStack
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._fonts.math_family_registry import MathFamilyRegistry
from aspose_tex.exceptions import EngineError, FontError


def _registry() -> tuple[MathFamilyRegistry, GroupStack]:
 groups = GroupStack()
 fonts = FontManager(group_stack=groups)
 fonts.load_font("tenrm", "cmr10")
 fonts.load_font("sevenrm", "cmr7")
 fonts.load_font("fiverm", "cmr5")
 return MathFamilyRegistry(groups, fonts), groups


class TestMathFamilyRegistry:
 def test_default_all_none(self) -> None:
 registry, _groups = _registry()

 assert all(registry.get_text(i) is None for i in range(16))
 assert all(registry.get_script(i) is None for i in range(16))
 assert all(registry.get_scriptscript(i) is None for i in range(16))

 def test_set_text_writes_slot(self) -> None:
 registry, _groups = _registry()

 registry.set_text(0, "tenrm")

 assert registry.get_text(0) == "tenrm"

 def test_set_script_writes_slot(self) -> None:
 registry, _groups = _registry()

 registry.set_script(0, "sevenrm")

 assert registry.get_script(0) == "sevenrm"

 def test_set_scriptscript_writes_slot(self) -> None:
 registry, _groups = _registry()

 registry.set_scriptscript(0, "fiverm")

 assert registry.get_scriptscript(0) == "fiverm"

 def test_set_unknown_font_raises(self) -> None:
 registry, _groups = _registry()

 with pytest.raises(FontError, match="not a font"):
 registry.set_text(0, "missing")

 @pytest.mark.parametrize("family", [-1, 16])
 def test_family_range_validation(self, family: int) -> None:
 registry, _groups = _registry()

 with pytest.raises(EngineError, match="out of range 0-15"):
 registry.set_text(family, "tenrm")

 def test_group_save_restore_text(self) -> None:
 registry, groups = _registry()
 registry.set_text(0, "tenrm")
 groups.open_group(GroupKind.BRACE)

 registry.set_text(0, "sevenrm")
 groups.close_group()

 assert registry.get_text(0) == "tenrm"

 def test_group_save_restore_script(self) -> None:
 registry, groups = _registry()
 registry.set_script(0, "tenrm")
 groups.open_group(GroupKind.BRACE)

 registry.set_script(0, "sevenrm")
 groups.close_group()

 assert registry.get_script(0) == "tenrm"

 def test_group_save_restore_scriptscript(self) -> None:
 registry, groups = _registry()
 registry.set_scriptscript(0, "tenrm")
 groups.open_group(GroupKind.BRACE)

 registry.set_scriptscript(0, "fiverm")
 groups.close_group()

 assert registry.get_scriptscript(0) == "tenrm"

 def test_global_flag_skips_save(self) -> None:
 registry, groups = _registry()
 registry.set_text(0, "tenrm")
 groups.open_group(GroupKind.BRACE)

 registry.set_text(0, "sevenrm", global_=True)
 groups.close_group()

 assert registry.get_text(0) == "sevenrm"

 def test_three_roles_independent(self) -> None:
 registry, _groups = _registry()

 registry.set_text(0, "tenrm")
 registry.set_script(0, "sevenrm")
 registry.set_scriptscript(0, "fiverm")

 assert registry.get_text(0) == "tenrm"
 assert registry.get_script(0) == "sevenrm"
 assert registry.get_scriptscript(0) == "fiverm"
