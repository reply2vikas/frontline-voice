"""Authority-boundary and hallucination guard.

Two failure modes are unacceptable in a volunteer-facing tool:
  1. naming a gate, route or facility that does not exist, and
  2. recommending an action a volunteer has no authority to take.

Both are blocked structurally rather than by prompt instruction alone. The model
receives a closed set of legal zone IDs; anything outside it is stripped, and any
phrasing matching a prohibited-action pattern causes the response to be rejected
in favour of the deterministic template.
"""

from __future__ import annotations

import re

from .schemas import GenAIOutput

# Patterns describing actions outside volunteer authority. Matched against the
# generated recommendation and announcements, case-insensitively.
PROHIBITED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "directs people past a security or police line",
        re.compile(
            r"\b(push|move|go|walk|force|get)\b[^.]{0,40}\b(past|through|around)\b[^.]{0,30}\b(police|security|barrier|cordon|line)\b",
            re.I,
        ),
    ),
    # Requires a determiner between verb and noun so that descriptive adjectival
    # use ("the nearest open entrance") is not confused with an instruction
    # ("open the gate"). Caught by test_safety::test_open_entrance_is_not_a_violation.
    (
        "instructs opening or closing a gate",
        re.compile(
            r"\b(open|unlock|close|lock|shut)\s+(the|this|that|a|any|all|these|those)\s+\w*\s*(gate|turnstile|entrance|barrier|door)s?\b",
            re.I,
        ),
    ),
    (
        "orders an evacuation",
        re.compile(r"\b(evacuat\w+|clear the (stadium|venue|area) immediately)\b", re.I),
    ),
    (
        "directs the crowd toward a closed entry",
        re.compile(r"\b(proceed|continue|head|move)\b[^.]{0,30}\bto\b[^.]{0,25}\bclosed\b", re.I),
    ),
    (
        "issues a patronising calm-down command",
        re.compile(r"\b(calm down|calmense|cálmense|settle down|stop pushing)\b", re.I),
    ),
    ("blames the crowd", re.compile(r"\b(your fault|you are to blame|because of you all)\b", re.I)),
    (
        "makes a medical judgement",
        re.compile(
            r"\b(you are (not )?(having|experiencing) a|diagnos\w+|it'?s? just dehydration)\b",
            re.I,
        ),
    ),
]

ZONE_TOKEN = re.compile(r"\b(?:GATE|TRANSIT|WELFARE|MEDICAL|QUIET)_[A-Z0-9]+\b")


def find_illegal_zone_refs(output: GenAIOutput, allowed: set[str]) -> list[str]:
    """Any zone-shaped identifier appearing anywhere in the output must be in the
    closed set supplied by the deterministic core."""
    blob = " ".join(
        [
            output.recommendation,
            *output.rationale,
            *(a.text for a in output.announcements),
            *(a.action for a in output.alternatives),
            *output.referenced_zone_ids,
        ]
    )
    return sorted({m for m in ZONE_TOKEN.findall(blob) if m not in allowed})


def find_prohibited_actions(output: GenAIOutput) -> list[str]:
    """Return labels for any action the volunteer has no authority to take."""
    blob = " ".join(
        [
            output.recommendation,
            *output.rationale,
            *(a.text for a in output.announcements),
            *(a.action for a in output.alternatives),
        ]
    )
    return [label for label, pat in PROHIBITED_PATTERNS if pat.search(blob)]


def guard(output: GenAIOutput, allowed: set[str]) -> list[str]:
    """Returns a list of violations. Empty list means the output is safe to show."""
    violations = []
    for z in find_illegal_zone_refs(output, allowed):
        violations.append(f"illegal_zone_reference:{z}")
    for a in find_prohibited_actions(output):
        violations.append(f"prohibited_action:{a}")
    return violations


INJECTION_PATTERNS = [
    re.compile(r"ignore (all )?(previous|prior|above) instructions", re.I),
    re.compile(r"disregard (the )?(above|previous|system)", re.I),
    re.compile(r"(reveal|print|show|output).{0,20}(system prompt|instructions)", re.I),
    re.compile(r"<\|im_(start|end)\|>", re.I),
    re.compile(r"\byou are now\b.{0,30}\b(unrestricted|dan|jailbroken)\b", re.I),
    re.compile(r"\bnew (instructions|role|system)\s*:", re.I),
]


def sanitize_free_text(text: str) -> str:
    """Untrusted free text is wrapped as data, never merged into instructions.
    Recognised injection attempts are redacted before the text is embedded."""
    out = text
    for pat in INJECTION_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out
