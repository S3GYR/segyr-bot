from __future__ import annotations

import asyncio
import json
import re
from typing import Iterable

import aiohttp

from core.providers.base import LLMProvider
from segyr_bot.channels.logging import logger
from segyr_bot.skills.registry import SkillsRegistry

_WORD_RE = re.compile(r"[a-z0-9àâäéèêëîïôöùûüç]+", re.IGNORECASE)


class SkillsRouter:
    """Résolution intelligente d'une skill à partir d'un message utilisateur."""

    def __init__(
        self,
        registry: SkillsRegistry,
        provider: LLMProvider | None = None,
        model: str | None = None,
        llm_timeout_s: float = 1.5,
    ) -> None:
        self.registry = registry
        self.provider = provider
        self.model = model
        self.llm_timeout_s = llm_timeout_s
        self._llm_cache: dict[str, str | None] = {}

    @staticmethod
    def _parse_confidence(value: object) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            low = value.strip().lower()
            if low in {"high", "forte", "élevée", "elevee"}:
                return 0.9
            if low in {"medium", "moyenne"}:
                return 0.6
            if low in {"low", "faible"}:
                return 0.2
            try:
                return float(low)
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def _extract_skill_from_text(text: str, available: list[str]) -> str | None:
        low = (text or "").lower()
        for name in available:
            pattern = rf"(^|[^a-z0-9_]){re.escape(name)}([^a-z0-9_]|$)"
            if re.search(pattern, low):
                return name
        return None

    async def _ollama_generate(self, message: str, available: list[dict[str, object]]) -> str | None:
        if self.provider is None or not self.provider.api_base:
            return None
        if not self.model or not self.model.startswith("ollama/"):
            return None

        model_name = self.model.split("/", 1)[1]
        skill_names = [str(item.get("name", "")).strip() for item in available if item.get("name")]
        if not skill_names:
            return None

        prompt = (
            "Tu dois choisir une skill parmi la liste fournie. "
            f"Skills possibles: {json.dumps(skill_names, ensure_ascii=False)}. "
            "Réponds uniquement en JSON strict au format: "
            '{"skill": "nom_skill" ou null, "confidence": nombre entre 0 et 1}.\n\n'
            f"Message utilisateur: {message}\n"
        )

        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }
        url = f"{self.provider.api_base.rstrip('/')}/api/generate"
        timeout = aiohttp.ClientTimeout(total=max(self.llm_timeout_s, 25.0))

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    return str(data.get("response") or "").strip() or None
        except Exception:
            return None

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {m.group(0).lower() for m in _WORD_RE.finditer(text or "")}

    @staticmethod
    def _iter_attr(value: object) -> Iterable[str]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, (list, tuple, set)):
            return (str(v) for v in value)
        return ()

    def resolve_local(self, message: str) -> str | None:
        text = (message or "").strip()
        if not text:
            return None

        lower_text = text.lower()
        first = lower_text.split(maxsplit=1)[0].lstrip("/")

        # 1) Match direct du premier token (commande explicite)
        if self.registry.get(first):
            logger.info("router local match")
            return first

        best_name: str | None = None
        best_score = 0
        msg_tokens = self._tokenize(lower_text)

        for skill_name in self.registry.list():
            skill = self.registry.get(skill_name)
            if skill is None:
                continue

            score = 0

            # 2) Préfixes configurables
            prefixes = [skill_name, *self._iter_attr(getattr(skill, "triggers", ()))]
            for prefix in prefixes:
                p = str(prefix).strip().lower().lstrip("/")
                if not p:
                    continue
                if lower_text == p or lower_text.startswith(p + " "):
                    score = max(score, 100)

            # 3) Regex configurables
            for pattern in self._iter_attr(getattr(skill, "patterns", ())):
                try:
                    if re.search(pattern, lower_text, flags=re.IGNORECASE):
                        score = max(score, 90)
                except re.error:
                    # Pattern invalide -> ignoré pour ne pas casser le routage.
                    continue

            # 4) Score lexical (keywords + nom de skill)
            keywords = {
                *self._tokenize(skill_name),
                *self._tokenize(str(getattr(skill, "description", ""))),
                *{
                    token
                    for kw in self._iter_attr(getattr(skill, "keywords", ()))
                    for token in self._tokenize(kw)
                },
            }
            if keywords and msg_tokens:
                overlap = len(keywords.intersection(msg_tokens))
                if overlap > 0:
                    score = max(score, min(75, overlap * 15))

            if score > best_score:
                best_score = score
                best_name = skill_name

        # Seuil conservateur pour éviter les faux positifs.
        resolved = best_name if best_score >= 60 else None
        if resolved is not None:
            logger.info("router local match")
        return resolved

    @staticmethod
    def _extract_json_object(text: str) -> dict | None:
        raw = (text or "").strip()
        if not raw:
            return None

        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            pass

        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(raw[start : end + 1])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    async def resolve_with_llm(self, message: str) -> str | None:
        text = (message or "").strip()
        if not text:
            return None
        if self.provider is None:
            return None

        if text in self._llm_cache:
            return self._llm_cache[text]

        skills_payload = []
        available_skill_names: list[str] = []
        for skill_name in self.registry.list():
            skill = self.registry.get(skill_name)
            if skill is None:
                continue
            keywords = [str(v) for v in self._iter_attr(getattr(skill, "keywords", ()))]
            available_skill_names.append(skill_name)
            skills_payload.append(
                {
                    "name": skill_name,
                    "description": str(getattr(skill, "description", ""))[:180],
                    "keywords": keywords[:12],
                }
            )

        if not skills_payload:
            self._llm_cache[text] = None
            return None

        logger.info("router LLM fallback")

        system_prompt = (
            "Tu es un routeur de skills. Réponds uniquement en JSON valide au format: "
            '{"skill": "nom_skill" | null, "confidence": 0.0}. '
            "N'invente aucun nom de skill."
        )
        user_prompt = (
            "Message utilisateur:\n"
            f"{text}\n\n"
            "Skills disponibles (JSON):\n"
            f"{json.dumps(skills_payload, ensure_ascii=False)}\n\n"
            "Retourne uniquement l'objet JSON."
        )

        raw_content = ""
        if self.model and self.model.startswith("ollama/"):
            raw_content = (await self._ollama_generate(text, skills_payload) or "").strip()
        else:
            try:
                response = await asyncio.wait_for(
                    self.provider.chat_with_retry(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        model=self.model,
                        max_tokens=180,
                        temperature=0,
                    ),
                    timeout=self.llm_timeout_s,
                )
                raw_content = (response.content or "").strip()
            except Exception:
                raw_content = ""

        data = self._extract_json_object(raw_content)
        if not data:
            hinted_skill = self._extract_skill_from_text(raw_content, available_skill_names)
            if hinted_skill:
                logger.info("router LLM selected skill")
                self._llm_cache[text] = hinted_skill
                return hinted_skill
            self._llm_cache[text] = None
            return None

        skill_name = data.get("skill")
        conf = self._parse_confidence(data.get("confidence", 0))

        if isinstance(skill_name, str):
            skill_name = skill_name.strip().lower()
        else:
            skill_name = None

        if not skill_name:
            skill_name = self._extract_skill_from_text(raw_content, available_skill_names)

        if skill_name and conf >= 0.6 and self.registry.get(skill_name):
            logger.info("router LLM selected skill")
            self._llm_cache[text] = skill_name
            return skill_name

        self._llm_cache[text] = None
        return None

    async def resolve(self, message: str) -> str | None:
        local = self.resolve_local(message)
        if local is not None:
            return local

        llm_skill = await self.resolve_with_llm(message)
        if llm_skill is not None:
            return llm_skill

        logger.info("router fallback none")
        return None
