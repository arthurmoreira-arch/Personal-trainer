"""Bot do Telegram: recebe texto e fotos, envia lembretes e feedback semanal."""

from __future__ import annotations

import logging
from datetime import datetime, time as dtime

import anthropic
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .agent import Coach
from .config import CONFIG
from .db import DB
from .prompts import WEEKLY_FEEDBACK_REQUEST
from .reminders import protein_check

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("coach")

TG_LIMIT = 4000

HELP = (
    "Sou seu personal trainer 🏋️\n\n"
    "• Me conte seus objetivos e eu monto seu treino com carga e método de progressão.\n"
    "• Mande FOTO do prato (ou descreva) e eu estimo kcal, proteína, carbo e gordura.\n"
    "• Depois do treino, mande algo como: \"supino 60kg 10,9,8 sobrou 1\" — eu registro e digo quando subir a carga.\n"
    "• Conte sobre sono, passos, peso, estresse — uso isso no seu feedback.\n\n"
    "Comandos:\n"
    "/hoje — nutrição do dia\n"
    "/treino — seu programa atual\n"
    "/feedback — análise da sua semana\n"
    "/perfil — seus dados e metas\n"
    "/novaconversa — limpa o histórico da conversa (seus dados ficam salvos)"
)


def allowed(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    return uid is not None and (not CONFIG.allowed_user_ids or uid in CONFIG.allowed_user_ids)


async def send_long(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    while text:
        if len(text) <= TG_LIMIT:
            cut = text
        else:
            idx = text.rfind("\n", 0, TG_LIMIT)
            cut = text[: idx if idx > 0 else TG_LIMIT]
        await context.bot.send_message(chat_id, cut)
        text = text[len(cut):].lstrip("\n")


async def run_coach(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str | None,
                    image: bytes | None = None) -> None:
    if not allowed(update):
        await update.effective_message.reply_text(
            f"Acesso não autorizado. Seu ID do Telegram é {update.effective_user.id} — "
            "adicione-o em ALLOWED_USER_IDS no .env."
        )
        return
    coach: Coach = context.application.bot_data["coach"]
    db: DB = context.application.bot_data["db"]
    uid = update.effective_user.id
    db.update_profile(uid, {"chat_id": update.effective_chat.id})
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    try:
        reply = await coach.chat(uid, text, image)
    except anthropic.RateLimitError:
        reply = "Muitas requisições agora. Tente de novo em um minuto."
    except anthropic.APIConnectionError:
        reply = "Não consegui falar com o servidor da IA. Tente de novo em instantes."
    except anthropic.AuthenticationError:
        reply = "Erro 401: a ANTHROPIC_API_KEY é inválida. Confira a chave no Railway."
    except anthropic.APIStatusError as e:
        log.exception("API error")
        detail = getattr(e, "message", "") or str(e)
        if "credit balance" in detail.lower():
            reply = ("Erro 400: sua conta da Anthropic está sem créditos. Adicione créditos em "
                     "console.anthropic.com → Billing.")
        else:
            reply = f"Erro na API ({e.status_code}): {detail[:500]}"
    await send_long(context, update.effective_chat.id, reply)


# ----------------------------- handlers -----------------------------------
async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if allowed(update):
        await update.message.reply_text(HELP)
    await run_coach(update, context, "Acabei de iniciar o bot. Se apresente rapidamente e, se meu perfil "
                                     "estiver incompleto, comece a coletar meus dados e objetivos.")


async def on_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_coach(update, context, update.message.text)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if msg.photo:
        file = await msg.photo[-1].get_file()  # maior resolução
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        file = await msg.document.get_file()
    else:
        return
    data = bytes(await file.download_as_bytearray())
    await run_coach(update, context, msg.caption, data)


async def on_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_coach(update, context, "/hoje — mostre minha nutrição de hoje (refeições, totais, quanto falta).")


async def on_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_coach(update, context, "/treino — mostre meu programa atual com as cargas. Se não tiver, "
                                     "pergunte o necessário para montar um.")


async def on_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_coach(update, context, "/feedback — analise minha última semana e diga o que está "
                                     "atrapalhando meus objetivos.")


async def on_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_coach(update, context, "/perfil — mostre meus dados e metas calculadas, com a justificativa.")


async def on_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    context.application.bot_data["db"].clear_messages(update.effective_user.id)
    await update.message.reply_text("Histórico da conversa limpo. Perfil, treinos e refeições continuam salvos.")


# ----------------------------- jobs ---------------------------------------
async def job_protein(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = context.application.bot_data["db"]
    coach: Coach = context.application.bot_data["coach"]
    slot = context.job.data
    now = datetime.now(CONFIG.tz).replace(tzinfo=None)
    for uid in db.all_user_ids():
        chat_id = db.get_profile(uid).get("chat_id")
        if not chat_id:
            continue
        msg = protein_check(db, uid, now, slot)
        if msg:
            await context.bot.send_message(chat_id, msg)
            coach.note_proactive(uid, msg)


async def job_weekly(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = context.application.bot_data["db"]
    coach: Coach = context.application.bot_data["coach"]
    for uid in db.all_user_ids():
        chat_id = db.get_profile(uid).get("chat_id")
        if not chat_id:
            continue
        try:
            reply = await coach.chat(uid, WEEKLY_FEEDBACK_REQUEST)
            await send_long(context, chat_id, "📊 Feedback semanal\n\n" + reply)
        except anthropic.APIError:
            log.exception("weekly feedback failed for %s", uid)


def _hm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m), tzinfo=CONFIG.tz)


def build_app() -> Application:
    if not CONFIG.telegram_token:
        raise SystemExit("Defina TELEGRAM_BOT_TOKEN no .env")
    if not CONFIG.allowed_user_ids:
        log.warning("ALLOWED_USER_IDS vazio: qualquer pessoa que achar o bot poderá usá-lo (e gastar sua API).")
    db = DB(CONFIG.db_path)
    app = Application.builder().token(CONFIG.telegram_token).build()
    app.bot_data["db"] = db
    app.bot_data["coach"] = Coach(db)

    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler(["ajuda", "help"], on_help))
    app.add_handler(CommandHandler("hoje", on_today))
    app.add_handler(CommandHandler("treino", on_plan))
    app.add_handler(CommandHandler("feedback", on_feedback))
    app.add_handler(CommandHandler("perfil", on_profile))
    app.add_handler(CommandHandler("novaconversa", on_reset))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    jq = app.job_queue
    for t in CONFIG.protein_check_times:
        jq.run_daily(job_protein, _hm(t), data=t, name=f"protein-{t}")
    # python-telegram-bot usa 0=domingo; a config usa 0=segunda (padrão do Python)
    ptb_day = (CONFIG.weekly_feedback_day + 1) % 7
    jq.run_daily(job_weekly, _hm(CONFIG.weekly_feedback_time), days=(ptb_day,), name="weekly")
    return app


def main() -> None:
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
