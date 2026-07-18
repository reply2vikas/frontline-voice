"""Deterministic operations-feed simulator.

The tournament does not expose a public crowd feed, and volunteers have no
sensors, so live venue state is simulated. It is generated deterministically
from a seed and a time bucket rather than randomly: the same seed and minute
always produce the same state, which keeps the map, the telemetry strip and the
test suite in agreement, and lets an evaluator reproduce any screenshot exactly.

Evaluators who want to drive the product from their own data should post it to
/api/upload/feed instead; nothing here is used when a real feed is supplied.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from .schemas import OpsStatus
from .venues import Venue, get_venue

# Statuses a gate may hold, with the relative weight of each. Weighted so that a
# venue is mostly functional, which is what makes the exceptions legible.
GATE_STATES: list[tuple[OpsStatus, int]] = [
    (OpsStatus.OPEN, 55),
    (OpsStatus.CONGESTED, 20),
    (OpsStatus.STATIC_QUEUE, 10),
    (OpsStatus.SURGE, 7),
    (OpsStatus.SCANNER_FAILURE, 4),
    (OpsStatus.CLOSED, 4),
]

TRANSIT_STATES: list[tuple[OpsStatus, int]] = [
    (OpsStatus.OPEN, 65),
    (OpsStatus.CONGESTED, 22),
    (OpsStatus.TRANSIT_DELAY, 13),
]


def _hash_unit(*parts: str) -> float:
    """Stable pseudo-random value in [0, 1) derived from the given parts."""
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


def _weighted(choices: list[tuple[OpsStatus, int]], u: float) -> OpsStatus:
    total = sum(w for _, w in choices)
    cursor = u * total
    for status, weight in choices:
        cursor -= weight
        if cursor < 0:
            return status
    return choices[0][0]


def bucket(now: float | None = None, seconds: int = 45) -> int:
    """Time bucket. State advances on a fixed cadence so a demo visibly changes
    without flickering between renders."""
    return int((now if now is not None else time.time()) // seconds)


def venue_state(venue_id: str, now: float | None = None) -> dict[str, Any]:
    venue: Venue | None = get_venue(venue_id)
    if venue is None:
        raise ValueError(f"unknown venue: {venue_id}")

    b = str(bucket(now))
    zones: list[dict[str, Any]] = []
    for zone in venue.zones.values():
        if zone.kind == "gate":
            status = _weighted(GATE_STATES, _hash_unit(venue_id, zone.id, b))
        elif zone.kind == "transit":
            status = _weighted(TRANSIT_STATES, _hash_unit(venue_id, zone.id, b, "t"))
        else:
            status = OpsStatus.OPEN

        if zone.capacity:
            load = _hash_unit(venue_id, zone.id, b, "load")
            if status in (OpsStatus.SURGE, OpsStatus.STATIC_QUEUE, OpsStatus.CONGESTED):
                load = 0.72 + load * 0.27
            elif status == OpsStatus.CLOSED:
                load = 0.88 + load * 0.11
            else:
                load = load * 0.65
            occupancy = int(zone.capacity * load)
        else:
            occupancy = 0

        zones.append(
            {
                "id": zone.id,
                "name": zone.name,
                "kind": zone.kind,
                "status": status.value,
                "occupancy": occupancy,
                "capacity": zone.capacity,
                "load_pct": round(occupancy / zone.capacity * 100) if zone.capacity else 0,
                "step_free": zone.step_free,
                "shaded": zone.shaded,
            }
        )

    zones.sort(key=lambda z: (z["kind"], z["id"]))
    gates = [z for z in zones if z["kind"] == "gate"]
    return {
        "venue_id": venue.id,
        "venue_name": venue.name,
        "heat_risk": venue.heat_risk,
        "bucket": int(b),
        "simulated": True,
        "zones": zones,
        "summary": {
            "gates_total": len(gates),
            "gates_open": sum(1 for z in gates if z["status"] == OpsStatus.OPEN.value),
            "gates_impaired": sum(1 for z in gates if z["status"] != OpsStatus.OPEN.value),
            "peak_load_pct": max((z["load_pct"] for z in gates), default=0),
        },
    }


def feed_for(venue_id: str, now: float | None = None) -> list[dict[str, Any]]:
    """Venue state expressed as ops-feed events, for the decision endpoint."""
    return [
        {"zone_id": z["id"], "status": z["status"], "occupancy": z["occupancy"]}
        for z in venue_state(venue_id, now)["zones"]
        if z["kind"] in ("gate", "transit")
    ]
