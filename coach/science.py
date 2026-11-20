"""Cálculos determinísticos com base científica.

Tudo que é número (metas de proteína, gasto calórico, progressão de carga)
é calculado aqui, em código, e não "inventado" pelo modelo. O Claude usa
esses resultados para conversar e montar treinos.

Referências (ver README para a lista completa):
- Mifflin MD et al. (1990) Am J Clin Nutr 51:241-7 — equação de TMB.
- Morton RW et al. (2018) Br J Sports Med 52:376-84 — meta-análise:
  ganho de massa magra estabiliza ~1,6 g/kg/dia (IC 95% até ~2,2 g/kg).
- Helms ER et al. (2014) JISSN 11:20 — em déficit, 2,3-3,1 g/kg de massa
  magra; perda de 0,5-1,0% do peso/semana.
- Schoenfeld BJ & Aragon AA (2018) JISSN 15:10 — ~0,4 g/kg por refeição
  em ≥4 refeições para maximizar síntese proteica.
- Iraki J et al. (2019) Sports 7:154 — superávit ~10-20% para ganho de massa
  em praticantes (ganho ~0,25-0,5% do peso/semana).
- Zourdos MC et al. (2016) JSCR 30:267-75 — escala RPE baseada em RIR.
- Baechle TR & Earle RW (NSCA, Essentials of S&C) — regra "2 por 2" e
  incrementos de carga de ~2-10%.
- ACSM (2009) Med Sci Sports Exerc 41:687-708 — progressão de 2-10% quando
  o praticante supera a faixa de repetições alvo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

Sex = Literal["M", "F"]
Goal = Literal["hipertrofia", "emagrecimento", "recomposicao", "forca", "saude"]

ACTIVITY_FACTORS = {
    "sedentario": 1.2,
    "leve": 1.375,
    "moderado": 1.55,
    "alto": 1.725,
    "muito_alto": 1.9,
}


# --------------------------------------------------------------------------- #
# Energia
# --------------------------------------------------------------------------- #
def bmr_mifflin(weight_kg: float, height_cm: float, age: int, sex: Sex) -> float:
    """Taxa metabólica basal — Mifflin-St Jeor (1990)."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + (5 if sex == "M" else -161)


def tdee(weight_kg: float, height_cm: float, age: int, sex: Sex, activity: str) -> float:
    return bmr_mifflin(weight_kg, height_cm, age, sex) * ACTIVITY_FACTORS.get(activity, 1.55)


def calorie_target(tdee_kcal: float, goal: str) -> float:
    """Meta calórica diária.

    - emagrecimento: déficit ~20% (≈0,5-1% do peso/semana; Helms 2014)
    - hipertrofia: superávit ~10% (Iraki 2019)
    - recomposição/força/saúde: manutenção (força: leve superávit de 5%)
    """
    factor = {
        "emagrecimento": 0.80,
        "hipertrofia": 1.10,
        "forca": 1.05,
        "recomposicao": 1.00,
        "saude": 1.00,
    }.get(goal, 1.0)
    return tdee_kcal * factor


# --------------------------------------------------------------------------- #
# Proteína
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProteinTarget:
    grams_per_day: float
    g_per_kg: float
    per_meal_g: float
    meals: int
    rationale: str


def protein_target(weight_kg: float, goal: str, body_fat_pct: float | None = None) -> ProteinTarget:
    """Meta de proteína diária.

    - Padrão (hipertrofia/força/recomposição): 1,6-2,2 g/kg → usamos 2,0 g/kg,
      acima do ponto de saturação de 1,62 g/kg de Morton 2018 com margem.
    - Emagrecimento: 2,3-3,1 g/kg de massa magra (Helms 2014). Se o % de gordura
      é conhecido usamos 2,6 g/kg de massa magra; senão 2,2 g/kg do peso total.
    - Saúde geral: 1,2-1,6 g/kg → 1,4 g/kg.
    Distribuição: ~0,4 g/kg por refeição em ≥4 refeições (Schoenfeld & Aragon 2018).
    """
    if goal == "emagrecimento":
        if body_fat_pct:
            lean = weight_kg * (1 - body_fat_pct / 100)
            grams = lean * 2.6
            why = "2,6 g/kg de massa magra em déficit (Helms et al., 2014)"
        else:
            grams = weight_kg * 2.2
            why = "2,2 g/kg em déficit para preservar massa magra (Helms 2014; Morton 2018)"
    elif goal == "saude":
        grams = weight_kg * 1.4
        why = "1,4 g/kg para saúde geral e treino (posicionamento ISSN, Jäger et al., 2017)"
    else:
        grams = weight_kg * 2.0
        why = "2,0 g/kg — acima do platô de 1,62 g/kg da meta-análise de Morton et al. (2018)"
    per_meal = weight_kg * 0.4
    meals = max(4, round(grams / per_meal)) if per_meal else 4
    return ProteinTarget(
        grams_per_day=round(grams),
        g_per_kg=round(grams / weight_kg, 2),
        per_meal_g=round(per_meal),
        meals=meals,
        rationale=why,
    )


