from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class FDVData:
    prix_vente_ht: float = 0.0
    materiel_prevu: float = 0.0
    materiel_reel: float = 0.0
    heures_prevues: float = 0.0
    heures_reelles: float = 0.0
    taux_horaire: float = 0.0
    cout_vehicule: float = 0.0
    cout_outillage: float = 0.0
    frais_generaux_pct: float = 0.0

    cout_direct: float = 0.0
    prix_revient: float = 0.0
    marge: float = 0.0
    rentabilite_pct: float = 0.0

    chantier_id: Optional[int] = None
