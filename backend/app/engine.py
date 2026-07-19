"""Deterministic decision core.

Every fact in a recommendation is resolved here, in typed code, before any model
is consulted. The engine selects the governing SOP, computes the legal set of
destination zones from live venue state, decides severity and escalation, and
picks the register. The language model receives this as immutable input.

This split is what makes the system safe: a model failure can degrade the
wording of an announcement but can never change which gate a volunteer sends
four thousand people toward.

The module is organised as small single-purpose resolvers composed by `decide`,
so that each rule can be read, tested and changed in isolation.
"""

from __future__ import annotations

from typing import Any

from .config import settings
from .corpus import get_sop
from .schemas import (
    CrowdMood,
    DecisionFacts,
    OpsFeedEvent,
    OpsStatus,
    Phase,
    Register,
    VolunteerReport,
)
from .venues import Venue, Zone, get_venue

# Maps the volunteer's tapped issue plus the ops status onto a governing SOP.
ISSUE_SOP: dict[str, str] = {
    "gate_closed": "SOP-001",
    "line_static": "SOP-004",
    "transit_delay": "SOP-006",
    "lost_fans": "SOP-007",
    "fan_distress": "SOP-009",
    "heat_distress": "SOP-005",
    "out_of_scope_request": "SOP-012",
    "no_information": "SOP-011",
}

STATUS_SOP: dict[OpsStatus, str] = {
    OpsStatus.SCANNER_FAILURE: "SOP-002",
    OpsStatus.SURGE: "SOP-003",
    OpsStatus.HEAT_WARNING: "SOP-005",
    OpsStatus.TRANSIT_DELAY: "SOP-006",
    OpsStatus.UNKNOWN: "SOP-011",
}

MOOD_REGISTER: dict[CrowdMood, Register] = {
    CrowdMood.CALM: Register.INFORMATIONAL,
    CrowdMood.CONFUSED: Register.INFORMATIONAL,
    CrowdMood.FRUSTRATED: Register.DE_ESCALATING,
    CrowdMood.HOSTILE: Register.DE_ESCALATING,
    CrowdMood.DISTRESSED: Register.WELFARE,
    CrowdMood.EXHAUSTED: Register.WELFARE,
}

BLOCKING_STATUSES = frozenset(
    {OpsStatus.CLOSED, OpsStatus.HOLD, OpsStatus.SCANNER_FAILURE, OpsStatus.CONGESTED}
)

HUMAN_SITUATION_ISSUES = frozenset({"fan_distress", "out_of_scope_request", "no_information"})
WELFARE_SOPS = frozenset({"SOP-005", "SOP-009"})
HIGH_CONCERN_MOODS = frozenset({CrowdMood.HOSTILE, CrowdMood.DISTRESSED})
HEAT_SENSITIVE_MOODS = frozenset({CrowdMood.EXHAUSTED, CrowdMood.DISTRESSED})


def select_sop_id(report: VolunteerReport, status: OpsStatus) -> str:
    """Volunteer-tapped issue wins when it names a specific human situation;
    otherwise the ops status governs. Hostility overrides both, because wording
    is the intervention in that case."""
    if report.issue in HUMAN_SITUATION_ISSUES:
        return ISSUE_SOP[report.issue]
    if report.crowd_mood is CrowdMood.HOSTILE:
        return "SOP-008"
    if status in STATUS_SOP:
        return STATUS_SOP[status]
    return ISSUE_SOP.get(report.issue, "SOP-010")


def _nearest(venue: Venue, origin: Zone, kind: str) -> Zone | None:
    candidates = venue.of_kind(kind)  # type: ignore[arg-type]
    if not candidates:
        return None
    return min(candidates, key=lambda z: origin.walk_time_to(z.id))


def _destination_kinds(phase: Phase) -> tuple[str, ...]:
    """During egress, transit hubs become legal destinations alongside gates."""
    return ("gate",) if phase is Phase.PRE_KICKOFF else ("gate", "transit")


def _is_available(zone: Zone, event: OpsFeedEvent | None) -> bool:
    """A destination is legal only if it is neither blocked nor near capacity."""
    if event is None:
        return True
    if event.status in BLOCKING_STATUSES:
        return False
    if not (event.occupancy and zone.capacity):
        return True
    return event.occupancy / zone.capacity < settings.capacity_warn_ratio


def compute_alternatives(
    venue: Venue, origin: Zone, feed: dict[str, OpsFeedEvent], phase: Phase
) -> list[Zone]:
    """Legal destinations, ordered by walking time from the volunteer."""
    kinds = _destination_kinds(phase)
    candidates = [
        zone
        for zone in venue.zones.values()
        if zone.kind in kinds and zone.id != origin.id and _is_available(zone, feed.get(zone.id))
    ]
    return sorted(candidates, key=lambda z: origin.walk_time_to(z.id))


def _resolve_status(origin: Zone, feed: dict[str, OpsFeedEvent]) -> OpsStatus:
    event = feed.get(origin.id)
    return event.status if event else OpsStatus.OPEN


