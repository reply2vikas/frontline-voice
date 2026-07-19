"""Structured operational logging.

The audit log records what was decided; this records what happened while
deciding. A safety-critical tool that silently swallows a credential error, a
timeout and a malformed model response into the same fallback is impossible to
diagnose in the field, so every degradation path is recorded with its cause.

Logs carry no volunteer free text or credentials — only operational facts.
"""

from __future__ import annotations

import logging
import sys

from .config import settings

_CONFIGURED = False


def configure_logging() -> None:
    """Install a single stream handler. Safe to call more than once."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s"))
    root = logging.getLogger("frontline")
    root.setLevel(settings.log_level.upper())
    root.handlers = [handler]
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, configuring the tree on first use."""
    configure_logging()
    return logging.getLogger(f"frontline.{name}")