# --------------------------------------------------------------------------- #
# Progressão de carga
# --------------------------------------------------------------------------- #
def e1rm(load_kg: float, reps: int, rir: float = 0) -> float:
    """1RM estimado (Epley) ajustado por RIR: reps "possíveis" = reps + RIR."""
    return load_kg * (1 + (reps + rir) / 30)


def _round_to(x: float, step: float) -> float:
    return round(round(x / step) * step, 2)


@dataclass(frozen=True)
class ProgressionDecision:
    action: Literal["aumentar", "manter", "reduzir"]
    next_load_kg: float
    message: str


def progression(
    current_load_kg: float,
    reps_done: Sequence[int],
    rep_min: int,
    rep_max: int,
    rir_last_set: float | None,
    rir_target: float = 2,
    lower_body_compound: bool = False,
    previous_session_hit_top: bool = False,
    previous_session_below_min: bool = False,
    plate_step_kg: float = 1.0,
) -> ProgressionDecision:
    """Dupla progressão com autorregulação por RIR.

    Regras:
    1. Se TODAS as séries atingiram rep_max e o RIR da última série ≥ (alvo - 1)
       → aumentar carga. Compostos de membros inferiores: +5% (mín 2,5 kg);
       demais: +2,5% (mín 1 kg). (ACSM 2009: 2-10%.)
       Se já foi assim na sessão anterior também ("2 por 2" da NSCA), o aumento
       é recomendado com mais confiança.
    2. Se alguma série ficou abaixo de rep_min em duas sessões seguidas → reduzir
       ~7,5% (fadiga acumulada / carga excessiva).
    3. Caso contrário → manter a carga e buscar +1 repetição nas séries.
    """
    if not reps_done:
        return ProgressionDecision("manter", current_load_kg, "Sem séries registradas.")

    all_top = all(r >= rep_max for r in reps_done)
    any_below = any(r < rep_min for r in reps_done)
    rir_ok = rir_last_set is None or rir_last_set >= rir_target - 1

    if all_top and rir_ok:
        pct, minimum = (0.05, 2.5) if lower_body_compound else (0.025, 1.0)
        inc = max(current_load_kg * pct, minimum)
        nxt = _round_to(current_load_kg + inc, plate_step_kg)
        if nxt <= current_load_kg:
            nxt = current_load_kg + plate_step_kg
        confidence = (
            "2ª sessão seguida no topo da faixa (regra 2-por-2 da NSCA)"
            if previous_session_hit_top
            else "todas as séries no topo da faixa com RIR adequado"
        )
        return ProgressionDecision(
            "aumentar",
            nxt,
            f"Aumente para {nxt:g} kg na próxima sessão — {confidence}. "
            f"Volte ao início da faixa ({rep_min} reps) e suba de novo.",
        )

    if any_below and previous_session_below_min:
        nxt = _round_to(current_load_kg * 0.925, plate_step_kg)
        return ProgressionDecision(
            "reduzir",
            nxt,
            f"Reduza para {nxt:g} kg: duas sessões abaixo de {rep_min} reps indicam carga "
            "excessiva ou fadiga acumulada. Confira sono, alimentação e técnica.",
        )

    if all_top and not rir_ok:
        msg = (
            f"Você bateu {rep_max} reps mas perto da falha (RIR {rir_last_set:g}). "
            f"Mantenha {current_load_kg:g} kg até fazer com RIR ≥ {rir_target - 1:g}."
        )
    else:
        msg = (
            f"Mantenha {current_load_kg:g} kg e tente +1 repetição por série "
            f"até chegar a {rep_max} em todas."
        )
    return ProgressionDecision("manter", current_load_kg, msg)


def starting_load_from_test(test_load_kg: float, test_reps: int, target_reps: int, target_rir: float = 2) -> float:
    """Carga inicial a partir de um teste de repetições (Epley invertido).

    Ex.: fez 60 kg x 10 até perto da falha → e1RM ≈ 80 kg. Para 8 reps com RIR 2
    (= 10 reps possíveis) → 80 / (1 + 10/30) = 60 kg.
    """
    est = e1rm(test_load_kg, test_reps, 0)
    return round(est / (1 + (target_reps + target_rir) / 30), 1)
