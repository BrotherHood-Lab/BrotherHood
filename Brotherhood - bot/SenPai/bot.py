"""
Brotherhood SenPai — бот учёта результатов тренировок.

Любой участник записывает сегодняшний результат по упражнению прямо в
Supabase (таблица exercise_logs) — оттуда его сразу подхватывает личный
кабинет (nutrition.thebrotherhoodclub.com/training/): разряд, стрик и
тренд считаются уже на сайте, здесь дублируется только простая сводка.

Команды:
  /start  — знакомство: кто это и что делает
  /today  — сводка на сегодня + кнопки прямо под сообщением, чтобы отметить результат
  /stats  — сводка по всем упражнениям за всё время
  /cancel — отменить текущую запись
"""

import os
import logging
from datetime import datetime, timezone, timedelta

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

TZ = timezone(timedelta(hours=7))  # Таиланд, как и в остальном проекте

SITE_URL = "https://thebrotherhoodclub.com/"
CABINET_URL = "https://nutrition.thebrotherhoodclub.com/training/"


def seq_from(start, step, count):
    return [start + step * i for i in range(count)]


# Зеркало EXERCISE_CONFIG из training/index.html — держать в соответствии,
# иначе разряды в боте и на сайте разъедутся.
EXERCISE_CONFIG = {
    "pushups": {
        "label": "Отжимания", "unit": "раз",
        "milestones": seq_from(20, 10, 15),
        "ranks": [(0, "Новичок"), (20, "Ученик"), (30, "Воин"), (40, "Ронин"),
                  (50, "Самурай"), (70, "Мастер"), (100, "Легенда додзё")],
    },
    "pullups": {
        "label": "Подтягивания", "unit": "раз",
        "milestones": seq_from(10, 5, 15),
        "ranks": [(0, "Новичок"), (5, "Ученик"), (10, "Воин"), (15, "Ронин"),
                  (20, "Самурай"), (25, "Мастер"), (30, "Легенда додзё")],
    },
    "squats": {
        "label": "Приседания", "unit": "раз",
        "milestones": seq_from(20, 10, 15),
        "ranks": [(0, "Новичок"), (20, "Ученик"), (30, "Воин"), (40, "Ронин"),
                  (50, "Самурай"), (70, "Мастер"), (100, "Легенда додзё")],
    },
    "plank": {
        "label": "Планка", "unit": "сек",
        "milestones": seq_from(60, 30, 15),
        "ranks": [(0, "Новичок"), (60, "Ученик"), (90, "Воин"), (120, "Ронин"),
                  (150, "Самурай"), (210, "Мастер"), (300, "Легенда додзё")],
    },
    "ladder": {
        "label": "Лесенка", "unit": "ступень", "is_ladder": True, "max": 10,
        "ranks": [(1, "Новичок"), (4, "Ученик"), (6, "Воин"), (8, "Ронин"), (10, "Мастер Лесенки")],
    },
}
EXERCISE_ORDER = ["pushups", "pullups", "squats", "plank", "ladder"]

ASK_NAME, CHOOSING, ENTERING = range(3)


def rank_for_value(cfg, value):
    name = cfg["ranks"][0][1]
    for bound, rname in cfg["ranks"]:
        if value >= bound:
            name = rname
        else:
            break
    return name


def next_milestone(cfg, value):
    if cfg.get("is_ladder"):
        return cfg["max"]
    for m in cfg["milestones"]:
        if m > value:
            return m
    return cfg["milestones"][-1]


def unit_plural(cfg):
    return "ступеней" if cfg.get("is_ladder") else cfg["unit"]


def today_str():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def save_exercise(user_id: str, exercise: str, value: float, unit: str) -> bool:
    payload = {"user_id": user_id, "exercise": exercise, "value": value, "date": today_str(), "unit": unit}
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/exercise_logs",
            headers={**HEADERS, "Prefer": "resolution=merge-duplicates"},
            params={"on_conflict": "user_id,exercise,date"},
            json=payload,
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        logger.error("Supabase insert failed: %s", e)
        return False
    if resp.status_code >= 300:
        logger.error("Supabase insert error: %s %s", resp.status_code, resp.text)
        return False
    return True


