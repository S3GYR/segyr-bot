from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Chantier:
    id: Optional[int]
    titre: str
    client_id: Optional[int] = None
    entreprise_id: Optional[str] = None
    numero_affaire: Optional[str] = None
    montant_ht: Optional[float] = None
    avancement: float = 0.0
    echeance: Optional[date] = None
    statut: str = "brouillon"
    risques: list[str] = field(default_factory=list)
    notes: Optional[str] = None
    risk_score: int = 0
    heures_vendues: float = 0.0
    heures_consommees: float = 0.0
    heures_restantes: float = 0.0
    reste_a_faire: float = 0.0
    derive_heures: float = 0.0
    derive_pourcentage: float = 0.0
    projections: dict = field(default_factory=dict)
    budget_materiel_prevu: float = 0.0
    budget_materiel_engage: float = 0.0
    budget_materiel_restant: float = 0.0
    derive_budget_materiel: float = 0.0
    derive_budget_pourcentage: float = 0.0
    fdv: dict = field(default_factory=dict)
