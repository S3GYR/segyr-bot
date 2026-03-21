from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from core.memory import MemoryStore
from modules.clients.schema import Client
from modules.clients.scoring import compute_client_score


class ClientService:
    """Service client adossé à PostgreSQL via MemoryStore."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    @staticmethod
    def _to_client(row: Dict[str, object] | None) -> Optional[Client]:
        if not row:
            return None
        payload = {field: row.get(field) for field in Client.__dataclass_fields__}
        return Client(**payload)

    def _score_inputs(self, client_id: int, entreprise_id: str | None = None) -> Dict[str, object]:
        factures = self.store.list_factures_by_client(client_id, entreprise_id=entreprise_id)
        today = date.today()
        unpaid = [f for f in factures if f.get("statut") not in {"payée", "paye"}]
        factures_retard = [f for f in unpaid if f.get("due_date") and str(f["due_date"]) < str(today)]
        montant_impaye = sum(float(f.get("montant_ht") or 0) for f in unpaid)
        delays = []
        for f in factures_retard:
            try:
                d = date.fromisoformat(str(f["due_date"]))
                delays.append((today - d).days)
            except Exception:
                continue
        delai_moyen = sum(delays) / len(delays) if delays else 0
        return {
            "factures_retard": len(factures_retard),
            "delai_moyen": delai_moyen,
            "montant_impaye": montant_impaye,
            "nb_relances": 0,
        }

    def _compute_and_store_score(self, client_id: int, entreprise_id: str | None = None) -> Optional[Client]:
        inputs = self._score_inputs(client_id, entreprise_id)
        score_data = compute_client_score(inputs)
        row = self.store.update_client_score(client_id, score_data["score"])
        return self._to_client(row)

    def create(self, client: Client | Dict[str, object]) -> Client:
        if isinstance(client, dict):
            payload = {"id": None, **client}
            client = Client(**payload)
        row = self.store.add_client(client.name, client.email, client.phone, client.notes, score_client=int(client.score_client or 50), entreprise_id=client.entreprise_id)
        created = self._to_client(row)
        if created is None:
            raise ValueError("Échec de création du client")
        if created.id is None:
            return created
        recomputed = self._compute_and_store_score(created.id, created.entreprise_id)
        return recomputed or created

    def list(self, entreprise_id: str | None = None) -> List[Client]:
        clients: List[Client] = []
        for row in self.store.list_clients(entreprise_id=entreprise_id):
            client = self._to_client(row)
            if client is not None:
                clients.append(client)
        return clients

    def get(self, client_id: int) -> Optional[Client]:
        row = self.store.get_client(client_id)
        return self._to_client(row)

    def update(self, client_id: int, data: dict) -> Optional[Client]:
        row = self.store.update_client(client_id, data)
        if not row:
            return None
        entreprise_id = data.get("entreprise_id") or row.get("entreprise_id")
        updated = self._compute_and_store_score(client_id, entreprise_id)
        return updated or self._to_client(row)

    def recompute_score_for_client(self, client_id: int, entreprise_id: str | None = None) -> Optional[Client]:
        return self._compute_and_store_score(client_id, entreprise_id)
