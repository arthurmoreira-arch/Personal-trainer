"""Lembretes de proteína — lógica determinística, sem custo de API."""

from __future__ import annotations

from datetime import datetime

from .db import DB
from .tools import compute_targets

# (alimento, porção, proteína em g) — valores aproximados TACO/USDA
PROTEIN_FOODS = [
    ("peito de frango grelhado", "150 g", 45),
    ("atum em lata (drenado)", "1 lata, 120 g", 30),
    ("whey protein", "1 dose, 30 g", 24),
    ("iogurte grego/skyr natural", "1 pote, 170 g", 17),
    ("ovos", "3 unidades", 18),
    ("carne moída magra", "120 g", 32),
    ("queijo cottage", "100 g", 11),
    ("leite", "1 copo, 300 ml", 10),
]

DAY_START_H, DAY_END_H = 7, 22


def expected_fraction(now: datetime) -> float:
    """Fração da meta de proteína que 'deveria' estar consumida até agora,
    assumindo distribuição uniforme em ≥4 refeições (Schoenfeld & Aragon 2018)."""
    h = now.hour + now.minute / 60
    return min(1.0, max(0.0, (h - DAY_START_H) / (DAY_END_H - DAY_START_H)))


def suggestions(remaining_g: float) -> list[str]:
    out, left = [], remaining_g
    for name, portion, p in PROTEIN_FOODS:
        if left <= 0 or len(out) >= 3:
            break
        if p <= left + 10:
            out.append(f"• {portion} de {name} (~{p} g)")
            left -= p
    if not out:
        name, portion, p = PROTEIN_FOODS[3]
        out.append(f"• {portion} de {name} (~{p} g)")
    return out


def protein_check(db: DB, user_id: int, now: datetime, slot: str) -> str | None:
    """Mensagem de alerta, ou None se está em dia (ou já avisou neste horário)."""
    targets = compute_targets(db.get_profile(user_id))
    if "protein_target_g" not in targets:
        return None
    goal = targets["protein_target_g"]
    totals = db.day_totals(user_id, now.date())
    eaten = totals["protein_g"]
    expected = goal * expected_fraction(now)
    remaining = goal - eaten

    late_in_day = expected_fraction(now) >= 0.85
    behind = eaten < 0.85 * expected and (expected - eaten) >= 15
    if not behind and not (late_in_day and remaining >= 15):
        return None
    if not db.mark_notified(user_id, now.date(), f"protein-{slot}"):
        return None

    if totals["meals"] == 0:
        return (
            f"⏰ Ainda não tem nenhuma refeição registrada hoje. Manda foto ou descrição do que "
            f"comeu para eu acompanhar sua proteína (meta: {goal} g)."
        )

    lines = [
        f"⚠️ Proteína do dia: {eaten:.0f} g de {goal} g — faltam {remaining:.0f} g.",
    ]
    if not late_in_day:
        lines.append(f"Até agora o ideal seria ~{expected:.0f} g. Tente ~{targets['protein_per_meal_g']} g na próxima refeição.")
    lines.append("Opções para fechar a conta:")
    lines += suggestions(remaining)
    lines.append("(Ingestão ≥1,6 g/kg/dia maximiza ganho de massa magra — Morton et al., 2018.)")
    return "\n".join(lines)
