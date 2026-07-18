"""Deterministic core behaviour, including boundary and degenerate inputs."""

import pytest

from app.engine import compute_alternatives, decide, select_sop_id
from app.schemas import OpsFeedEvent, OpsStatus, Phase, Register, VolunteerReport
from app.venues import get_venue


def report(**kw):
    base = {"venue_id": "MIA", "zone_id": "GATE_3", "issue": "gate_closed", "crowd_mood": "calm"}
    base.update(kw)
    return VolunteerReport(**base)


def test_closed_gate_recommends_nearest_open_gate():
    facts = decide(report(), [OpsFeedEvent(zone_id="GATE_3", status=OpsStatus.CLOSED)])
    assert facts.recommended_zone_id == "GATE_2"
    assert facts.walk_time_min == 5


def test_blocked_alternatives_are_excluded():
    feed = [
        OpsFeedEvent(zone_id="GATE_3", status=OpsStatus.CLOSED),
        OpsFeedEvent(zone_id="GATE_2", status=OpsStatus.CLOSED),
        OpsFeedEvent(zone_id="GATE_1", status=OpsStatus.HOLD),
    ]
    facts = decide(report(), feed)
    assert facts.recommended_zone_id == "GATE_4"


def test_zone_over_capacity_threshold_is_excluded():
    feed = [
        OpsFeedEvent(zone_id="GATE_3", status=OpsStatus.CLOSED),
        OpsFeedEvent(zone_id="GATE_2", status=OpsStatus.OPEN, occupancy=4900),  # 98% of 5000
    ]
    facts = decide(report(), feed)
    assert facts.recommended_zone_id != "GATE_2"


def test_no_alternatives_available_escalates_and_recommends_hold():
    feed = [
        OpsFeedEvent(zone_id=z, status=OpsStatus.CLOSED) for z in ("GATE_1", "GATE_2", "GATE_3", "GATE_4")
    ]
    facts = decide(report(), feed)
    assert facts.recommended_zone_id is None
    assert facts.escalate
    assert "no legal alternative destination available" in facts.escalate_reasons


def test_hostile_mood_selects_de_escalation_sop_and_register():
    facts = decide(report(crowd_mood="hostile"), [])
    assert facts.sop_id == "SOP-008"
    assert facts.register_mode == Register.DE_ESCALATING


def test_out_of_scope_request_always_escalates():
    facts = decide(report(issue="out_of_scope_request"), [])
    assert facts.sop_id == "SOP-012"
    assert facts.escalate


def test_static_queue_threshold_triggers_escalation():
    below = decide(report(static_for_min=5), [])
    above = decide(report(static_for_min=20), [])
    assert not any("static" in r for r in below.escalate_reasons)
    assert any("static" in r for r in above.escalate_reasons)


def test_extreme_heat_venue_activates_welfare_defaults():
    facts = decide(report(crowd_mood="exhausted"), [])
    assert facts.heat_active
    assert facts.register_mode == Register.WELFARE


def test_egress_phase_allows_transit_destinations():
    venue = get_venue("MIA")
    origin = venue.zone("GATE_3")
    pre = compute_alternatives(venue, origin, {}, Phase.PRE_KICKOFF)
    post = compute_alternatives(venue, origin, {}, Phase.POST_MATCH)
    assert all(z.kind == "gate" for z in pre)
    assert any(z.kind == "transit" for z in post)


def test_allowed_zone_set_always_contains_origin_welfare_and_medical():
    facts = decide(report(), [])
    assert facts.origin_zone_id in facts.allowed_zone_ids
    assert facts.welfare_zone_id in facts.allowed_zone_ids
    assert facts.medical_zone_id in facts.allowed_zone_ids


@pytest.mark.parametrize("venue,zone", [("NOPE", "GATE_1"), ("MIA", "GATE_999")])
def test_unknown_venue_or_zone_raises(venue, zone):
    with pytest.raises(ValueError):
        decide(report(venue_id=venue, zone_id=zone), [])


def test_empty_feed_defaults_to_open_status():
    assert decide(report(), []).status == OpsStatus.OPEN


def test_unknown_status_routes_to_no_information_sop():
    facts = decide(report(issue="no_information"), [OpsFeedEvent(zone_id="GATE_3", status=OpsStatus.UNKNOWN)])
    assert facts.sop_id == "SOP-011"


def test_sop_selection_prefers_human_situation_over_status():
    assert select_sop_id(report(issue="fan_distress", crowd_mood="hostile"), OpsStatus.SURGE) == "SOP-009"
