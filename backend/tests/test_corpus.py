"""Corpus integrity and retrieval quality.

The retrieval hit-rate assertion is a CI gate: if scoring or triggers regress,
the build fails rather than the product silently citing the wrong precedent.
"""

import pytest

from app.corpus import load_authority, load_precedents, load_sops, retrieve, score_precedent

REQUIRED_PRECEDENT_FIELDS = [
    "id",
    "title",
    "event",
    "venue",
    "date",
    "category",
    "what_happened",
    "root_cause",
    "official_finding",
    "volunteer_relevance",
    "evidence_tier",
    "sources",
    "retrieval_triggers",
]


def test_corpora_load():
    assert len(load_precedents()) == 12
    assert len(load_sops()) == 12


@pytest.mark.parametrize("field", REQUIRED_PRECEDENT_FIELDS)
def test_every_precedent_has_required_field(field):
    assert all(p.get(field) for p in load_precedents())


def test_every_precedent_has_at_least_one_source_url():
    for p in load_precedents():
        assert p["sources"]
        assert all(s["url"].startswith("http") for s in p["sources"])


def test_evidence_tier_is_declared_and_valid():
    valid = {"official_report", "credible_reporting"}
    assert all(p["evidence_tier"] in valid for p in load_precedents())


def test_every_sop_derives_from_a_real_precedent():
    ids = {p["id"] for p in load_precedents()}
    for s in load_sops():
        assert s["derived_from"]
        assert set(s["derived_from"]) <= ids


def test_every_sop_declares_boundaries():
    for s in load_sops():
        assert s["volunteer_actions"] and s["do_not"] and s["escalate_if"]


def test_sop_actions_never_include_prohibited_verbs():
    """No SOP may instruct an action outside volunteer authority."""
    banned = ("unlock", "evacuate", "arrest", "detain")
    for s in load_sops():
        blob = " ".join(s["volunteer_actions"]).lower()
        assert not any(b in blob for b in banned), s["id"]


def test_authority_boundary_present():
    a = load_authority()
    assert a["can"] and a["cannot"]


# (query status, mood, phase, expected precedent id in top-3)
EVAL_CASES = [
    ("CLOSED", "hostile", "pre_kickoff", "PRE-001"),
    ("CLOSED", "frustrated", "pre_kickoff", "PRE-003"),
    ("STATIC_QUEUE", "pressing", "pre_kickoff", "PRE-005"),
    ("TRANSIT_DELAY", "frustrated", "post_match", "PRE-008"),
    ("TRANSIT_DELAY", "confused", "post_match", "PRE-009"),
    ("HEAT_WARNING", "exhausted", "pre_kickoff", "PRE-011"),
    ("HEAT_WARNING", "distressed", "post_match", "PRE-012"),
    ("SURGE", "frustrated", "pre_kickoff", "PRE-002"),
    ("REROUTE", "confused", "post_match", "PRE-007"),
    ("HOLD", "distrustful", "pre_kickoff", "PRE-006"),
    ("STATIC_QUEUE", "exhausted", "post_match", "PRE-010"),
    ("SURGE", "building", "pre_kickoff", "PRE-004"),
]


@pytest.mark.parametrize("status,mood,phase,expected", EVAL_CASES)
def test_retrieval_finds_expected_precedent(status, mood, phase, expected):
    assert expected in [p["id"] for p, _ in retrieve(status, mood, phase, k=3)]


def test_retrieval_hit_rate_gate():
    hits = sum(
        1 for s, m, ph, exp in EVAL_CASES if exp in [p["id"] for p, _ in retrieve(s, m, ph, k=3)]
    )
    rate = hits / len(EVAL_CASES)
    assert rate >= 0.85, f"retrieval hit-rate regressed to {rate:.0%}"


def test_official_reports_outrank_on_equal_triggers():
    """The evidence bonus breaks ties between relevant precedents only."""
    official = next(
        p
        for p in load_precedents()
        if p["evidence_tier"] == "official_report" and "CLOSED" in p["retrieval_triggers"]["status"]
    )
    reporting = next(p for p in load_precedents() if p["evidence_tier"] == "credible_reporting")
    assert score_precedent(official, "CLOSED", "none", "none") > 3.0
    assert score_precedent(reporting, "NONE", "none", "none") == 0.0


def test_irrelevant_query_returns_nothing():
    assert retrieve("NONE", "none", "none") == []
