from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class Facture:
    id: Optional[int]
    client_id: Optional[int]
    montant_ht: float
    due_date: Optional[date] = None
    statut: str = "brouillon"
    reference: Optional[str] = None
    notes: Optional[str] = None
    entreprise_id: Optional[str] = None
