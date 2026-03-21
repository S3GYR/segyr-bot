from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from core.memory import MemoryStore
from modules.chantier.schema import Chantier
from modules.chantier.engine import compute_heures_metrics, compute_budget_materiel, projection_fin_chantier
from modules.fdv.engine import compute_fdv


class ChantierService:
    """Services chantier : état, planning, alertes risques."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    def _from_row(self, row: Dict[str, object]) -> Chantier:
        cleaned = dict(row)
        if cleaned.get("echeance") and isinstance(cleaned["echeance"], str):
            try:
                cleaned["echeance"] = date.fromisoformat(cleaned["echeance"])
            except ValueError:
                pass
        metrics = compute_heures_metrics(cleaned)
        budget_metrics = compute_budget_materiel(cleaned)
        enriched = projection_fin_chantier({**cleaned, **metrics, **budget_metrics})
        cleaned.update({k: v for k, v in enriched.items() if not k.startswith("projection_")})
        cleaned["projections"] = {k: v for k, v in enriched.items() if k.startswith("projection_")}
        fdv_data = compute_fdv(cleaned, cleaned.get("fdv"))
        cleaned["fdv"] = fdv_data.__dict__
        return Chantier(**cleaned)

    def create(self, chantier: Chantier | Dict[str, object]) -> Chantier:
        if isinstance(chantier, dict):
            chantier = Chantier(**chantier)
        # Numero d'affaire auto AFF-YYYY-ID simulé (ID sera affecté après insert, donc préfix basé sur date + compteur temporaire)
        year = date.today().year
        numero_affaire = chantier.numero_affaire or f"AFF-{year}-PENDING"
        metrics = compute_heures_metrics(chantier.__dict__)
        budget_metrics = compute_budget_materiel(chantier.__dict__)
        fdv_data = compute_fdv({**chantier.__dict__, **metrics, **budget_metrics}, chantier.fdv)
        row = self.store.add_project(
            chantier.titre,
            chantier.client_id,
            chantier.entreprise_id,
            numero_affaire,
            chantier.montant_ht,
            chantier.echeance.isoformat() if chantier.echeance else None,
            chantier.statut,
            chantier.avancement,
            chantier.notes,
            chantier.risk_score,
            metrics["heures_vendues"],
            metrics["heures_consommees"],
            metrics["heures_restantes"],
            metrics["reste_a_faire"],
            metrics["derive_heures"],
            metrics["derive_pourcentage"],
            budget_metrics["budget_materiel_prevu"],
            budget_metrics["budget_materiel_engage"],
            budget_metrics["budget_materiel_restant"],
            budget_metrics["derive_budget_materiel"],
            budget_metrics["derive_budget_pourcentage"],
        )
        created = self._from_row(row)
        # Ajout suffix avec ID réel
        if created and created.id and (created.numero_affaire or "PENDING" in numero_affaire):
            naff = f"AFF-{date.today().year}-{created.id:05d}"
            self.store.update_project(created.id, {"numero_affaire": naff})
            created.numero_affaire = naff
        created.fdv = fdv_data.__dict__
        try:
            self.store.save_fdv_snapshot({**fdv_data.__dict__, "chantier_id": created.id, "heures_consommees": metrics["heures_consommees"], "materiel_reel": budget_metrics["budget_materiel_engage"]})
        except Exception:
            pass
        return created

    def update(self, chantier_id: int, data: dict) -> Optional[Chantier]:
        current = self.store.get_project(chantier_id)
        if not current:
            return None
        merged = {**current, **data}
        metrics = compute_heures_metrics(merged)
        budget_metrics = compute_budget_materiel(merged)
        fdv_data = compute_fdv({**merged, **metrics, **budget_metrics}, merged.get("fdv"))
        merged.update({**metrics, **budget_metrics, "fdv": fdv_data.__dict__})
        db_payload = {k: v for k, v in merged.items() if k != "fdv"}
        row = self.store.update_project(chantier_id, db_payload)
        updated = self._from_row(row) if row else None
        if updated:
            try:
                self.store.save_fdv_snapshot({**fdv_data.__dict__, "chantier_id": updated.id, "heures_consommees": metrics["heures_consommees"], "materiel_reel": budget_metrics["budget_materiel_engage"]})
            except Exception:
                pass
        return updated

    def list(self, entreprise_id: str | None = None) -> List[Chantier]:
        return [self._from_row(r) for r in self.store.list_projects(entreprise_id=entreprise_id)]

    def get(self, chantier_id: int) -> Optional[Chantier]:
        row = self.store.get_project(chantier_id)
        return self._from_row(row) if row else None

    def check_status(self, chantier_id: int) -> Dict[str, object]:
        chantier = self.get(chantier_id)
        if not chantier:
            return {"error": "chantier introuvable"}
        risks = []
        if chantier.avancement < 50 and chantier.statut not in {"planifié", "lancé", "en cours"}:
            risks.append("Statut incohérent vs avancement")
        if chantier.echeance and chantier.echeance < date.today():
            risks.append("Echéance dépassée")
        return {"chantier": chantier.__dict__, "risques": risks}

    def plan(self, chantier_id: int) -> Dict[str, object]:
        chantier = self.get(chantier_id)
        if not chantier:
            return {"error": "chantier introuvable"}
        horizon = "court terme" if chantier.avancement < 50 else "stabilisation"
        next_steps = [
            "Mettre à jour planning jalons",
            "Revue risques terrain avec équipes",
            "Confirmer ressources critiques",
        ]
        return {"chantier": chantier.__dict__, "horizon": horizon, "next_steps": next_steps}

    def alertes(self) -> Dict[str, object]:
        projets = self.store.list_projects()
        alerts = []
        for p in projets:
            if p.get("echeance") and str(p["echeance"]) < str(date.today()):
                alerts.append({"projet_id": p["id"], "type": "retard", "message": "Echéance dépassée"})
            if p.get("avancement", 0) < 20:
                alerts.append({"projet_id": p["id"], "type": "ralentissement", "message": "Avancement < 20%"})
        return {"alertes": alerts}
