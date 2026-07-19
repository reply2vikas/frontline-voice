"""Append-only decision log.

Accountability is a product requirement for an operations tool: every
recommendation shown to a volunteer must be reconstructable afterwards, with the
inputs that produced it and the engine that phrased it.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    venue_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    status TEXT NOT NULL,
    sop_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    engine TEXT NOT NULL,
    model TEXT,
    confidence TEXT NOT NULL,
    escalated INTEGER NOT NULL,
    guard_violations TEXT NOT NULL,
    citations TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
"""


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    """Opens a connection and guarantees the schema exists.

    Applying the schema on every connect is idempotent and removes any dependency
    on application startup ordering, which matters on platforms that may serve a
    request against a cold, ephemeral filesystem."""
    conn = sqlite3.connect(db_path or settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def init_db(db_path: str | None = None) -> None:
    """Create the decisions table if it does not yet exist."""
    with closing(_connect(db_path)) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def record(response: Any, db_path: str | None = None) -> int:
    """Append one decision to the audit log and return its row id."""
    with closing(_connect(db_path)) as conn:
        cur = conn.execute(
            """INSERT INTO decisions
               (ts, venue_id, zone_id, status, sop_id, severity, engine, model,
                confidence, escalated, guard_violations, citations, payload)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(UTC).isoformat(),
                response.facts.venue_id,
                response.facts.origin_zone_id,
                response.facts.status.value,
                response.facts.sop_id,
                response.facts.severity,
                response.engine,
                response.model,
                response.output.confidence,
                int(response.facts.escalate),
                json.dumps(response.guard_violations),
                json.dumps([c.id for c in response.citations]),
                response.model_dump_json(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


def recent(limit: int = 25, db_path: str | None = None) -> list[dict[str, Any]]:
    """Return the most recent decisions, newest first."""
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            """SELECT id, ts, venue_id, zone_id, status, sop_id, severity,
                      engine, model, confidence, escalated, guard_violations, citations
               FROM decisions ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
