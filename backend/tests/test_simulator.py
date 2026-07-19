"""Simulated operations feed: determinism, bounds, and shape."""

import pytest

from app.schemas import OpsStatus
from app.simulator import bucket, feed_for, venue_state

VALID = {s.value for s in OpsStatus}


def test_same_bucket_yields_identical_state():
    assert venue_state("MIA", now=1_000_000) == venue_state("MIA", now=1_000_030)


def test_state_advances_across_buckets():
    assert venue_state("MIA", now=1_000_000) != venue_state("MIA", now=1_000_500)


def test_bucket_is_monotonic():
    assert bucket(now=1_000_000) < bucket(now=1_000_500)


@pytest.mark.parametrize("venue_id", ["MIA", "MEX", "NYNJ"])
def test_every_venue_produces_a_complete_state(venue_id):
    s = venue_state(venue_id, now=42)
    assert s["venue_id"] == venue_id
    assert s["simulated"] is True
    assert s["zones"]
    assert all(z["status"] in VALID for z in s["zones"])


def test_load_percentage_is_bounded():
    for z in venue_state("MIA", now=7)["zones"]:
        assert 0 <= z["load_pct"] <= 100
        assert z["occupancy"] <= z["capacity"] or z["capacity"] == 0


def test_non_operational_zones_are_always_open():
    for z in venue_state("MIA", now=11)["zones"]:
        if z["kind"] in ("welfare", "medical"):
            assert z["status"] == OpsStatus.OPEN.value


def test_summary_is_internally_consistent():
    s = venue_state("NYNJ", now=99)["summary"]
    assert s["gates_open"] + s["gates_impaired"] == s["gates_total"]
    assert 0 <= s["peak_load_pct"] <= 100


def test_feed_contains_only_operational_zones():
    feed = feed_for("MIA", now=3)
    kinds = {
        z["id"] for z in venue_state("MIA", now=3)["zones"] if z["kind"] in ("gate", "transit")
    }
    assert {e["zone_id"] for e in feed} == kinds


def test_feed_events_validate_against_the_ops_schema():
    from app.schemas import OpsFeedEvent

    for e in feed_for("MEX", now=5):
        OpsFeedEvent.model_validate(e)


def test_unknown_venue_raises():
    with pytest.raises(ValueError):
        venue_state("NOPE")


def test_simulated_feed_drives_a_real_decision():
    """The simulator must produce state the deterministic core can act on."""
    from app.engine import decide
    from app.schemas import OpsFeedEvent, VolunteerReport

    events = [OpsFeedEvent.model_validate(e) for e in feed_for("MIA", now=13)]
    facts = decide(
        VolunteerReport(
            venue_id="MIA", zone_id="GATE_1", issue="gate_closed", crowd_mood="frustrated"
        ),
        events,
    )
    assert facts.sop_id
    assert set(facts.allowed_zone_ids) <= {z["id"] for z in venue_state("MIA", now=13)["zones"]}
