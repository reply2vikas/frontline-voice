"""Venue topology for FIFA World Cup 2026 host stadiums.

This is the authoritative, immutable set of zones. The language model is never
permitted to name a zone that does not appear here; the deterministic core
passes it a closed set of legal zone IDs and the safety guard rejects anything
else. That constraint is what makes hallucinated wayfinding structurally
impossible rather than merely unlikely.
"""

from __future__ import annotations

from typing import Literal

ZoneKind = Literal["gate", "transit", "welfare", "medical"]


class Zone:
    __slots__ = ("id", "name", "kind", "capacity", "walk_times", "step_free", "shaded")

    def __init__(
        self,
        id: str,
        name: str,
        kind: ZoneKind,
        capacity: int = 0,
        walk_times: dict[str, int] | None = None,
        step_free: bool = True,
        shaded: bool = False,
    ) -> None:
        self.id = id
        self.name = name
        self.kind = kind
        self.capacity = capacity
        self.walk_times = walk_times or {}
        self.step_free = step_free
        self.shaded = shaded

    def walk_time_to(self, other: str) -> int:
        """Walking minutes from this zone to another, defaulting to 8 when unmapped."""
        return self.walk_times.get(other, 8)


class Venue:
    def __init__(self, id: str, name: str, city: str, heat_risk: str, zones: list[Zone]) -> None:
        self.id = id
        self.name = name
        self.city = city
        self.heat_risk = heat_risk
        self.zones = {z.id: z for z in zones}

    def zone(self, zone_id: str) -> Zone | None:
        """Return a zone by id, or None when it does not exist at this venue."""
        return self.zones.get(zone_id)

    def gates(self) -> list[Zone]:
        """All entry gates at this venue."""
        return [z for z in self.zones.values() if z.kind == "gate"]

    def of_kind(self, kind: ZoneKind) -> list[Zone]:
        """All zones of a given kind (gate, transit, welfare, medical)."""
        return [z for z in self.zones.values() if z.kind == kind]


VENUES: dict[str, Venue] = {
    "MIA": Venue(
        id="MIA",
        name="Miami Stadium",
        city="Miami Gardens",
        heat_risk="extreme",
        zones=[
            Zone(
                "GATE_1", "Gate 1 (North)", "gate", 6000, {"GATE_2": 4, "GATE_3": 7, "GATE_4": 11}
            ),
            Zone("GATE_2", "Gate 2 (East)", "gate", 5000, {"GATE_1": 4, "GATE_3": 5, "GATE_4": 8}),
            Zone("GATE_3", "Gate 3 (South)", "gate", 5500, {"GATE_1": 7, "GATE_2": 5, "GATE_4": 5}),
            Zone("GATE_4", "Gate 4 (West)", "gate", 4500, {"GATE_1": 11, "GATE_2": 8, "GATE_3": 5}),
            Zone("TRANSIT_N", "North Shuttle Plaza", "transit", 9000, {"GATE_1": 5}),
            Zone("TRANSIT_S", "South Rideshare Pickup", "transit", 7000, {"GATE_3": 6}),
            Zone("WELFARE_A", "Shaded Rest Area A", "welfare", 800, {"GATE_2": 3}, shaded=True),
            Zone(
                "WELFARE_B", "Cooling & Water Point B", "welfare", 600, {"GATE_3": 4}, shaded=True
            ),
            Zone("QUIET_1", "Sensory Quiet Room", "welfare", 40, {"GATE_2": 6}, shaded=True),
            Zone("MEDICAL_1", "Medical Post 1", "medical", 60, {"GATE_1": 4, "GATE_3": 6}),
        ],
    ),
    "MEX": Venue(
        id="MEX",
        name="Mexico City Stadium",
        city="Mexico City",
        heat_risk="moderate",
        zones=[
            Zone("GATE_A", "Puerta A", "gate", 7000, {"GATE_B": 6, "GATE_C": 9}),
            Zone("GATE_B", "Puerta B", "gate", 6500, {"GATE_A": 6, "GATE_C": 5}),
            Zone("GATE_C", "Puerta C", "gate", 6000, {"GATE_A": 9, "GATE_B": 5}),
            Zone("TRANSIT_METRO", "Metro Concourse", "transit", 12000, {"GATE_A": 7}),
            Zone("WELFARE_C", "Shaded Rest Area", "welfare", 700, {"GATE_B": 4}, shaded=True),
            Zone("QUIET_2", "Sala Tranquila", "welfare", 35, {"GATE_B": 5}, shaded=True),
            Zone("MEDICAL_2", "Puesto Medico", "medical", 50, {"GATE_B": 3}),
        ],
    ),
    "NYNJ": Venue(
        id="NYNJ",
        name="New York New Jersey Stadium",
        city="East Rutherford",
        heat_risk="high",
        zones=[
            Zone("GATE_A", "Gate A", "gate", 8000, {"GATE_B": 6, "GATE_C": 10}),
            Zone("GATE_B", "Gate B", "gate", 7000, {"GATE_A": 6, "GATE_C": 6}),
            Zone("GATE_C", "Gate C", "gate", 6500, {"GATE_A": 10, "GATE_B": 6}),
            Zone("TRANSIT_RAIL", "Rail Station Plaza", "transit", 15000, {"GATE_A": 9}),
            Zone("TRANSIT_BUS", "Bus Lot", "transit", 8000, {"GATE_C": 7}),
            Zone("WELFARE_D", "Water & Shade Point", "welfare", 900, {"GATE_B": 3}, shaded=True),
            Zone("QUIET_3", "Quiet Space", "welfare", 30, {"GATE_B": 7}, shaded=True),
            Zone("MEDICAL_3", "Medical Post", "medical", 55, {"GATE_B": 4}),
        ],
    ),
}


def get_venue(venue_id: str) -> Venue | None:
    """Return a venue by id, or None when the id is unknown."""
    return VENUES.get(venue_id)


def legal_zone_ids(venue_id: str) -> set[str]:
    """Every zone id that exists at a venue; the closed set for safety checks."""
    v = get_venue(venue_id)
    return set(v.zones.keys()) if v else set()
