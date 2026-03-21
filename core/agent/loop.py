"""Agent loop — the core processing engine of SEGYR-BOT."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from config.settings import settings
from loguru import logger

from core.agent.context import ContextBuilder
from core.agent.memory import MemoryConsolidator
from core.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from core.agent.tools.registry import ToolRegistry
from core.agent.tools.shell import ExecTool
from core.bus.events import InboundMessage, OutboundMessage
from core.bus.queue import MessageBus
from core.cache.redis_client import RedisClient
from core.providers.base import LLMProvider
from core.redis_memory import append_message as append_redis_message
from core.redis_memory import get_history as get_redis_history
from core.session.manager import Session, SessionManager
from segyr_bot.skills.base import BaseSkill
from segyr_bot.skills.loader import SkillsLoader
from segyr_bot.skills.registry import SkillsRegistry
from segyr_bot.skills.router import SkillsRouter


class AgentLoop:
    """
    The agent loop is the core processing engine.

    1. Receives messages from the bus
    2. Builds context with history and memory
    3. Calls the LLM
    4. Executes tool calls
    5. Returns responses
    """

    _TOOL_RESULT_MAX_CHARS = 16_000

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        context_window_tokens: int = 65_536,
        exec_timeout: int = 60,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
    ):
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.context_window_tokens = context_window_tokens
        self.exec_timeout = exec_timeout
        self.restrict_to_workspace = restrict_to_workspace

        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.memory_consolidator = MemoryConsolidator(
            workspace=workspace,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
        )

        self._running = False
        self._active_tasks: dict[str, list[asyncio.Task]] = {}
        self._background_tasks: list[asyncio.Task] = []
        self._processing_lock = asyncio.Lock()
        self.cache = RedisClient(
            url=settings.redis_url,
            enabled=settings.redis_enabled,
            default_ttl=settings.cache_ttl,
            timeout_s=1.0,
        )
        self.cache_hits = 0
        self.cache_miss = 0

        self.skills_registry: SkillsRegistry = SkillsLoader().load_builtin()
        self.skills_router = SkillsRouter(
            self.skills_registry,
            provider=self.provider,
            model=self.model,
            llm_timeout_s=1.5,
        )
        logger.info("Skills chargées: {}", ", ".join(self.skills_registry.list()) or "aucune")

        self._register_default_tools()

    async def _resolve_skill_invocation(self, content: str) -> tuple[BaseSkill, str] | None:
        raw = (content or "").strip()
        if not raw:
            return None

        skill_name = await self.skills_router.resolve(raw)
        if not skill_name:
            return None

        skill = self.skills_registry.get(skill_name)
        if not skill:
            return None

        parts = raw.split(maxsplit=1)
        first = parts[0].lstrip("/").lower() if parts else ""
        if first == skill_name:
            payload = parts[1] if len(parts) > 1 else ""
        else:
            payload = raw

        return skill, payload

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_timeout,
            restrict_to_workspace=self.restrict_to_workspace,
        ))

    def register_tool(self, tool) -> None:
        """Register an additional tool (business tools, etc.)."""
        self.tools.register(tool)

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks embedded by some models."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _is_cacheable_response(content: str | None) -> bool:
        if not content:
            return False
        text = content.strip()
        if not text:
            return False
        return text.lower() != "traitement en cours"

    @staticmethod
    def _build_cache_key(session_key: str, channel: str, chat_id: str, model: str, message: str) -> str:
        payload = {
            "session": session_key,
            "channel": channel,
            "chat_id": chat_id,
            "model": model,
            "message": (message or "").strip(),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"segyr:llm_cache:{digest}"

    def _cache_enabled(self) -> bool:
        return settings.redis_enabled and not settings.debug

    async def _load_redis_history(self, chat_id: str, limit: int = 10) -> list[dict[str, str]]:
        if not self._cache_enabled():
            return []
        try:
            return await asyncio.to_thread(get_redis_history, chat_id, limit)
        except Exception:
            return []

    async def _append_redis_memory(self, chat_id: str, role: str, content: str) -> None:
        text = (content or "").strip()
        if not text or not self._cache_enabled():
            return
        try:
            await asyncio.to_thread(append_redis_message, chat_id, role, text)
        except Exception:
            # Redis memory is optional and must never block core flow.
            pass

    @staticmethod
    def _merge_histories(
        session_history: list[dict[str, Any]],
        redis_history: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        if not redis_history:
            return session_history

        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for item in [*redis_history, *session_history]:
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            if not role or not content:
                continue
            sig = (role, content)
            if sig in seen:
                continue
            seen.add(sig)
            merged.append({"role": role, "content": content})

        return merged

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict]]:
        """Run the agent iteration loop."""
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []

        while iteration < self.max_iterations:
            iteration += 1
            tool_defs = self.tools.get_definitions()

            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=tool_defs,
                model=self.model,
            )

            if response.has_tool_calls:
                if on_progress:
                    thought = self._strip_think(response.content)
                    if thought:
                        await on_progress(thought)

                tool_call_dicts = [tc.to_openai_tool_call() for tc in response.tool_calls]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )

                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])

                    if on_progress:
                        await on_progress(f"→ {tool_call.name}({args_str[:60]})", tool_hint=True)

                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                clean = self._strip_think(response.content)
                if response.finish_reason == "error":
                    logger.error("LLM error: {}", (clean or "")[:200])
                    final_content = clean or "Désolé, une erreur s'est produite avec le modèle IA."
                    break
                messages = self.context.add_assistant_message(
                    messages, clean,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                final_content = clean
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"J'ai atteint le nombre maximum d'itérations ({self.max_iterations}) "
                "sans terminer la tâche. Essayez de décomposer la demande en étapes plus petites."
            )

        return final_content, tools_used, messages

    async def run(self) -> None:
        """Run the agent loop, consuming inbound messages."""
        self._running = True
        logger.info("SEGYR-BOT agent loop started")
        if self._cache_enabled() and self.cache.enabled:
            await self.cache.ping()

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning("Error consuming inbound message: {}, continuing...", e)
                continue

            cmd = msg.content.strip().lower()
            if cmd == "/stop":
                await self._handle_stop(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(
                    lambda t, k=msg.session_key: (
                        self._active_tasks.get(k, []).remove(t)
                        if t in self._active_tasks.get(k, []) else None
                    )
                )

    async def _handle_stop(self, msg: InboundMessage) -> None:
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        content = f"Arrêt de {cancelled} tâche(s)." if cancelled else "Aucune tâche active."
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    async def _dispatch(self, msg: InboundMessage) -> None:
        async with self._processing_lock:
            try:
                response = await self._process_message(msg)
                if response is not None:
                    await self.bus.publish_outbound(response)
                elif msg.channel == "cli":
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content="", metadata=msg.metadata or {},
                    ))
            except asyncio.CancelledError:
                logger.info("Task cancelled for session {}", msg.session_key)
                raise
            except Exception:
                logger.exception("Error processing message for session {}", msg.session_key)
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Désolé, une erreur s'est produite.",
                ))

    def _schedule_background(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.append(task)
        task.add_done_callback(self._background_tasks.remove)

    def stop(self) -> None:
        self._running = False
        logger.info("SEGYR-BOT agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            snapshot = session.messages[session.last_consolidated:]
            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            if snapshot:
                self._schedule_background(self.memory_consolidator.archive_messages(snapshot))
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id,
                content="Nouvelle session démarrée.",
            )
        if cmd == "/help":
            lines = [
                "SEGYR-BOT — Commandes disponibles:",
                "/new    — Démarrer une nouvelle conversation",
                "/stop   — Arrêter la tâche en cours",
                "/help   — Afficher cette aide",
                "",
                "Domaines: affaires, chantier, clients, facturation",
            ]
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content="\n".join(lines),
            )

        skill_invocation = await self._resolve_skill_invocation(msg.content)
        if skill_invocation:
            skill, payload = skill_invocation
            logger.info("Skill appelée: {} (sender={}, chat={})", skill.name, msg.sender_id, msg.chat_id)
            try:
                result = await skill.execute(payload)
                logger.info("Résultat skill {}: {}", skill.name, (result or "")[:200])
                session.add_message("user", msg.content)
                session.add_message("assistant", result)
                self.sessions.save(session)
                await self._append_redis_memory(msg.chat_id, "user", msg.content)
                await self._append_redis_memory(msg.chat_id, "assistant", result)
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=result,
                    metadata=msg.metadata or {},
                )
            except Exception:
                logger.exception("Échec exécution skill {}, fallback LLM", skill.name)

        logger.info("Fallback LLM (aucune skill correspondante)")

        cache_key = self._build_cache_key(
            session_key=key,
            channel=msg.channel,
            chat_id=msg.chat_id,
            model=self.model,
            message=msg.content,
        )
        if self._cache_enabled():
            cached = await self.cache.get(cache_key)
            if self._is_cacheable_response(cached):
                self.cache_hits += 1
                logger.info("Cache hit")
                session.add_message("user", msg.content)
                session.add_message("assistant", cached)
                self.sessions.save(session)
                await self._append_redis_memory(msg.chat_id, "user", msg.content)
                await self._append_redis_memory(msg.chat_id, "assistant", cached or "")
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=cached or "",
                    metadata=msg.metadata or {},
                )
            self.cache_miss += 1
            logger.info("Cache miss")

        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

        history = session.get_history(max_messages=0)
        redis_history = await self._load_redis_history(msg.chat_id, limit=12)
        history = self._merge_histories(history, redis_history)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages, on_progress=on_progress or _bus_progress,
        )

        if final_content is None:
            final_content = "Traitement terminé."

        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)
        self._schedule_background(self.memory_consolidator.maybe_consolidate_by_tokens(session))
        await self._append_redis_memory(msg.chat_id, "user", msg.content)
        await self._append_redis_memory(msg.chat_id, "assistant", final_content)

        if self._cache_enabled() and self._is_cacheable_response(final_content):
            stored = await self.cache.set(cache_key, final_content or "", ttl=settings.cache_ttl)
            if stored:
                logger.info("Cache stored")

        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[:self._TOOL_RESULT_MAX_CHARS] + "\n... (tronqué)"
            elif role == "user":
                if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or API usage)."""
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
        return response.content if response else ""
