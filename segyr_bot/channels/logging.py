from __future__ import annotations

import logging

try:  # Prefer project-wide configured logger.
    from core.logging import logger as logger  # type: ignore
except Exception:  # pragma: no cover - fallback for lightweight runtimes/tests
    try:
        from loguru import logger as logger  # type: ignore
    except Exception:  # pragma: no cover
        logger = logging.getLogger("segyr.channels")
