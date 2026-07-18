"""Application configuration.

Every credential is optional by design: the copilot must run end to end with no
API key at all, falling back to the deterministic template engine. A missing key
degrades output quality, never availability.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class Settings:
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"
    db_path: str = "audit.db"
    static_queue_threshold_min: int = 12
    capacity_warn_ratio: float = 0.80

    @classmethod
    def load(cls) -> Settings:
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
            db_path=os.getenv("DB_PATH", "audit.db"),
        )


settings = Settings.load()
