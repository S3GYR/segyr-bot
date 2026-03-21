from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Client:
    id: Optional[int]
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    score_client: float = 50
    entreprise_id: Optional[str] = None
