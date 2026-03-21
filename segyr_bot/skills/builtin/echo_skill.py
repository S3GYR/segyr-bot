from __future__ import annotations

import re

from segyr_bot.skills.base import BaseSkill


class EchoSkill(BaseSkill):
    name = "echo"
    description = "Renvoie le texte passé après la commande echo"

    async def execute(self, input_text: str) -> str:
        payload = input_text.strip()
        if not payload:
            return ""

        normalized = payload.lower()
        if normalized.startswith("echo "):
            return payload.split(maxsplit=1)[1].strip()

        patterns = [
            r"^(?:peux-tu|peux tu|tu peux)?\s*(?:répète|répéter|repete|repeter|repeat)\s+(.+)$",
            r"^(?:merci de\s+)?(?:répète|répéter|repete|repeter|repeat)\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, payload, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return payload
