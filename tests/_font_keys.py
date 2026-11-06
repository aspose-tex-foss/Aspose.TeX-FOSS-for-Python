"""Resolve expected persistent keys in the same font setup as a legacy fixture."""
import warnings
from functools import lru_cache

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.reader import StringInputSource


@lru_cache
def font_key(name: str, preamble: str = '', plain: bool = False) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        interp = TeXInterpreter(load_format='plain' if plain else False)
        interp.run(StringInputSource(preamble + r'\bye'))
    return interp._font_manager.font_id(name)
