from __future__ import annotations

from typing import Dict, List, Optional

from modules.affaires.schema import Affaire


class AffaireService:
    """Service affaires minimal en mémoire."""

    def __init__(self) -> None:
        self._items: Dict[int, Affaire] = {}
        self._next_id = 1

    def create(self, affaire: Affaire) -> Affaire:
        affaire.id = self._next_id
        self._items[self._next_id] = affaire
        self._next_id += 1
        return affaire

    def list(self) -> List[Affaire]:
        return list(self._items.values())

    def get(self, item_id: int) -> Optional[Affaire]:
        return self._items.get(item_id)

    def update(self, item_id: int, data: dict) -> Optional[Affaire]:
        existing = self._items.get(item_id)
        if not existing:
            return None
        for k, v in data.items():
            if hasattr(existing, k):
                setattr(existing, k, v)
        return existing
