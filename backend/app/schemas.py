"""Typed contracts between layers.

The critical schema is GenAIOutput: it is the only structure the language model
is permitted to return, and every zone reference inside it is validated against
the closed set supplied by the deterministic core.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class OpsStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    HOLD = "HOLD"
    SURGE = "SURGE"
    STATIC_QUEUE = "STATIC_QUEUE"
    SCANNER_FAILURE = "SCANNER_FAILURE"
    TRANSIT_DELAY = "TRANSIT_DELAY"
    CONGESTED = "CONGESTED"
    REROUTE = "REROUTE"
    HEAT_WARNING = "HEAT_WARNING"
    UNKNOWN = "UNKNOWN"


class CrowdMood(str, Enum):
    CALM = "calm"
    CONFUSED = "confused"
    FRUSTRATED = "frustrated"
    HOSTILE = "hostile"
    DISTRESSED = "distressed"
    EXHAUSTED = "exhausted"


class Phase(str, Enum):
    PRE_KICKOFF = "pre_kickoff"
    POST_MATCH = "post_match"


class Register(str, Enum):
    INFORMATIONAL = "informational"
    DE_ESCALATING = "de_escalating"
    WELFARE = "welfare"
    URGENT_CLEAR = "urgent_clear"


class OpsFeedEvent(BaseModel):
    """A broadcast from the operations command centre. This is the only external
    fact source; volunteers do not have sensors or camera feeds."""

    zone_id: str
    status: OpsStatus
    reason: str | None = None
    hold_time_min: int | None = Field(default=None, ge=0, le=600)
    reroute_to: str | None = None
    occupancy: int | None = Field(default=None, ge=0)


class VolunteerReport(BaseModel):
    """The three taps a volunteer can make while standing in a crowd."""

    venue_id: str
    zone_id: str
    issue: Literal[
        "line_static",
        "gate_closed",
        "lost_fans",
        "transit_delay",
        "fan_distress",
        "heat_distress",
        "out_of_scope_request",
        "no_information",
    ]
    crowd_mood: CrowdMood
    phase: Phase = Phase.PRE_KICKOFF
    static_for_min: int = Field(default=0, ge=0)


class DecisionFacts(BaseModel):
    """Resolved by deterministic code only. The model may not alter these."""

    venue_id: str
    venue_name: str
    origin_zone_id: str
    origin_zone_name: str
    status: OpsStatus
    severity: Literal["routine", "elevated", "critical"]
    sop_id: str
    sop_title: str
    objective: str
    allowed_zone_ids: list[str]
    recommended_zone_id: str | None = None
    recommended_zone_name: str | None = None
    walk_time_min: int | None = None
    welfare_zone_id: str | None = None
    medical_zone_id: str | None = None
    heat_active: bool = False
    escalate: bool = False
    escalate_reasons: list[str] = Field(default_factory=list)
    permitted_actions: list[str] = Field(default_factory=list)
    prohibited_actions: list[str] = Field(default_factory=list)
    register_mode: Register = Register.INFORMATIONAL


class Alternative(BaseModel):
    action: str
    tradeoff: str


class Announcement(BaseModel):
    lang: Literal["en", "es", "fr"]
    text: str


class GenAIOutput(BaseModel):
    """Strict output contract. Anything outside this shape is rejected."""

    recommendation: str
    rationale: list[str] = Field(min_length=1, max_length=5)
    confidence: Literal["low", "medium", "high"]
    alternatives: list[Alternative] = Field(default_factory=list, max_length=3)
    announcements: list[Announcement] = Field(min_length=1)
    referenced_zone_ids: list[str] = Field(default_factory=list)

    @field_validator("rationale")
    @classmethod
    def _no_empty_rationale(cls, v: list[str]) -> list[str]:
        if any(not s.strip() for s in v):
            raise ValueError("rationale entries must be non-empty")
        return v


class Citation(BaseModel):
    id: str
    title: str
    event: str
    venue: str
    date: str
    evidence_tier: str
    sources: list[dict[str, Any]]
    relevance: float


class DecisionResponse(BaseModel):
    facts: DecisionFacts
    output: GenAIOutput
    citations: list[Citation]
    engine: Literal["genai", "offline_template"]
    model: str | None = None
    latency_ms: int
    guard_violations: list[str] = Field(default_factory=list)
