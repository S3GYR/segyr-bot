"""Context builder — assembles system prompt and messages for the agent."""

import platform
from pathlib import Path
from typing import Any

from core.agent.memory import MemoryStore
from core.utils.helpers import build_assistant_message, current_time_str


class ContextBuilder:
    """Builds the context (system prompt + messages) for SEGYR-BOT."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)

    def build_system_prompt(self) -> str:
        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        if system == "Windows":
            platform_policy = """## Platform (Windows)
- Do not assume GNU tools. Prefer Windows-native commands or file tools.
"""
        else:
            platform_policy = """## Platform (POSIX)
- Prefer UTF-8 and standard shell tools.
"""

        return f"""# SEGYR-BOT — Agent IA Conducteur de Travaux / Responsable d'Affaires

Tu es SEGYR-BOT, un assistant IA spécialisé dans la gestion d'affaires BTP, le pilotage de chantier et le suivi financier.

## Runtime
{runtime}

## Workspace
Ton espace de travail est : {workspace_path}
- Mémoire long-terme : {workspace_path}/memory/MEMORY.md
- Historique : {workspace_path}/memory/HISTORY.md

{platform_policy}

## Domaines métier
- **Affaires** : gestion du portefeuille d'affaires, suivi d'avancement
- **Chantier** : planning, ressources, incidents, réception
- **Clients** : contacts, contrats, satisfaction
- **Finance** : devis, factures, situations de travaux, rentabilité

## Directives
- Annonce tes intentions avant d'appeler des outils, mais ne prédit jamais les résultats.
- Lis un fichier avant de le modifier.
- Si un outil échoue, analyse l'erreur avant de réessayer.
- Réponds en français sauf demande contraire.
- Pour les données sensibles (contrats, prix), demande confirmation avant toute modification.

Réponds directement par du texte pour les conversations simples."""

    @staticmethod
    def _build_runtime_context(channel: str | None, chat_id: str | None) -> str:
        lines = [f"Heure actuelle: {current_time_str()}"]
        if channel and chat_id:
            lines += [f"Canal: {channel}", f"Session: {chat_id}"]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)

    def _load_bootstrap_files(self) -> str:
        parts = []
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
        return "\n\n".join(parts) if parts else ""

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        channel: str | None = None,
        chat_id: str | None = None,
        current_role: str = "user",
    ) -> list[dict[str, Any]]:
        runtime_ctx = self._build_runtime_context(channel, chat_id)
        merged = f"{runtime_ctx}\n\n{current_message}"
        return [
            {"role": "system", "content": self.build_system_prompt()},
            *history,
            {"role": current_role, "content": merged},
        ]

    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str,
    ) -> list[dict[str, Any]]:
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result,
        })
        return messages

    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        messages.append(build_assistant_message(
            content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        ))
        return messages
