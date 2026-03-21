from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from core.memory import MemoryStore
from modules.factures.schema import Facture
from modules.clients.service import ClientService


class InvoiceService:
    """Service factures adossé à PostgreSQL via MemoryStore."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    @staticmethod
    def _to_facture(row: Dict[str, object] | None) -> Optional[Facture]:
        if not row:
            return None
        payload = {field: row.get(field) for field in Facture.__dataclass_fields__}
        return Facture(**payload)

    def create(self, facture: Facture | Dict[str, object]) -> Facture:
        if isinstance(facture, dict):
            if facture.get("due_date") and isinstance(facture.get("due_date"), str):
                facture = {**facture, "due_date": date.fromisoformat(facture["due_date"])}
            payload = {"id": None, **facture}
            facture = Facture(**payload)
        row = self.store.add_facture(
            facture.client_id,
            facture.montant_ht,
            facture.due_date.isoformat() if getattr(facture, "due_date", None) else None,
            facture.reference,
            facture.notes,
            facture.entreprise_id,
        )
        created = self._to_facture(row)
        if created is None:
            raise ValueError("Échec de création de la facture")
        if created.client_id:
            ClientService(self.store).recompute_score_for_client(created.client_id, facture.entreprise_id)
        return created

    def list(self, entreprise_id: str | None = None) -> List[Facture]:
        factures: List[Facture] = []
        for row in self.store.list_factures(entreprise_id=entreprise_id):
            facture = self._to_facture(row)
            if facture is not None:
                factures.append(facture)
        return factures

    def get(self, item_id: int) -> Optional[Facture]:
        row = self.store.get_facture(item_id)
        return self._to_facture(row)

    def update(self, item_id: int, data: dict) -> Optional[Facture]:
        row = self.store.update_facture(item_id, data)
        if not row:
            return None
        updated = self._to_facture(row)
        if updated is None:
            return None
        if updated.client_id:
            ClientService(self.store).recompute_score_for_client(updated.client_id, data.get("entreprise_id") or row.get("entreprise_id"))
        return updated
