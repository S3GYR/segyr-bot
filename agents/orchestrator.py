"""Orchestrateur SEGYR-BOT — détecte l'intention et route les demandes."""

from __future__ import annotations

import re
from enum import Enum
from dataclasses import dataclass
from typing import Any

from loguru import logger


class BusinessDomain(str, Enum):
    """Domaines métier reconnus par l'orchestrateur."""
    FINANCE = "finance"
    CHANTIER = "chantier"
    CLIENT = "client"
    AFFAIRE = "affaire"
    TECHNIQUE = "technique"
    GENERAL = "general"


@dataclass
class Intent:
    """Intention détectée dans un message utilisateur."""
    domain: BusinessDomain
    action: str
    confidence: float
    entities: dict[str, Any]

_FINANCE_PRIORITY_KEYWORDS = {
    "facture",
    "devis",
    "paiement",
    "acompte",
    "solde",
    "règlement",
    "impayé",
}


# Règles de détection par mots-clés (rapide, avant appel LLM)
_DOMAIN_KEYWORDS: dict[BusinessDomain, list[str]] = {
    BusinessDomain.FINANCE: [
        "facture", "devis", "paiement", "acompte", "solde", "situation",
        "montant", "prix", "coût", "budget", "rentabilité", "marge",
        "avoir", "règlement", "relance", "impayé",
    ],
    BusinessDomain.CHANTIER: [
        "chantier", "planning", "avancement", "travaux", "phase",
        "réception", "levée", "réserve", "incident", "retard",
        "ressource", "matériau", "fourniture", "sous-traitant",
    ],
    BusinessDomain.CLIENT: [
        "client", "contact", "maître d'ouvrage", "moa", "interlocuteur",
        "contrat", "satisfaction", "réclamation", "coordonnées",
    ],
    BusinessDomain.AFFAIRE: [
        "affaire", "dossier", "projet", "référence", "n°", "numéro",
        "statut", "portefeuille", "pipeline", "opportunité",
    ],
    BusinessDomain.TECHNIQUE: [
        "calcul", "dimensionnement", "plan", "norme", "dtu",
        "métré", "quantitatif", "bpqe", "spécification",
    ],
}

_ACTION_PATTERNS: list[tuple[str, str]] = [
    (r"\b(créer|ajouter|nouveau|nouvelle|enregistrer)\b", "create"),
    (r"\b(modifier|mettre à jour|changer|corriger|éditer)\b", "update"),
    (r"\b(supprimer|effacer|annuler)\b", "delete"),
    (r"\b(chercher|trouver|afficher|lister|voir|consulter|montrer)\b", "read"),
    (r"\b(envoyer|transmettre|notifier|relancer)\b", "send"),
    (r"\b(calculer|estimer|chiffrer|évaluer)\b", "calculate"),
    (r"\b(valider|approuver|confirmer)\b", "validate"),
    (r"\b(clôturer|terminer|fermer|finaliser)\b", "close"),
]


def detect_intent(message: str) -> Intent:
    """
    Détecte le domaine métier et l'action à partir du message.

    Algorithme simple par mots-clés — peut être remplacé
    par un appel LLM pour plus de précision.
    """
    message_lower = message.lower()

    # Détection domaine
    domain_scores: dict[BusinessDomain, int] = {}
    entities: dict[str, Any] = {}

    for domain, keywords in _DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in message_lower)
        if score > 0:
            domain_scores[domain] = score

    if BusinessDomain.FINANCE in domain_scores and BusinessDomain.CHANTIER in domain_scores:
        if any(keyword in message_lower for keyword in _FINANCE_PRIORITY_KEYWORDS):
            domain_scores[BusinessDomain.FINANCE] += 1

    if domain_scores:
        best_domain = max(domain_scores, key=lambda d: domain_scores[d])
        total = sum(domain_scores.values())
        confidence = domain_scores[best_domain] / total
    else:
        best_domain = BusinessDomain.GENERAL
        confidence = 1.0

    # Détection action
    action = "read"  # default
    for pattern, act in _ACTION_PATTERNS:
        if re.search(pattern, message_lower):
            action = act
            break

    # Extraction d'entités simples
    ref_match = re.search(r'\b([A-Z]{2,5}-?\d{3,8})\b', message)
    if ref_match:
        entities["reference"] = ref_match.group(1)

    amount_match = re.search(r'(\d[\d\s]*(?:[,.]\d+)?)\s*(?:€|EUR|euros?)', message, re.IGNORECASE)
    if amount_match:
        entities["montant"] = amount_match.group(1).replace(" ", "")

    logger.debug(
        "Intent detected: domain={} action={} confidence={:.0%} entities={}",
        best_domain.value, action, confidence, entities,
    )

    return Intent(
        domain=best_domain,
        action=action,
        confidence=confidence,
        entities=entities,
    )


class Orchestrator:
    """
    Orchestrateur principal de SEGYR-BOT.

    Reçoit un message, détecte l'intention métier,
    et enrichit le contexte pour l'agent.
    """

    def __init__(self):
        self._handlers: dict[BusinessDomain, list] = {d: [] for d in BusinessDomain}

    def register_handler(self, domain: BusinessDomain, handler) -> None:
        """Enregistre un handler pour un domaine métier."""
        self._handlers[domain].append(handler)

    async def route(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Analyse le message et retourne le contexte enrichi.

        Returns:
            dict avec:
              - intent: l'intention détectée
              - domain: le domaine métier
              - action: l'action à effectuer
              - entities: les entités extraites
              - system_hint: indication supplémentaire pour le prompt
        """
        intent = detect_intent(message)
        ctx = context or {}

        system_hint = self._build_system_hint(intent)

        result = {
            "intent": intent,
            "domain": intent.domain.value,
            "action": intent.action,
            "entities": intent.entities,
            "system_hint": system_hint,
            **ctx,
        }

        # Appel des handlers enregistrés
        for handler in self._handlers.get(intent.domain, []):
            try:
                handler_result = await handler(intent, result)
                if handler_result:
                    result.update(handler_result)
            except Exception as e:
                logger.warning("Handler error for domain {}: {}", intent.domain, e)

        return result

    def _build_system_hint(self, intent: Intent) -> str:
        """Construit une indication système basée sur l'intention."""
        hints = {
            BusinessDomain.FINANCE: (
                "L'utilisateur pose une question financière. "
                "Vérifie les données dans la base, calcule avec précision, "
                "cite les montants HT et TTC."
            ),
            BusinessDomain.CHANTIER: (
                "L'utilisateur parle d'un chantier. "
                "Identifie l'affaire concernée, vérifie le planning, "
                "note les incidents ou blocages."
            ),
            BusinessDomain.CLIENT: (
                "L'utilisateur parle d'un client. "
                "Retrouve ses coordonnées et son historique, "
                "adopte un ton professionnel."
            ),
            BusinessDomain.AFFAIRE: (
                "L'utilisateur parle d'une affaire. "
                "Retrouve le dossier, présente son statut complet "
                "et les actions en cours."
            ),
            BusinessDomain.TECHNIQUE: (
                "L'utilisateur pose une question technique. "
                "Sois précis, cite les normes applicables si pertinent."
            ),
            BusinessDomain.GENERAL: (
                "Réponds de manière utile et professionnelle."
            ),
        }
        return hints.get(intent.domain, "")