def fetch_history(user_id: str, exercise: str, limit: int = 30):
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/exercise_logs",
            headers=HEADERS,
            params={
                "user_id": f"eq.{user_id}",
                "exercise": f"eq.{exercise}",
                "select": "value,date",
                "order": "date.asc",
                "limit": limit,
            },
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        logger.error("Supabase fetch failed: %s", e)
        return []
    if resp.status_code >= 300:
        logger.error("Supabase fetch error: %s %s", resp.status_code, resp.text)
        return []
    return resp.json()


def user_id_for(update: Update) -> str:
    return f"tg_{update.effective_user.id}"


def raw_telegram_id(update: Update) -> str:
    return str(update.effective_user.id)


def fetch_display_name(telegram_id: str):
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/user_profiles",
            headers=HEADERS,
            params={"telegram_id": f"eq.{telegram_id}", "select": "nickname", "limit": 1},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        logger.error("Supabase fetch name failed: %s", e)
        return None
    if resp.status_code >= 300:
        logger.error("Supabase fetch name error: %s %s", resp.status_code, resp.text)
        return None
    rows = resp.json()
    return rows[0]["nickname"] if rows else None


def save_display_name(telegram_id: str, name: str) -> bool:
    payload = {"telegram_id": telegram_id, "nickname": name}
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/user_profiles",
            headers={**HEADERS, "Prefer": "resolution=merge-duplicates"},
            params={"on_conflict": "telegram_id"},
            json=payload,
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        logger.error("Supabase save name failed: %s", e)
        return False
    if resp.status_code >= 300:
        logger.error("Supabase save name error: %s %s", resp.status_code, resp.text)
        return False
    return True


# ── /start — знакомство. Спрашиваем имя один раз, дальше используем его,
# а не телеграмный логин/first_name. ──
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = raw_telegram_id(update)
    name = fetch_display_name(telegram_id)
    if name:
        await send_greeting(update, name)
        return ConversationHandler.END

    await update.message.reply_text(
        "Привет! Я СенПай, твой помощник по тренировкам в Brotherhood. 👋\n\n"
        "Как мне к тебе обращаться?"
    )
    return ASK_NAME


async def save_name_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    save_display_name(raw_telegram_id(update), name)
    await send_greeting(update, name)
    return ConversationHandler.END


async def send_greeting(update: Update, name: str):
    await update.message.reply_text(
        f"Приятно познакомиться, {name}! 👊\n\n"
        "Буду записывать твои результаты, считать разряды и серию тренировок "
        "подряд — чтобы тебе не приходилось держать это в голове.\n\n"
        "/today — отметить сегодняшний результат\n"
        "/stats — статистика по всем упражнениям\n\n"
        f"А ещё загляни на сайт — {SITE_URL} — и нажми там кнопку «Войти», "
        "чтобы попасть в свой личный кабинет: там разряды, серия и графики уже "
        "собраны вместе."
    )


def picker_keyboard():
    rows = [[InlineKeyboardButton(EXERCISE_CONFIG[k]["label"], callback_data=f"ex:{k}")] for k in EXERCISE_ORDER]
    rows.append([InlineKeyboardButton("Готово ✅", callback_data="done")])
    return InlineKeyboardMarkup(rows)


def build_today_text(uid: str, name: str = None) -> str:
    today = today_str()
    header = f"{name}, вот твоя сводка на {today}:" if name else f"Сегодня, {today}"
    blocks = [header]
    for key in EXERCISE_ORDER:
        cfg = EXERCISE_CONFIG[key]
        history = fetch_history(uid, key)
        if not history:
            blocks.append(f"{cfg['label']} — нет данных\nсегодня: ещё не отмечено")
            continue
        pr = max(float(h["value"]) for h in history)
        rank = rank_for_value(cfg, pr)
        milestone = next_milestone(cfg, pr)
        remain = max(0, milestone - pr)
        last = history[-1]
        today_val = f"{float(last['value']):g} {cfg['unit']}" if last["date"] == today else "ещё не отмечено"

        line = f"{cfg['label']} — {rank}"
        if remain > 0:
            line += f" · осталось {remain:g} {unit_plural(cfg)}"
        line += f"\nсегодня: {today_val}"
        blocks.append(line)
    return "\n\n".join(blocks)


