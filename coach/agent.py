"""Loop de conversa com o Claude (Messages API + ferramentas locais)."""

from __future__ import annotations

import asyncio
import base64
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

import anthropic

from .config import CONFIG
from .db import DB
from .prompts import SYSTEM_PROMPT
from .tools import TOOLS, ToolExecutor, compute_targets

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 12
# Só texto e chamadas/resultados de ferramenta vão para o histórico salvo.
# Blocos de "thinking" não são reenviados em turnos futuros: assim o histórico
# pode ser aparado pelo início sem quebrar a verificação de histórico da API.
_PERSIST_BLOCKS = {"text", "tool_use", "tool_result"}


class Coach:
    def __init__(self, db: DB, client: anthropic.AsyncAnthropic | None = None):
        self.db = db
        self.client = client or anthropic.AsyncAnthropic()
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ------------------------------------------------------------------ #
    def _context_line(self, user_id: int, now: datetime) -> str:
        totals = self.db.day_totals(user_id, now.date())
        targets = compute_targets(self.db.get_profile(user_id))
        parts = [f"agora: {now:%Y-%m-%d %H:%M} ({now:%A})"]
        if "protein_target_g" in targets:
            parts.append(
                f"hoje: {totals['kcal']:.0f}/{targets['kcal_target']} kcal, "
                f"{totals['protein_g']:.0f}/{targets['protein_target_g']} g proteína, "
                f"{totals['meals']} refeições registradas"
            )
        else:
            parts.append("perfil incompleto: " + ", ".join(targets.get("missing_for_targets", [])))
        return "[contexto] " + " | ".join(parts)

    async def chat(self, user_id: int, text: str | None = None, image_jpeg: bytes | None = None) -> str:
        async with self._locks[user_id]:
            return await self._chat(user_id, text, image_jpeg)

    async def _chat(self, user_id: int, text: str | None, image_jpeg: bytes | None) -> str:
        now = datetime.now(CONFIG.tz).replace(tzinfo=None)
        content: list[dict[str, Any]] = []
        if image_jpeg is not None:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg",
                           "data": base64.standard_b64encode(image_jpeg).decode()},
            })
        user_text = text or ("Analise esta refeição." if image_jpeg is not None else "")
        content.append({"type": "text", "text": f"{self._context_line(user_id, now)}\n\n{user_text}"})

        history = self.db.recent_messages(user_id, CONFIG.history_messages)
        new_turn: list[dict[str, Any]] = [{"role": "user", "content": content}]
        executor = ToolExecutor(self.db, user_id, now)

        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            response = await self._create(history + new_turn)

            if response.stop_reason == "refusal":
                reply = "Não consigo ajudar com isso. Posso ajudar com treino, nutrição ou rotina?"
                break

            new_turn.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "pause_turn":
                continue

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                reply = "\n".join(b.text for b in response.content if b.type == "text").strip()
                break

            results = []
            for tu in tool_uses:
                try:
                    out = executor.run(tu.name, dict(tu.input))
                    results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out})
                except Exception as e:  # noqa: BLE001 — devolvemos o erro ao modelo
                    log.exception("tool %s failed", tu.name)
                    results.append({"type": "tool_result", "tool_use_id": tu.id,
                                    "content": f"Erro: {e}", "is_error": True})
            new_turn.append({"role": "user", "content": results})
        else:
            reply = reply or "Fiz muitas operações seguidas e parei por segurança. Pode repetir o pedido?"

        self._persist(user_id, new_turn, had_image=image_jpeg is not None)
        return reply or "👍"

    async def _create(self, messages: list[dict[str, Any]]):
        return await self.client.beta.messages.create(
            model=CONFIG.model,
            max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": CONFIG.effort},
            cache_control={"type": "ephemeral"},
            # Se o modelo principal recusar por um falso positivo de segurança,
            # a API refaz a mesma requisição num modelo de reserva.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    def _persist(self, user_id: int, turn: list[dict[str, Any]], had_image: bool) -> None:
        for i, msg in enumerate(turn):
            blocks = []
            for b in msg["content"]:
                d = b if isinstance(b, dict) else b.model_dump(exclude_none=True)
                if d.get("type") == "image":
                    blocks.append({"type": "text", "text": "[foto de refeição enviada pelo aluno]"})
                elif d.get("type") in _PERSIST_BLOCKS:
                    if d["type"] == "tool_use":
                        d = {k: d[k] for k in ("type", "id", "name", "input")}
                    elif d["type"] == "text":
                        d = {"type": "text", "text": d["text"]}
                    blocks.append(d)
            if blocks:
                self.db.append_message(user_id, msg["role"], blocks)
            elif msg["role"] == "assistant" and i + 1 < len(turn):
                # assistente sem bloco persistível no meio do turno: mantém a alternância
                self.db.append_message(user_id, "assistant", [{"type": "text", "text": "..."}])

    def note_proactive(self, user_id: int, text: str) -> None:
        """Guarda no histórico uma mensagem enviada pelo bot por conta própria."""
        self.db.append_message(user_id, "assistant", [{"type": "text", "text": text}])
