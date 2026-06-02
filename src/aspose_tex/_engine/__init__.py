"""TeX engine: macro expansion and future execution layer."""

from aspose_tex._engine.code_arrays import CodeArrays
from aspose_tex._engine.expansion import Expander, RegisterProvider
from aspose_tex._engine.inserts import InsertAccumulator
from aspose_tex._engine.internal_quantities import InternalQuantityRegistry, QuantityKind
from aspose_tex._engine.macro import MacroDefinition, Meaning
from aspose_tex._engine.math_shell import MathOperandKind, MathShellRegistry
from aspose_tex._engine.named_parameters import (
 NamedParameterRegistry,
 ParamKind,
)
from aspose_tex._engine.nodes import InsertNode

__all__ = [
 "CodeArrays",
 "Expander",
 "InsertAccumulator",
 "InsertNode",
 "InternalQuantityRegistry",
 "MacroDefinition",
 "MathOperandKind",
 "MathShellRegistry",
 "Meaning",
 "NamedParameterRegistry",
 "ParamKind",
 "QuantityKind",
 "RegisterProvider",
]
