"""Verification helpers referenced by FR-4.

These modules are intentionally import-safe (no side effects on import, no
logging handlers, no ``print`` at module scope) so they can be used from
inline task verification blocks and reviewer replay without polluting
state.
"""
