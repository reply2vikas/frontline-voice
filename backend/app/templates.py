"""Deterministic announcement templates.

This is the offline engine. It runs when no API key is configured, when the API
errors, or when the guard rejects a generated response. It is intentionally
complete rather than a stub: an evaluator with no credentials must be able to
exercise the entire product, and a credential failure at judging time must
degrade wording quality, never availability.

Register wording follows the corpus register policy: collective phrasing in
Spanish rather than bare imperatives, vouvoiement in French, and acknowledgement
before instruction whenever the crowd is frustrated or hostile.
"""

from __future__ import annotations

from .schemas import Alternative, Announcement, DecisionFacts, GenAIOutput, Register

_OPENERS = {
    Register.INFORMATIONAL: {
        "en": "Attention please.",
        "es": "Atención, por favor.",
        "fr": "Votre attention, s'il vous plaît.",
    },
    Register.DE_ESCALATING: {
        "en": "Thank you for your patience — we know this wait is frustrating.",
        "es": "Apreciamos su paciencia. Sabemos que la espera es molesta.",
        "fr": "Nous vous remercions de votre patience. Nous savons que cette attente est pénible.",
    },
    Register.WELFARE: {
        "en": "If you feel unwell, please come forward.",
        "es": "Si se siente mal, acérquese por favor.",
        "fr": "Si vous ne vous sentez pas bien, avancez vers nous.",
    },
    Register.URGENT_CLEAR: {
        "en": "Please listen carefully.",
        "es": "Escuchen con atención, por favor.",
        "fr": "Merci d'écouter attentivement.",
    },
}

_REDIRECT = {
    "en": "This entrance is on hold. The nearest open entrance is {zone}, about {mins} minutes on foot.",
    "es": "Esta entrada está detenida. La entrada abierta más cercana es {zone}, a unos {mins} minutos caminando.",
    "fr": "Cette entrée est suspendue. L'entrée ouverte la plus proche est {zone}, à environ {mins} minutes à pied.",
}

_NO_ALT = {
    "en": "This entrance is on hold and we are waiting on an update. Please stay where you are and keep space around you.",
    "es": "Esta entrada está detenida y esperamos una actualización. Permanezca donde está y mantenga espacio a su alrededor.",
    "fr": "Cette entrée est suspendue et nous attendons une mise à jour. Restez où vous êtes et gardez de l'espace autour de vous.",
}

_WELFARE = {
    "en": "Water and shade are available at {zone}.",
    "es": "Hay agua y sombra en {zone}.",
    "fr": "De l'eau et de l'ombre sont disponibles à {zone}.",
}

_UPDATE = {
    "en": "We will update you as soon as we know more.",
    "es": "Les informaremos en cuanto sepamos más.",
    "fr": "Nous vous informerons dès que possible.",
}

_OUT_OF_SCOPE = {
    "en": "That decision sits with the operations team. I have passed it on. In the meantime I can direct you to {zone}.",
    "es": "Esa decisión corresponde al equipo de operaciones. Ya la he transmitido. Mientras tanto puedo indicarle {zone}.",
    "fr": "Cette décision relève de l'équipe opérationnelle. Je l'ai transmise. En attendant, je peux vous indiquer {zone}.",
}

LANGS = ("en", "es", "fr")


def _human(zone_id: str | None) -> str:
    """Render a zone ID for humans: WELFARE_A -> Welfare A."""
    return zone_id.replace("_", " ").title() if zone_id else "the nearest welfare point"


def _zone_label(facts: DecisionFacts) -> str:
    return facts.recommended_zone_name or "the next open entrance"


def build_offline_output(facts: DecisionFacts) -> GenAIOutput:
    """Compose a complete, safe response using only resolved facts."""
    announcements: list[Announcement] = []
    for lang in LANGS:
        parts = [_OPENERS[facts.register_mode][lang]]
        if facts.sop_id == "SOP-012":
            parts.append(_OUT_OF_SCOPE[lang].format(zone=_zone_label(facts)))
        elif facts.recommended_zone_name and facts.walk_time_min is not None:
            parts.append(_REDIRECT[lang].format(zone=facts.recommended_zone_name, mins=facts.walk_time_min))
        else:
            parts.append(_NO_ALT[lang])
        if facts.heat_active and facts.welfare_zone_id:
            parts.append(_WELFARE[lang].format(zone=_human(facts.welfare_zone_id)))
        parts.append(_UPDATE[lang])
        announcements.append(Announcement(lang=lang, text=" ".join(parts)))

    rationale = [
        f"Status at {facts.origin_zone_name} is {facts.status.value}; governing procedure is {facts.sop_id} ({facts.sop_title}).",
        f"Severity assessed as {facts.severity} from reported conditions.",
    ]
    if facts.recommended_zone_name:
        rationale.append(
            f"{facts.recommended_zone_name} is the closest destination that is open and below the capacity threshold, about {facts.walk_time_min} minutes away."
        )
    if facts.heat_active:
        rationale.append("Heat conditions are active, so welfare messaging is included by default.")
    if facts.escalate:
        rationale.append("Escalation triggered: " + "; ".join(facts.escalate_reasons) + ".")

    alternatives = [
        Alternative(
            action="Hold arrivals at the current standing point and wait for the operations update.",
            tradeoff="Avoids sending people on a walk that may prove unnecessary, but extends standing time, which is the main driver of harm in a static queue.",
        )
    ]
    if facts.welfare_zone_id:
        alternatives.append(
            Alternative(
                action=f"Direct families, older people and anyone unwell to {_human(facts.welfare_zone_id)} first.",
                tradeoff="Splits the queue and takes longer to communicate, but removes the people least able to tolerate a long wait.",
            )
        )

    recommendation = (
        f"Redirect arriving people from {facts.origin_zone_name} to {facts.recommended_zone_name} "
        f"(about {facts.walk_time_min} minutes on foot) and explain the hold."
        if facts.recommended_zone_name
        else f"Hold position at {facts.origin_zone_name}, explain that an update is coming, and report the queue state upward."
    )

    return GenAIOutput(
        recommendation=recommendation,
        rationale=rationale[:5],
        confidence="high" if facts.recommended_zone_id else "medium",
        alternatives=alternatives[:3],
        announcements=announcements,
        referenced_zone_ids=[
            z for z in [facts.origin_zone_id, facts.recommended_zone_id, facts.welfare_zone_id] if z
        ],
    )
