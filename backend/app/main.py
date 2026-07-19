"""FastAPI application.

Endpoints are deliberately few. The product is one decision loop, exposed
cleanly, plus the harness an evaluator needs to run it on their own data.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from . import audit
from .config import settings
from .corpus import load_precedents, load_sops, retrieve
from .engine import decide
from .llm import generate
from .schemas import Citation, DecisionResponse, OpsFeedEvent, VolunteerReport
from .simulator import feed_for, venue_state
from .venues import VENUES, get_venue

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach hardening headers to every response."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001 - signature required by FastAPI
    audit.init_db()
    yield


app = FastAPI(
    title="Micro-Megaphone",
    version="1.0.0",
    description="Crowd de-escalation copilot for last-mile volunteers, FIFA World Cup 2026.",
    lifespan=lifespan,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class DecideRequest(BaseModel):
    """One volunteer report plus any operations feed to reason over."""

    report: VolunteerReport
    feed: list[OpsFeedEvent] = Field(default_factory=list)
    free_text: str = ""
    heat_warning: bool = False


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Report service status and which engine will answer a request."""
    return {
        "status": "ok",
        "genai_configured": bool(settings.anthropic_api_key),
        "engine_if_called": "genai" if settings.anthropic_api_key else "offline_template",
        "precedents": len(load_precedents()),
        "sops": len(load_sops()),
    }


@app.get("/api/venues")
def venues() -> list[dict[str, Any]]:
    """Return the venue topology used by the map and the location picker."""
    return [
        {
            "id": v.id,
            "name": v.name,
            "city": v.city,
            "heat_risk": v.heat_risk,
            "zones": [{"id": z.id, "name": z.name, "kind": z.kind} for z in v.zones.values()],
        }
        for v in VENUES.values()
    ]


def _to_citations(hits: list[tuple[dict[str, Any], float]]) -> list[Citation]:
    return [
        Citation(
            id=p["id"],
            title=p["title"],
            event=p["event"],
            venue=p["venue"],
            date=p["date"],
            evidence_tier=p["evidence_tier"],
            sources=p["sources"],
            relevance=round(score, 2),
        )
        for p, score in hits
    ]


@app.post("/api/decide", response_model=DecisionResponse)
def decide_endpoint(req: DecideRequest) -> DecisionResponse:
    """Resolve facts deterministically, ground them, phrase them, and log them."""
    try:
        facts = decide(req.report, req.feed, heat_warning=req.heat_warning)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    hits = retrieve(
        facts.status.value, req.report.crowd_mood.value, req.report.phase.value, req.free_text
    )
    output, engine, model, violations, ms = generate(facts, [p for p, _ in hits], req.free_text)

    response = DecisionResponse(
        facts=facts,
        output=output,
        citations=_to_citations(hits),
        engine=engine,
        model=model,
        latency_ms=ms,
        guard_violations=violations,
    )
    audit.record(response)
    return response


@app.get("/api/venue-state/{venue_id}")
def venue_state_endpoint(venue_id: str) -> dict[str, Any]:
    """Simulated live operations feed, used by the map and telemetry views."""
    try:
        return venue_state(venue_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/venue-feed/{venue_id}")
def venue_feed_endpoint(venue_id: str) -> list[dict[str, Any]]:
    """Return the simulated feed as ops events for the decision endpoint."""
    try:
        return feed_for(venue_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/upload/feed")
def upload_feed(events: list[OpsFeedEvent]) -> dict[str, Any]:
    """Evaluator harness: accept an operations feed and report what the
    deterministic core makes of it, without requiring any credentials."""
    known: list[OpsFeedEvent] = []
    unknown: list[str] = []
    for e in events:
        if any(get_venue(v) and get_venue(v).zone(e.zone_id) for v in VENUES):  # type: ignore[union-attr]
            known.append(e)
        else:
            unknown.append(e.zone_id)
    return {
        "accepted": len(known),
        "rejected_unknown_zones": unknown,
        "statuses": {e.zone_id: e.status.value for e in known},
    }


@app.get("/api/audit")
def audit_log(limit: int = 25) -> list[dict[str, Any]]:
    """Return the most recent recorded decisions."""
    return audit.recent(limit)


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        """Serve the single-page volunteer interface."""
        return FileResponse(STATIC_DIR / "index.html")
