from __future__ import annotations

from typing import Dict

from modules.fdv.schema import FDVData


def compute_fdv(chantier: Dict[str, object], fdv: FDVData | Dict[str, object] | None = None) -> FDVData:
    """Calcule coût, marge et rentabilité d'un chantier à partir des données FDV.

    Les champs FDV peuvent être partiellement fournis ; on complète avec les données chantier
    (heures vendues/consommées, budget matériel, montant HT).
    """

    base = fdv.__dict__ if isinstance(fdv, FDVData) else dict(fdv or {})

    prix_vente_ht = float(base.get("prix_vente_ht") or chantier.get("montant_ht") or 0)
    materiel_prevu = float(base.get("materiel_prevu") or chantier.get("budget_materiel_prevu") or 0)
    materiel_reel = float(base.get("materiel_reel") or chantier.get("budget_materiel_engage") or 0)
    heures_prevues = float(base.get("heures_prevues") or chantier.get("heures_vendues") or 0)
    heures_reelles = float(base.get("heures_reelles") or chantier.get("heures_consommees") or 0)
    taux_horaire = float(base.get("taux_horaire") or 0)
    cout_vehicule = float(base.get("cout_vehicule") or 0)
    cout_outillage = float(base.get("cout_outillage") or 0)
    frais_generaux_pct = float(base.get("frais_generaux_pct") or 0)

    cout_direct = materiel_reel + heures_reelles * taux_horaire + cout_vehicule + cout_outillage
    prix_revient = cout_direct + (frais_generaux_pct / 100.0) * prix_vente_ht
    marge = prix_vente_ht - prix_revient
    rentabilite_pct = (marge / prix_vente_ht * 100) if prix_vente_ht else 0.0

    return FDVData(
        prix_vente_ht=prix_vente_ht,
        materiel_prevu=materiel_prevu,
        materiel_reel=materiel_reel,
        heures_prevues=heures_prevues,
        heures_reelles=heures_reelles,
        taux_horaire=taux_horaire,
        cout_vehicule=cout_vehicule,
        cout_outillage=cout_outillage,
        frais_generaux_pct=frais_generaux_pct,
        cout_direct=cout_direct,
        prix_revient=prix_revient,
        marge=marge,
        rentabilite_pct=rentabilite_pct,
        chantier_id=chantier.get("id"),
    )
