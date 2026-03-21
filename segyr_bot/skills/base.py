from __future__ import annotations

from abc import ABC, abstractmethod


class BaseSkill(ABC):
    """Contrat minimal des skills SEGYR."""

    name: str = "skill"
    description: str = ""

    @abstractmethod
    async def execute(self, input_text: str) -> str:
        """Execute la skill et retourne une réponse texte."""
