"""Deterministic decision core.

Every fact in a recommendation is resolved here, in typed code, before any model
is consulted. The engine selects the governing SOP, computes the legal set of
destination zones from live venue state, decides severity and escalation, and
picks the register. The language model receives this as immutable input.

This split is what makes the system safe: a model failure can degrade the
wording of an announcement but can never change which gate a volunteer sends
four thousand people toward.
"""

from __future__ import annotations

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

BLOCKING_STATUSES = {OpsStatus.CLOSED, OpsStatus.HOLD, OpsStatus.SCANNER_FAILURE, OpsStatus.CONGESTED}


def select_sop_id(report: VolunteerReport, status: OpsStatus) -> str:
    """Volunteer-tapped issue wins when it names a specific human situation;
    otherwise the ops status governs. Hostility overrides both, because wording
    is the intervention in that case."""
    if report.issue in ("fan_distress", "out_of_scope_request", "no_information"):
        return ISSUE_SOP[report.issue]
    if report.crowd_mood == CrowdMood.HOSTILE:
        return "SOP-008"
    if status in STATUS_SOP:
        return STATUS_SOP[status]
    return ISSUE_SOP.get(report.issue, "SOP-010")


def _nearest(venue: Venue, origin: Zone, kind: str) -> Zone | None:
    candidates = venue.of_kind(kind)  # type: ignore[arg-type]
    if not candidates:
        return None
    return min(candidates, key=lambda z: origin.walk_time_to(z.id))


def compute_alternatives(
    venue: Venue, origin: Zone, feed: dict[str, OpsFeedEvent], phase: Phase
) -> list[Zone]:
    """Legal destinations: gates that are not blocked, ordered by walk time.
    During egress, transit zones become legal destinations too."""
    kinds = ["gate"] if phase == Phase.PRE_KICKOFF else ["gate", "transit"]
    out: list[Zone] = []
    for z in venue.zones.values():
        if z.kind not in kinds or z.id == origin.id:
            continue
        ev = feed.get(z.id)
        if ev and ev.status in BLOCKING_STATUSES:
            continue
        if ev and ev.occupancy and z.capacity and ev.occupancy / z.capacity >= settings.capacity_warn_ratio:
            continue
        out.append(z)
    out.sort(key=lambda z: origin.walk_time_to(z.id))
    return out


def decide(
    report: VolunteerReport,
    feed_events: list[OpsFeedEvent] | None = None,
    heat_warning: bool = False,
) -> DecisionFacts:
    venue = get_venue(report.venue_id)
    if venue is None:
        raise ValueError(f"unknown venue: {report.venue_id}")
    origin = venue.zone(report.zone_id)
    if origin is None:
        raise ValueError(f"unknown zone for venue {report.venue_id}: {report.zone_id}")

    feed = {e.zone_id: e for e in (feed_events or [])}
    origin_event = feed.get(origin.id)
    status = origin_event.status if origin_event else OpsStatus.OPEN

    heat_active = (
        heat_warning
        or any(e.status == OpsStatus.HEAT_WARNING for e in feed.values())
        or venue.heat_risk == "extreme"
    )

    sop_id = select_sop_id(report, status)
    sop = get_sop(sop_id) or get_sop("SOP-010")
    assert sop is not None

    alts = compute_alternatives(venue, origin, feed, report.phase)
    recommended = alts[0] if alts else None

    welfare = _nearest(venue, origin, "welfare")
    medical = _nearest(venue, origin, "medical")

    # Severity and escalation are threshold decisions, never model decisions.
    escalate_reasons: list[str] = []
    if report.static_for_min >= settings.static_queue_threshold_min:
        escalate_reasons.append(f"queue static for {report.static_for_min} min")
    if report.crowd_mood in (CrowdMood.HOSTILE, CrowdMood.DISTRESSED):
        escalate_reasons.append(f"crowd mood reported as {report.crowd_mood.value}")
    if status in BLOCKING_STATUSES and not alts:
        escalate_reasons.append("no legal alternative destination available")
    if report.issue == "out_of_scope_request":
        escalate_reasons.append("request exceeds volunteer authority")
    if heat_active and report.crowd_mood in (CrowdMood.EXHAUSTED, CrowdMood.DISTRESSED):
        escalate_reasons.append("heat load with distress present")

    if not escalate_reasons:
        severity = "routine"
    elif len(escalate_reasons) == 1 and report.static_for_min < settings.static_queue_threshold_min * 2:
        severity = "elevated"
    else:
        severity = "critical"

    register = MOOD_REGISTER.get(report.crowd_mood, Register.INFORMATIONAL)
    if heat_active and report.crowd_mood in (CrowdMood.EXHAUSTED, CrowdMood.DISTRESSED):
        register = Register.WELFARE
    if sop_id in ("SOP-005", "SOP-009"):
        register = Register.WELFARE

    allowed = {origin.id, *(z.id for z in alts)}
    if welfare:
        allowed.add(welfare.id)
    if medical:
        allowed.add(medical.id)

    return DecisionFacts(
        venue_id=venue.id,
        venue_name=venue.name,
        origin_zone_id=origin.id,
        origin_zone_name=origin.name,
        status=status,
        severity=severity,  # type: ignore[arg-type]
        sop_id=sop["id"],
        sop_title=sop["title"],
        objective=sop["objective"],
        allowed_zone_ids=sorted(allowed),
        recommended_zone_id=recommended.id if recommended else None,
        recommended_zone_name=recommended.name if recommended else None,
        walk_time_min=origin.walk_time_to(recommended.id) if recommended else None,
        welfare_zone_id=welfare.id if welfare else None,
        medical_zone_id=medical.id if medical else None,
        heat_active=heat_active,
        escalate=bool(escalate_reasons),
        escalate_reasons=escalate_reasons,
        permitted_actions=sop["volunteer_actions"],
        prohibited_actions=sop["do_not"],
        register_mode=register,
    )
