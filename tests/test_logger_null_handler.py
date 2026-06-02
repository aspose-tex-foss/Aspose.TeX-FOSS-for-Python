from __future__ import annotations

import importlib
import logging

import aspose_tex


def test_aspose_tex_logger_has_single_null_handler_after_reimport() -> None:
 logger = logging.getLogger("aspose_tex")
 before = [
 handler for handler in logger.handlers
 if isinstance(handler, logging.NullHandler)
 ]

 importlib.reload(aspose_tex)
 after = [
 handler for handler in logger.handlers
 if isinstance(handler, logging.NullHandler)
 ]

 assert logger.hasHandlers()
 assert len(after) == 1
 assert before == after