def _heat_is_active(venue: Venue, feed: dict[str, OpsFeedEvent], declared: bool) -> bool:
    """Heat converts an ordinary delay into a welfare situation, so it is treated
    as active whenever the venue, the feed, or the caller says so."""
    return (
        declared
        or venue.heat_risk == "extreme"
        or any(e.status is OpsStatus.HEAT_WARNING for e in feed.values())
    )


def _escalation_reasons(
    report: VolunteerReport, status: OpsStatus, alternatives: list[Zone], heat_active: bool
) -> list[str]:
    """Escalation is threshold-driven and never a model decision."""
    reasons: list[str] = []
    if report.static_for_min >= settings.static_queue_threshold_min:
        reasons.append(f"queue static for {report.static_for_min} min")
    if report.crowd_mood in HIGH_CONCERN_MOODS:
        reasons.append(f"crowd mood reported as {report.crowd_mood.value}")
    if status in BLOCKING_STATUSES and not alternatives:
        reasons.append("no legal alternative destination available")
    if report.issue == "out_of_scope_request":
        reasons.append("request exceeds volunteer authority")
    if heat_active and report.crowd_mood in HEAT_SENSITIVE_MOODS:
        reasons.append("heat load with distress present")
    return reasons


def _grade_severity(reasons: list[str], static_for_min: int) -> str:
    if not reasons:
        return "routine"
    if len(reasons) == 1 and static_for_min < settings.static_queue_threshold_min * 2:
        return "elevated"
    return "critical"


def _select_register(report: VolunteerReport, sop_id: str, heat_active: bool) -> Register:
    """Welfare procedures and heat-affected crowds always take welfare phrasing."""
    if sop_id in WELFARE_SOPS:
        return Register.WELFARE
    if heat_active and report.crowd_mood in HEAT_SENSITIVE_MOODS:
        return Register.WELFARE
    return MOOD_REGISTER.get(report.crowd_mood, Register.INFORMATIONAL)


def _allowed_zone_ids(origin: Zone, alternatives: list[Zone], *support: Zone | None) -> list[str]:
    """The closed set the language model may reference. Nothing outside it can
    reach a volunteer; see safety.find_illegal_zone_refs."""
    ids = {origin.id, *(z.id for z in alternatives)}
    ids.update(z.id for z in support if z is not None)
    return sorted(ids)


def _locate(report: VolunteerReport) -> tuple[Venue, Zone]:
    venue = get_venue(report.venue_id)
    if venue is None:
        raise ValueError(f"unknown venue: {report.venue_id}")
    origin = venue.zone(report.zone_id)
    if origin is None:
        raise ValueError(f"unknown zone for venue {report.venue_id}: {report.zone_id}")
    return venue, origin


def _assemble(
    venue: Venue,
    origin: Zone,
    report: VolunteerReport,
    sop: dict[str, Any],
    status: OpsStatus,
    alternatives: list[Zone],
    welfare: Zone | None,
    medical: Zone | None,
    heat_active: bool,
    reasons: list[str],
) -> DecisionFacts:
    """Assemble the immutable fact set handed to the generation layer."""
    recommended = alternatives[0] if alternatives else None
    return DecisionFacts(
        venue_id=venue.id,
        venue_name=venue.name,
        origin_zone_id=origin.id,
        origin_zone_name=origin.name,
        status=status,
        severity=_grade_severity(reasons, report.static_for_min),  # type: ignore[arg-type]
        sop_id=sop["id"],
        sop_title=sop["title"],
        objective=sop["objective"],
        allowed_zone_ids=_allowed_zone_ids(origin, alternatives, welfare, medical),
        recommended_zone_id=recommended.id if recommended else None,
        recommended_zone_name=recommended.name if recommended else None,
        walk_time_min=origin.walk_time_to(recommended.id) if recommended else None,
        welfare_zone_id=welfare.id if welfare else None,
        medical_zone_id=medical.id if medical else None,
        heat_active=heat_active,
        escalate=bool(reasons),
        escalate_reasons=reasons,
        permitted_actions=sop["volunteer_actions"],
        prohibited_actions=sop["do_not"],
        register_mode=_select_register(report, sop["id"], heat_active),
    )


def decide(
    report: VolunteerReport,
    feed_events: list[OpsFeedEvent] | None = None,
    heat_warning: bool = False,
) -> DecisionFacts:
    """Resolve every operational fact for one volunteer report.

    Raises ValueError if the venue or zone is unknown, so an invalid location can
    never reach the generation layer.
    """
    venue, origin = _locate(report)
    feed = {e.zone_id: e for e in (feed_events or [])}

    status = _resolve_status(origin, feed)
    heat_active = _heat_is_active(venue, feed, heat_warning)
    alternatives = compute_alternatives(venue, origin, feed, report.phase)
    sop = get_sop(select_sop_id(report, status)) or get_sop("SOP-010")
    if sop is None:  # pragma: no cover - SOP-010 is present in the shipped corpus
        raise RuntimeError("SOP corpus is missing the SOP-010 fallback procedure")

    return _assemble(
        venue=venue,
        origin=origin,
        report=report,
        sop=sop,
        status=status,
        alternatives=alternatives,
        welfare=_nearest(venue, origin, "welfare"),
        medical=_nearest(venue, origin, "medical"),
        heat_active=heat_active,
        reasons=_escalation_reasons(report, status, alternatives, heat_active),
    )
