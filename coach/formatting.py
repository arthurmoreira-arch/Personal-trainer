"""Formatação das respostas para o Telegram (HTML simples + divisão em mensagens)."""

from __future__ import annotations

import html
import re

TG_LIMIT = 4000
SPLIT_MARK = re.compile(r"^\s*-{3,}\s*$", re.MULTILINE)
_ALLOWED = ("b", "i", "u", "s", "code")


def to_html(text: str) -> str:
    """Escapa o texto e mantém só as tags permitidas pelo Telegram que usamos.
    Converte também Markdown comum (**negrito**, _itálico_, # títulos) caso o
    modelo escape do formato pedido."""
    s = html.escape(text, quote=False)
    for tag in _ALLOWED:
        s = re.sub(rf"&lt;(/?){tag}&gt;", rf"<\1{tag}>", s, flags=re.IGNORECASE)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", s, flags=re.MULTILINE)
    s = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)\*(?![\w*])", r"<b>\1</b>", s)
    s = re.sub(r"^\s*[-*]\s+", "• ", s, flags=re.MULTILINE)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"</?(?:b|i|u|s|code)>", "", s))


def split_messages(text: str) -> list[str]:
    """Divide nas linhas '---' (o modelo marca onde quebrar) e no limite do Telegram."""
    parts: list[str] = []
    for chunk in SPLIT_MARK.split(text):
        chunk = chunk.strip()
        while chunk:
            if len(chunk) <= TG_LIMIT:
                parts.append(chunk)
                break
            idx = chunk.rfind("\n\n", 0, TG_LIMIT)
            if idx <= 0:
                idx = chunk.rfind("\n", 0, TG_LIMIT)
            if idx <= 0:
                idx = TG_LIMIT
            parts.append(chunk[:idx].strip())
            chunk = chunk[idx:].strip()
    return parts
