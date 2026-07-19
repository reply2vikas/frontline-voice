"""Operational logging.

The audit log records what was decided; these tests assert that the reason for
every degradation is recorded too, so a credential fault, a timeout and a guard
rejection are distinguishable in the field rather than collapsing into one
silent fallback.
"""

import logging

import httpx
import pytest

from app import llm
from app.engine import decide
from app.logging_setup import configure_logging, get_logger
from app.schemas import OpsFeedEvent, VolunteerReport


@pytest.fixture(autouse=True)
def _capture_frontline(caplog):
    """Route the frontline logger into caplog.

    configure_logging sets propagate=False so that a host application configuring
    the root logger cannot duplicate our output. caplog captures at the root, so
    its handler must be attached to our logger directly for these assertions.
    """
    configure_logging()
    logger = logging.getLogger("frontline")
    logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        logger.removeHandler(caplog.handler)


@pytest.fixture
def facts():
    report = VolunteerReport(
        venue_id="MIA", zone_id="GATE_3", issue="gate_closed", crowd_mood="hostile"
    )
    return decide(report, [OpsFeedEvent(zone_id="GATE_3", status="CLOSED")])


def test_logger_is_namespaced():
    assert get_logger("unit").name == "frontline.unit"


def test_configure_logging_is_idempotent():
    """A second call must not replace handlers already installed.

    Handler identity is checked rather than count, because pytest attaches its
    own capture handlers to the same logger during a test run.
    """
    configure_logging()
    before = list(logging.getLogger("frontline").handlers)
    configure_logging()
    assert list(logging.getLogger("frontline").handlers) == before


def test_transport_failure_is_logged_with_cause(facts, monkeypatch, caplog):
    def boom(*_args, **_kwargs):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(llm.settings, "anthropic_api_key", "k", raising=False)
    monkeypatch.setattr(llm.httpx, "post", boom)
    with caplog.at_level(logging.WARNING, logger="frontline.llm"):
        _, engine, _, _, _ = llm.generate(facts, [])
    assert engine == "offline_template"
    assert any("falling back" in r.message for r in caplog.records)


def test_guard_rejection_is_logged_as_error(facts, monkeypatch, caplog):
    import json

    bad = {
        "recommendation": "Send everyone to GATE_99 now.",
        "rationale": ["x"],
        "confidence": "high",
        "alternatives": [],
        "announcements": [{"lang": "en", "text": "Go to GATE_99."}],
        "referenced_zone_ids": ["GATE_99"],
    }

    def fake_post(*_args, **_kwargs):
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": json.dumps(bad)}]},
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )

    monkeypatch.setattr(llm.settings, "anthropic_api_key", "k", raising=False)
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    with caplog.at_level(logging.ERROR, logger="frontline.llm"):
        _, engine, _, violations, _ = llm.generate(facts, [])
    assert engine == "offline_template"
    assert violations
    assert any("safety guard rejected" in r.message for r in caplog.records)


def test_missing_credential_does_not_log_a_warning(facts, monkeypatch, caplog):
    """Running without a key is a supported mode, not a fault."""
    monkeypatch.setattr(llm.settings, "anthropic_api_key", None, raising=False)
    with caplog.at_level(logging.WARNING, logger="frontline.llm"):
        _, engine, _, _, _ = llm.generate(facts, [])
    assert engine == "offline_template"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_escalation_is_logged(client, caplog):
    payload = {
        "report": {
            "venue_id": "MIA",
            "zone_id": "GATE_3",
            "issue": "gate_closed",
            "crowd_mood": "hostile",
            "static_for_min": 15,
        },
        "feed": [{"zone_id": "GATE_3", "status": "CLOSED"}],
    }
    with caplog.at_level(logging.INFO, logger="frontline.api"):
        assert client.post("/api/decide", json=payload).status_code == 200
    assert any("escalation" in r.message for r in caplog.records)


def test_logs_never_contain_credentials(facts, monkeypatch, caplog):
    monkeypatch.setattr(llm.settings, "anthropic_api_key", "secret-key-value", raising=False)
    monkeypatch.setattr(
        llm.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("x"))
    )
    with caplog.at_level(logging.DEBUG, logger="frontline.llm"):
        llm.generate(facts, [])
    assert not any("secret-key-value" in r.getMessage() for r in caplog.records)
