"""Ferramentas que o Claude pode chamar. Cada uma lê/grava no banco local.

As decisões numéricas (metas, progressão) vêm de `science.py`, para que sejam
consistentes e auditáveis.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from . import science
from .db import DB

# --------------------------------------------------------------------------- #
# Schemas (ordem fixa — mantém o cache de prompt estável)
# --------------------------------------------------------------------------- #
_EXERCISE = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Nome do exercício, ex.: 'Agachamento livre'"},
        "sets": {"type": "integer"},
        "rep_min": {"type": "integer"},
        "rep_max": {"type": "integer"},
        "rir_target": {"type": "number", "description": "Repetições em reserva alvo na última série (ex.: 1-3)"},
        "rest_seconds": {"type": "integer"},
        "load_kg": {"type": ["number", "null"], "description": "Carga inicial/atual em kg; null se ainda for testar"},
        "load_method": {
            "type": "string",
            "description": "Como achar e ajustar a carga (ex.: teste de repetições, dupla progressão por RIR)",
        },
        "lower_body_compound": {"type": "boolean", "description": "Composto de membros inferiores (incrementos maiores)"},
        "notes": {"type": "string", "description": "Técnica, cadência, amplitude, cuidados"},
    },
    "required": ["name", "sets", "rep_min", "rep_max", "rir_target", "rest_seconds", "load_method"],
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "update_profile",
        "description": (
            "Salva/atualiza dados do aluno (só os campos informados). Retorna o perfil e as metas "
            "calculadas (TMB Mifflin-St Jeor, gasto total, meta calórica e de proteína). Use sempre "
            "que o aluno informar peso, objetivo, rotina, lesões, equipamentos etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "sex": {"type": "string", "enum": ["M", "F"]},
                "age": {"type": "integer"},
                "height_cm": {"type": "number"},
                "weight_kg": {"type": "number"},
                "body_fat_pct": {"type": "number"},
                "goal": {"type": "string", "enum": ["hipertrofia", "emagrecimento", "recomposicao", "forca", "saude"]},
                "activity": {"type": "string", "enum": list(science.ACTIVITY_FACTORS)},
                "experience": {"type": "string", "enum": ["iniciante", "intermediario", "avancado"]},
                "training_days_per_week": {"type": "integer"},
                "session_minutes": {"type": "integer"},
                "equipment": {"type": "string", "description": "Academia completa, casa com halteres, etc."},
                "injuries": {"type": "string"},
                "routine": {"type": "string", "description": "Rotina: trabalho, horários, sono, estresse"},
                "food_preferences": {"type": "string"},
                "protein_target_override_g": {"type": "number", "description": "Só se o aluno/nutricionista definir outra meta"},
            },
        },
    },
    {
        "name": "get_profile",
        "description": "Lê o perfil do aluno e as metas calculadas.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "log_meal",
        "description": (
            "Registra uma refeição com a estimativa nutricional. Use depois de analisar uma foto ou "
            "descrição. Some os itens para os totais."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Ex.: 'Almoço: arroz, feijão, frango grelhado, salada'"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "grams": {"type": "number"},
                            "kcal": {"type": "number"},
                            "protein_g": {"type": "number"},
                            "carbs_g": {"type": "number"},
                            "fat_g": {"type": "number"},
                        },
                        "required": ["name", "grams", "kcal", "protein_g", "carbs_g", "fat_g"],
                    },
                },
                "kcal": {"type": "number"},
                "protein_g": {"type": "number"},
                "carbs_g": {"type": "number"},
                "fat_g": {"type": "number"},
                "fiber_g": {"type": "number"},
                "confidence": {"type": "string", "enum": ["alta", "media", "baixa"]},
                "eaten_at": {"type": "string", "description": "ISO 8601 se não foi agora (ex.: refeição de ontem)"},
            },
            "required": ["description", "items", "kcal", "protein_g", "carbs_g", "fat_g", "confidence"],
        },
    },
    {
        "name": "delete_meal",
        "description": "Apaga uma refeição registrada errada (use o id de get_day_nutrition).",
        "input_schema": {
            "type": "object",
            "properties": {"meal_id": {"type": "integer"}},
            "required": ["meal_id"],
        },
    },
    {
        "name": "get_day_nutrition",
        "description": "Refeições, totais do dia e quanto falta para as metas (kcal e proteína).",
        "input_schema": {
            "type": "object",
            "properties": {"day": {"type": "string", "description": "YYYY-MM-DD; omita para hoje"}},
        },
    },
    {
        "name": "save_workout_plan",
        "description": (
            "Salva o programa de treino completo (substitui o anterior). Cada exercício precisa de "
            "séries, faixa de repetições, RIR alvo, descanso, carga e método de carga."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "split": {"type": "string", "description": "Ex.: Upper/Lower 4x, Full body 3x"},
                "weeks": {"type": "integer"},
                "rationale": {"type": "string", "description": "Justificativa científica resumida"},
                "deload": {"type": "string", "description": "Quando/como fazer deload"},
                "days": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "exercises": {"type": "array", "items": _EXERCISE},
                        },
                        "required": ["name", "exercises"],
                    },
                },
            },
            "required": ["name", "split", "rationale", "days"],
        },
    },
    {
        "name": "get_workout_plan",
        "description": "Lê o programa de treino atual com as cargas atualizadas.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "log_exercise",
        "description": (
            "Registra as séries feitas de um exercício e retorna a decisão de progressão (aumentar, "
            "manter ou reduzir a carga), calculada por dupla progressão + RIR. Atualiza a carga no plano."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exercise": {"type": "string"},
                "load_kg": {"type": "number"},
                "reps": {"type": "array", "items": {"type": "integer"}, "description": "Reps de cada série"},
                "rir_last_set": {"type": "number", "description": "Reps que sobrariam na última série"},
                "day": {"type": "string", "description": "YYYY-MM-DD; omita para hoje"},
            },
            "required": ["exercise", "load_kg", "reps"],
        },
    },
    {
        "name": "exercise_history",
        "description": "Histórico recente de cargas/reps de um exercício.",
        "input_schema": {
            "type": "object",
            "properties": {"exercise": {"type": "string"}},
            "required": ["exercise"],
        },
    },
    {
        "name": "estimate_start_load",
        "description": (
            "Calcula carga de trabalho a partir de um teste (carga x reps perto da falha), via 1RM "
            "estimado de Epley ajustado pelo RIR alvo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "test_load_kg": {"type": "number"},
                "test_reps": {"type": "integer"},
                "target_reps": {"type": "integer"},
                "target_rir": {"type": "number"},
            },
            "required": ["test_load_kg", "test_reps", "target_reps"],
        },
    },
    {
        "name": "log_checkin",
        "description": (
            "Registra dados de rotina do dia: sono, passos, energia, estresse, dor muscular, peso. "
            "Use sempre que o aluno contar algo sobre o dia dele."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sleep_hours": {"type": "number"},
                "sleep_quality": {"type": "integer", "description": "1-5"},
                "steps": {"type": "integer"},
                "energy": {"type": "integer", "description": "1-5"},
                "stress": {"type": "integer", "description": "1-5"},
                "soreness": {"type": "integer", "description": "1-5"},
                "bodyweight_kg": {"type": "number"},
                "water_l": {"type": "number"},
                "alcohol_doses": {"type": "number"},
                "notes": {"type": "string"},
            },
        },
    },
    {
        "name": "get_period_summary",
        "description": (
            "Resumo dos últimos N dias: nutrição diária vs metas, treinos registrados, check-ins "
            "(sono, passos, peso). Use para dar feedback sobre a rotina."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Padrão 7"}},
        },
    },
]


# --------------------------------------------------------------------------- #
# Execução
# --------------------------------------------------------------------------- #
def compute_targets(profile: dict[str, Any]) -> dict[str, Any]:
    needed = ("weight_kg", "height_cm", "age", "sex", "goal")
    missing = [k for k in needed if not profile.get(k)]
    if missing:
        return {"missing_for_targets": missing}
    w, h, a, s, goal = (profile[k] for k in needed)
    activity = profile.get("activity", "moderado")
    bmr = science.bmr_mifflin(w, h, a, s)
    total = science.tdee(w, h, a, s, activity)
    kcal = science.calorie_target(total, goal)
    prot = science.protein_target(w, goal, profile.get("body_fat_pct"))
    protein_g = profile.get("protein_target_override_g") or prot.grams_per_day
    return {
        "bmr_kcal": round(bmr),
        "tdee_kcal": round(total),
        "kcal_target": round(kcal),
        "protein_target_g": round(protein_g),
        "protein_g_per_kg": round(protein_g / w, 2),
        "protein_per_meal_g": prot.per_meal_g,
        "protein_meals": prot.meals,
        "protein_rationale": prot.rationale,
        "fat_min_g": round(w * 0.6),  # ~0,5-1 g/kg mínimo para saúde hormonal
    }


class ToolExecutor:
    def __init__(self, db: DB, user_id: int, now: datetime):
        self.db = db
        self.user_id = user_id
        self.now = now
        self.today = now.date()

    def run(self, name: str, args: dict[str, Any]) -> str:
        fn = getattr(self, f"_t_{name}", None)
        if fn is None:
            raise ValueError(f"Ferramenta desconhecida: {name}")
        return json.dumps(fn(**args), ensure_ascii=False, default=str)

    def _day(self, s: str | None) -> date:
        return date.fromisoformat(s) if s else self.today

    # perfil
    def _t_update_profile(self, **fields: Any) -> dict[str, Any]:
        prof = self.db.update_profile(self.user_id, fields)
        if "weight_kg" in fields:
            self.db.log_checkin(self.user_id, self.today, {"bodyweight_kg": fields["weight_kg"]})
        return {"profile": prof, "targets": compute_targets(prof)}

    def _t_get_profile(self) -> dict[str, Any]:
        prof = self.db.get_profile(self.user_id)
        return {"profile": prof, "targets": compute_targets(prof)}

    # nutrição
    def _t_log_meal(self, eaten_at: str | None = None, **meal: Any) -> dict[str, Any]:
        when = datetime.fromisoformat(eaten_at) if eaten_at else self.now
        meal_id = self.db.log_meal(self.user_id, when.date(), when, meal)
        out = self._t_get_day_nutrition(when.date().isoformat())
        out["meal_id"] = meal_id
        return out

    def _t_delete_meal(self, meal_id: int) -> dict[str, Any]:
        return {"deleted": self.db.delete_meal(self.user_id, meal_id)}

    def _t_get_day_nutrition(self, day: str | None = None) -> dict[str, Any]:
        d = self._day(day)
        totals = self.db.day_totals(self.user_id, d)
        targets = compute_targets(self.db.get_profile(self.user_id))
        out: dict[str, Any] = {"day": d.isoformat(), "meals": self.db.meals_on(self.user_id, d), "totals": totals}
        if "protein_target_g" in targets:
            out["targets"] = {"kcal": targets["kcal_target"], "protein_g": targets["protein_target_g"]}
            out["remaining"] = {
                "kcal": round(targets["kcal_target"] - totals["kcal"]),
                "protein_g": round(targets["protein_target_g"] - totals["protein_g"]),
            }
        return out

    # treino
    def _t_save_workout_plan(self, **plan: Any) -> dict[str, Any]:
        self.db.save_plan(self.user_id, plan)
        return {"saved": True, "days": len(plan.get("days", []))}

    def _t_get_workout_plan(self) -> dict[str, Any]:
        return self.db.get_plan(self.user_id) or {"plan": None}

    def _find_exercise(self, plan: dict[str, Any] | None, exercise: str) -> dict[str, Any] | None:
        if not plan:
            return None
        key = exercise.lower().strip()
        for d in plan.get("days", []):
            for ex in d.get("exercises", []):
                if ex["name"].lower().strip() == key:
                    return ex
        for d in plan.get("days", []):  # correspondência parcial
            for ex in d.get("exercises", []):
                if key in ex["name"].lower() or ex["name"].lower() in key:
                    return ex
        return None

    def _t_log_exercise(self, exercise: str, load_kg: float, reps: list[int],
                        rir_last_set: float | None = None, day: str | None = None) -> dict[str, Any]:
        plan = self.db.get_plan(self.user_id)
        ex = self._find_exercise(plan, exercise)
        rep_min, rep_max = (ex["rep_min"], ex["rep_max"]) if ex else (8, 12)
        rir_target = ex.get("rir_target", 2) if ex else 2
        lower = bool(ex.get("lower_body_compound")) if ex else False
        name = ex["name"] if ex else exercise

        hist = self.db.exercise_history(self.user_id, name, limit=1)
        prev = hist[0] if hist else None
        prev_top = bool(prev and prev["load_kg"] == load_kg and all(r >= rep_max for r in prev["reps"]))
        prev_below = bool(prev and prev["load_kg"] == load_kg and any(r < rep_min for r in prev["reps"]))

        dec = science.progression(
            load_kg, reps, rep_min, rep_max, rir_last_set, rir_target,
            lower_body_compound=lower, previous_session_hit_top=prev_top,
            previous_session_below_min=prev_below,
        )
        self.db.log_sets(self.user_id, self._day(day), name, load_kg, reps, rir_last_set, dec.action, dec.next_load_kg)
        if ex is not None and plan is not None:
            ex["load_kg"] = dec.next_load_kg
            self.db.save_plan(self.user_id, plan)
        return {
            "exercise": name,
            "rep_range": [rep_min, rep_max],
            "rir_target": rir_target,
            "e1rm_kg": round(science.e1rm(load_kg, max(reps), rir_last_set or 0), 1),
            "decision": dec.action,
            "next_load_kg": dec.next_load_kg,
            "message": dec.message,
            "in_plan": ex is not None,
        }

    def _t_exercise_history(self, exercise: str) -> dict[str, Any]:
        ex = self._find_exercise(self.db.get_plan(self.user_id), exercise)
        name = ex["name"] if ex else exercise
        return {"exercise": name, "history": self.db.exercise_history(self.user_id, name)}

    def _t_estimate_start_load(self, test_load_kg: float, test_reps: int, target_reps: int,
                               target_rir: float = 2) -> dict[str, Any]:
        return {
            "e1rm_kg": round(science.e1rm(test_load_kg, test_reps), 1),
            "working_load_kg": science.starting_load_from_test(test_load_kg, test_reps, target_reps, target_rir),
        }

    # rotina
    def _t_log_checkin(self, **data: Any) -> dict[str, Any]:
        self.db.log_checkin(self.user_id, self.today, data)
        if data.get("bodyweight_kg"):
            self.db.update_profile(self.user_id, {"weight_kg": data["bodyweight_kg"]})
        return {"saved": True}

    def _t_get_period_summary(self, days: int = 7) -> dict[str, Any]:
        return period_summary(self.db, self.user_id, self.today, days)


def period_summary(db: DB, user_id: int, today: date, days: int = 7) -> dict[str, Any]:
    start = today - timedelta(days=days - 1)
    prof = db.get_profile(user_id)
    targets = compute_targets(prof)
    nutrition = db.nutrition_between(user_id, start, today)
    logged = [n for n in nutrition if n["meals"]]
    summary: dict[str, Any] = {
        "period": [start.isoformat(), today.isoformat()],
        "targets": targets,
        "nutrition_daily": nutrition,
        "training_sets": db.sessions_between(user_id, start, today),
        "checkins": db.checkins_between(user_id, start, today),
        "plan_days_per_week": prof.get("training_days_per_week"),
    }
    if logged and "protein_target_g" in targets:
        avg_p = sum(n["protein_g"] for n in logged) / len(logged)
        avg_k = sum(n["kcal"] for n in logged) / len(logged)
        summary["averages_on_logged_days"] = {
            "days_logged": len(logged),
            "protein_g": round(avg_p),
            "kcal": round(avg_k),
            "days_protein_target_hit": sum(n["protein_g"] >= 0.9 * targets["protein_target_g"] for n in logged),
        }
    summary["training_days_logged"] = len({s["day"] for s in summary["training_sets"]})
    return summary
