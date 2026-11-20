"""Persistência em SQLite (arquivo único, sem servidor)."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    user_id INTEGER PRIMARY KEY,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    logged_at TEXT NOT NULL,
    description TEXT NOT NULL,
    items TEXT NOT NULL,
    kcal REAL NOT NULL,
    protein_g REAL NOT NULL,
    carbs_g REAL NOT NULL,
    fat_g REAL NOT NULL,
    fiber_g REAL,
    confidence TEXT
);
CREATE TABLE IF NOT EXISTS workout_plan (
    user_id INTEGER PRIMARY KEY,
    plan TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sets_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    exercise TEXT NOT NULL,
    load_kg REAL NOT NULL,
    reps TEXT NOT NULL,
    rir REAL,
    decision TEXT,
    next_load_kg REAL
);
CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    PRIMARY KEY (user_id, day, kind)
);
"""


class DB:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------------- perfil ----------------
    def get_profile(self, user_id: int) -> dict[str, Any]:
        with self._conn() as c:
            row = c.execute("SELECT data FROM profile WHERE user_id=?", (user_id,)).fetchone()
        return json.loads(row["data"]) if row else {}

    def update_profile(self, user_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        prof = self.get_profile(user_id)
        prof.update({k: v for k, v in fields.items() if v is not None})
        with self._conn() as c:
            c.execute(
                "INSERT INTO profile(user_id, data) VALUES(?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
                (user_id, json.dumps(prof, ensure_ascii=False)),
            )
        return prof

    def all_user_ids(self) -> list[int]:
        with self._conn() as c:
            return [r["user_id"] for r in c.execute("SELECT user_id FROM profile")]

    # ---------------- histórico de conversa ----------------
    def append_message(self, user_id: int, role: str, content: Any) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO messages(user_id, role, content, created_at) VALUES(?,?,?,?)",
                (user_id, role, json.dumps(content, ensure_ascii=False), datetime.now(UTC).isoformat()),
            )

    def recent_messages(self, user_id: int, limit: int) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        msgs = [{"role": r["role"], "content": json.loads(r["content"])} for r in reversed(rows)]
        # O histórico precisa começar numa mensagem de usuário com texto
        # (não num tool_result órfão).
        while msgs and not _is_plain_user(msgs[0]):
            msgs.pop(0)
        return msgs

    def clear_messages(self, user_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM messages WHERE user_id=?", (user_id,))

    # ---------------- refeições ----------------
    def log_meal(self, user_id: int, day: date, logged_at: datetime, meal: dict[str, Any]) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO meals(user_id, day, logged_at, description, items, kcal, protein_g, "
                "carbs_g, fat_g, fiber_g, confidence) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    user_id,
                    day.isoformat(),
                    logged_at.isoformat(),
                    meal["description"],
                    json.dumps(meal.get("items", []), ensure_ascii=False),
                    float(meal["kcal"]),
                    float(meal["protein_g"]),
                    float(meal["carbs_g"]),
                    float(meal["fat_g"]),
                    meal.get("fiber_g"),
                    meal.get("confidence"),
                ),
            )
            return int(cur.lastrowid)

    def delete_meal(self, user_id: int, meal_id: int) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM meals WHERE user_id=? AND id=?", (user_id, meal_id))
            return cur.rowcount > 0

    def meals_on(self, user_id: int, day: date) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, logged_at, description, kcal, protein_g, carbs_g, fat_g, fiber_g "
                "FROM meals WHERE user_id=? AND day=? ORDER BY logged_at",
                (user_id, day.isoformat()),
            ).fetchall()
        return [dict(r) for r in rows]

    def day_totals(self, user_id: int, day: date) -> dict[str, float]:
        with self._conn() as c:
            r = c.execute(
                "SELECT COALESCE(SUM(kcal),0) kcal, COALESCE(SUM(protein_g),0) protein_g, "
                "COALESCE(SUM(carbs_g),0) carbs_g, COALESCE(SUM(fat_g),0) fat_g, COUNT(*) meals "
                "FROM meals WHERE user_id=? AND day=?",
                (user_id, day.isoformat()),
            ).fetchone()
        return {k: round(r[k], 1) for k in ("kcal", "protein_g", "carbs_g", "fat_g")} | {"meals": r["meals"]}

    # ---------------- treino ----------------
    def save_plan(self, user_id: int, plan: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO workout_plan(user_id, plan, created_at) VALUES(?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET plan=excluded.plan, created_at=excluded.created_at",
                (user_id, json.dumps(plan, ensure_ascii=False), datetime.now(UTC).isoformat()),
            )

    def get_plan(self, user_id: int) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT plan FROM workout_plan WHERE user_id=?", (user_id,)).fetchone()
        return json.loads(row["plan"]) if row else None

    def log_sets(self, user_id: int, day: date, exercise: str, load_kg: float, reps: list[int],
                 rir: float | None, decision: str, next_load: float) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO sets_log(user_id, day, exercise, load_kg, reps, rir, decision, next_load_kg) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (user_id, day.isoformat(), exercise.lower().strip(), load_kg, json.dumps(reps), rir,
                 decision, next_load),
            )

    def exercise_history(self, user_id: int, exercise: str, limit: int = 6) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT day, load_kg, reps, rir, decision, next_load_kg FROM sets_log "
                "WHERE user_id=? AND exercise=? ORDER BY id DESC LIMIT ?",
                (user_id, exercise.lower().strip(), limit),
            ).fetchall()
        return [dict(r) | {"reps": json.loads(r["reps"])} for r in rows]

    def sessions_between(self, user_id: int, start: date, end: date) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT day, exercise, load_kg, reps, rir, decision FROM sets_log "
                "WHERE user_id=? AND day BETWEEN ? AND ? ORDER BY day",
                (user_id, start.isoformat(), end.isoformat()),
            ).fetchall()
        return [dict(r) | {"reps": json.loads(r["reps"])} for r in rows]

    # ---------------- check-ins de rotina ----------------
    def log_checkin(self, user_id: int, day: date, data: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO checkins(user_id, day, data) VALUES(?,?,?)",
                (user_id, day.isoformat(), json.dumps(data, ensure_ascii=False)),
            )

    def checkins_between(self, user_id: int, start: date, end: date) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT day, data FROM checkins WHERE user_id=? AND day BETWEEN ? AND ? ORDER BY day",
                (user_id, start.isoformat(), end.isoformat()),
            ).fetchall()
        return [{"day": r["day"]} | json.loads(r["data"]) for r in rows]

    def nutrition_between(self, user_id: int, start: date, end: date) -> list[dict[str, Any]]:
        out = []
        d = start
        while d <= end:
            out.append({"day": d.isoformat()} | self.day_totals(user_id, d))
            d += timedelta(days=1)
        return out

    # ---------------- notificações (evita duplicar) ----------------
    def mark_notified(self, user_id: int, day: date, kind: str) -> bool:
        """Retorna True se marcou agora (ainda não havia sido enviada)."""
        with self._conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO notifications(user_id, day, kind) VALUES(?,?,?)",
                (user_id, day.isoformat(), kind),
            )
            return cur.rowcount > 0


def _is_plain_user(msg: dict[str, Any]) -> bool:
    if msg["role"] != "user":
        return False
    content = msg["content"]
    if isinstance(content, str):
        return True
    return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
