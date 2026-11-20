import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from coach import science
from coach.agent import Coach
from coach.db import DB
from coach.reminders import protein_check
from coach.tools import ToolExecutor


@pytest.fixture
def db(tmp_path):
    return DB(str(tmp_path / "t.db"))


PROFILE = dict(sex="M", age=30, height_cm=178, weight_kg=80, goal="hipertrofia", activity="moderado")


def test_mifflin():
    # 10*80 + 6.25*178 - 5*30 + 5 = 1767.5
    assert science.bmr_mifflin(80, 178, 30, "M") == pytest.approx(1767.5)


def test_protein_targets():
    assert science.protein_target(80, "hipertrofia").grams_per_day == 160
    assert science.protein_target(80, "emagrecimento").grams_per_day == 176
    assert science.protein_target(80, "emagrecimento", body_fat_pct=25).grams_per_day == 156


def test_progression_increase_lower_body():
    d = science.progression(100, [10, 10, 10], 6, 10, rir_last_set=2, lower_body_compound=True)
    assert d.action == "aumentar" and d.next_load_kg == 105


def test_progression_increase_upper_min_step():
    d = science.progression(20, [12, 12, 12], 8, 12, rir_last_set=2)
    assert d.action == "aumentar" and d.next_load_kg == 21


def test_progression_hold_when_near_failure():
    d = science.progression(60, [10, 10, 10], 6, 10, rir_last_set=0, rir_target=2)
    assert d.action == "manter"


def test_progression_reduce_after_two_bad_sessions():
    d = science.progression(80, [5, 4, 4], 6, 10, rir_last_set=0, previous_session_below_min=True)
    assert d.action == "reduzir" and d.next_load_kg < 80


def test_start_load():
    assert science.starting_load_from_test(60, 10, 8, 2) == pytest.approx(60, abs=0.5)


def test_log_exercise_updates_plan(db):
    ex = ToolExecutor(db, 1, datetime(2026, 11, 20, 18, 0))
    ex.run("save_workout_plan", {
        "name": "Upper/Lower", "split": "UL 4x", "rationale": "x",
        "days": [{"name": "Lower A", "exercises": [{
            "name": "Agachamento livre", "sets": 3, "rep_min": 6, "rep_max": 10, "rir_target": 2,
            "rest_seconds": 180, "load_kg": 100, "load_method": "dupla progressão",
            "lower_body_compound": True}]}],
    })
    out = json.loads(ex.run("log_exercise", {"exercise": "agachamento", "load_kg": 100,
                                             "reps": [10, 10, 10], "rir_last_set": 2}))
    assert out["decision"] == "aumentar" and out["next_load_kg"] == 105
    assert db.get_plan(1)["days"][0]["exercises"][0]["load_kg"] == 105


def test_meals_and_protein_reminder(db):
    db.update_profile(1, PROFILE)
    ex = ToolExecutor(db, 1, datetime(2026, 11, 20, 13, 0))
    out = json.loads(ex.run("log_meal", {
        "description": "almoço", "items": [], "kcal": 600, "protein_g": 30,
        "carbs_g": 70, "fat_g": 15, "confidence": "media"}))
    assert out["remaining"]["protein_g"] == 130
    msg = protein_check(db, 1, datetime(2026, 11, 20, 20, 30), "20:30")
    assert msg and "faltam 130 g" in msg
    # não repete no mesmo horário
    assert protein_check(db, 1, datetime(2026, 11, 20, 20, 30), "20:30") is None


def test_history_starts_with_plain_user(db):
    db.append_message(1, "assistant", [{"type": "tool_use", "id": "a", "name": "x", "input": {}}])
    db.append_message(1, "user", [{"type": "tool_result", "tool_use_id": "a", "content": "{}"}])
    db.append_message(1, "user", [{"type": "text", "text": "oi"}])
    msgs = db.recent_messages(1, 10)
    assert msgs[0]["content"][0]["text"] == "oi"


class FakeMessages:
    """Simula a API: 1ª resposta chama uma ferramenta, 2ª responde em texto."""

    def __init__(self):
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            return SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="thinking", thinking="", signature="s",
                                model_dump=lambda **_: {"type": "thinking", "thinking": "", "signature": "s"}),
                SimpleNamespace(type="tool_use", id="tu1", name="update_profile", input=PROFILE,
                                model_dump=lambda **_: {"type": "tool_use", "id": "tu1",
                                                        "name": "update_profile", "input": PROFILE}),
            ])
        return SimpleNamespace(stop_reason="end_turn", content=[
            SimpleNamespace(type="text", text="Perfil salvo! Meta: 160 g de proteína.",
                            model_dump=lambda **_: {"type": "text", "text": "Perfil salvo! Meta: 160 g de proteína."}),
        ])


@pytest.mark.asyncio
async def test_coach_loop(db):
    fake = FakeMessages()
    client = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    coach = Coach(db, client=client)
    reply = await coach.chat(1, "tenho 30 anos, 80kg, 178cm, quero hipertrofia")
    assert "160 g" in reply
    assert db.get_profile(1)["weight_kg"] == 80
    stored = db.recent_messages(1, 50)
    assert [m["role"] for m in stored] == ["user", "assistant", "user", "assistant"]
    # thinking não é persistido
    assert all(b["type"] != "thinking" for m in stored for b in m["content"])
    # 2ª chamada levou o resultado da ferramenta
    assert fake.calls[1]["messages"][-1]["content"][0]["type"] == "tool_result"
