"""Agent core package.

This package contains the new agent loop modules (core/agent/*) while the
legacy API still relies on AgentEngine defined in core/agent.py.
Expose AgentEngine here for backward compatibility.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_legacy_agent_engine():
    legacy_path = Path(__file__).resolve().parent.parent / "agent.py"
    spec = spec_from_file_location("core._legacy_agent_module", legacy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load legacy AgentEngine from {legacy_path}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    engine = getattr(module, "AgentEngine", None)
    if engine is None:
        raise ImportError("AgentEngine not found in core/agent.py")
    return engine


AgentEngine = _load_legacy_agent_engine()

__all__ = ["AgentEngine"]
