"""Corpus loading and precedent retrieval.

Retrieval is deterministic keyword-and-trigger scoring over 24 curated entries.
At this corpus size an embedding index adds dependency weight, install fragility
and repo size while measurably reducing nothing: exhaustive scoring of 12
precedents is O(12) and exact. The evaluation harness in tests pins hit-rate so
a regression is caught rather than assumed.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from .config import DATA_DIR

_TOKEN = re.compile(r"[a-z0-9_]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


@lru_cache(maxsize=1)
def load_precedents() -> list[dict[str, Any]]:
    with open(DATA_DIR / "precedent_corpus.json", encoding="utf-8") as fh:
        return json.load(fh)["precedents"]


@lru_cache(maxsize=1)
def load_sops() -> list[dict[str, Any]]:
    with open(DATA_DIR / "sop_corpus.json", encoding="utf-8") as fh:
        return json.load(fh)["sops"]


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    with open(DATA_DIR / "sop_corpus.json", encoding="utf-8") as fh:
        doc = json.load(fh)
    return {"hard_rules": doc["hard_rules"], "register_policy": doc["register_policy"]}


@lru_cache(maxsize=1)
def load_authority() -> dict[str, list[str]]:
    with open(DATA_DIR / "precedent_corpus.json", encoding="utf-8") as fh:
        doc = json.load(fh)
    ab = doc["authority_boundary"]
    return {"cannot": ab["volunteer_cannot"], "can": ab["volunteer_can"]}


def get_sop(sop_id: str) -> dict[str, Any] | None:
    return next((s for s in load_sops() if s["id"] == sop_id), None)


def score_precedent(p: dict[str, Any], status: str, mood: str, phase: str, extra: str = "") -> float:
    """Transparent additive scoring. Trigger matches dominate; free-text overlap
    breaks ties. Deliberately explainable so a low score can be justified."""
    trig = p.get("retrieval_triggers", {})
    score = 0.0
    if status in trig.get("status", []):
        score += 3.0
    if mood in trig.get("crowd_mood", []):
        score += 2.0
    if phase in trig.get("phase", []):
        score += 1.0
    if extra:
        blob = _tokens(
            " ".join([p.get("title", ""), p.get("what_happened", ""), " ".join(p.get("tags", []))])
        )
        overlap = len(blob & _tokens(extra))
        score += min(overlap * 0.25, 1.5)
    # The evidence bonus is a tie-breaker between relevant precedents, never a
    # reason to surface an irrelevant one. Applying it unconditionally caused
    # official reports to score above zero on queries they had no bearing on,
    # which would cite a crush report during a routine situation.
    if score > 0 and p.get("evidence_tier") == "official_report":
        score += 0.5
    return score


def retrieve(
    status: str, mood: str, phase: str, extra: str = "", k: int = 3
) -> list[tuple[dict[str, Any], float]]:
    scored = [(p, score_precedent(p, status, mood, phase, extra)) for p in load_precedents()]
    scored = [(p, s) for p, s in scored if s > 0]
    scored.sort(key=lambda t: (-t[1], t[0]["id"]))
    return scored[:k]