# ── /today — сводка + кнопки под сообщением ──
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = user_id_for(update)
    name = fetch_display_name(raw_telegram_id(update))
    await update.message.reply_text(build_today_text(uid, name), reply_markup=picker_keyboard())
    return CHOOSING


async def choose_exercise_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    context.user_data["exercise"] = key
    cfg = EXERCISE_CONFIG[key]
    await query.edit_message_text(f"{cfg['label']} — сколько сделал сегодня? ({cfg['unit']})", reply_markup=None)
    return ENTERING


async def finish_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Отлично, записали. До завтра — так и куётся серия 💪", reply_markup=None)
    await query.message.reply_text(
        "Полная картина — в личном кабинете:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Открыть кабинет", url=CABINET_URL)]]),
    )
    return ConversationHandler.END


async def enter_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip().replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        await update.message.reply_text("Нужно просто число, например 45. Попробуй ещё раз.")
        return ENTERING

    key = context.user_data["exercise"]
    cfg = EXERCISE_CONFIG[key]
    uid = user_id_for(update)

    if not save_exercise(uid, key, value, cfg["unit"]):
        await update.message.reply_text("Не получилось сохранить — попробуй ещё раз чуть позже.")
        return ConversationHandler.END

    rank = rank_for_value(cfg, value)
    milestone = next_milestone(cfg, value)
    remain = max(0, milestone - value)

    text = f"Записано: {cfg['label']} — {value:g}\nРазряд: {rank}"
    if remain > 0:
        text += f" · осталось {remain:g} {unit_plural(cfg)} до следующего"
    await update.message.reply_text(text)

    name = fetch_display_name(raw_telegram_id(update))
    await update.message.reply_text(build_today_text(uid, name), reply_markup=picker_keyboard())
    return CHOOSING


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = user_id_for(update)
    week_ago = (datetime.now(TZ) - timedelta(days=7)).strftime("%Y-%m-%d")
    lines = []
    for key in EXERCISE_ORDER:
        cfg = EXERCISE_CONFIG[key]
        history = fetch_history(uid, key)
        if not history:
            lines.append(f"{cfg['label']} — нет данных")
            continue
        pr = max(float(h["value"]) for h in history)
        current = float(history[-1]["value"])
        rank = rank_for_value(cfg, pr)
        milestone = next_milestone(cfg, pr)
        remain = max(0, milestone - pr)
        week_count = sum(1 for h in history if h["date"] >= week_ago)

        line = f"{cfg['label']}: {current:g} {cfg['unit']} · {rank}"
        if remain > 0:
            line += f" (осталось {remain:g} {unit_plural(cfg)})"
        line += f" · за неделю: {week_count}"
        lines.append(line)

    await update.message.reply_text("Твоя статистика:\n\n" + "\n".join(lines))


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled error while processing update: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Что-то пошло не так, попробуй ещё раз чуть позже."
            )
        except Exception:
            pass


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_error_handler(on_error)

    start_conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_name_step)],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
    )

    today_conv = ConversationHandler(
        entry_points=[CommandHandler("today", cmd_today)],
        states={
            CHOOSING: [
                CallbackQueryHandler(choose_exercise_cb, pattern=r"^ex:"),
                CallbackQueryHandler(finish_cb, pattern=r"^done$"),
            ],
            ENTERING: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_value)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("today", cmd_today),
            CommandHandler("start", cmd_start),
        ],
    )

    app.add_handler(start_conv)
    app.add_handler(today_conv)
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
