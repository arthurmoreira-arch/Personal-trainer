"""Configuração lida de variáveis de ambiente (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


def _times(raw: str | None, default: str) -> list[str]:
    return [t.strip() for t in (raw or default).split(",") if t.strip()]


@dataclass(frozen=True)
class Config:
    telegram_token: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    allowed_user_ids: set[int] = field(default_factory=lambda: _ids(os.environ.get("ALLOWED_USER_IDS")))
    model: str = field(default_factory=lambda: os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"))
    effort: str = field(default_factory=lambda: os.environ.get("CLAUDE_EFFORT", "medium"))
    db_path: str = field(default_factory=lambda: os.environ.get("DB_PATH", "data/coach.db"))
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo(os.environ.get("TZ_NAME", "America/Sao_Paulo")))
    # Horários (HH:MM, fuso TZ_NAME) para checar proteína do dia
    protein_check_times: list[str] = field(
        default_factory=lambda: _times(os.environ.get("PROTEIN_CHECK_TIMES"), "15:00,20:30")
    )
    # Dia/hora do feedback semanal (0=segunda ... 6=domingo)
    weekly_feedback_day: int = field(default_factory=lambda: int(os.environ.get("WEEKLY_FEEDBACK_DAY", "6")))
    weekly_feedback_time: str = field(default_factory=lambda: os.environ.get("WEEKLY_FEEDBACK_TIME", "19:00"))
    history_messages: int = field(default_factory=lambda: int(os.environ.get("HISTORY_MESSAGES", "30")))


CONFIG = Config()
