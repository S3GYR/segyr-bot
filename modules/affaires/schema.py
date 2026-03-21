from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class Affaire:
    id: Optional[int]
    titre: str
    client_id: Optional[int] = None
    montant_ht: Optional[float] = None
    echeance: Optional[date] = None
    statut: str = "brouillon"
    notes: Optional[str] = None
