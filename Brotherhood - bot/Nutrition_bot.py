"""
武道 Brotherhood Nutrition Bot 武道
Напоминания о питании, воде и тренировках.
Деплой: Railway (24/7)
"""

import os
import logging
from datetime import time, datetime
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ── НАСТРОЙКИ ──────────────────────────────────────────────
TOKEN = os.environ["TELEGRAM_TOKEN"]
CABINET_URL = "https://brotherhood-lab.github.io/Nutrition/"
TZ = ZoneInfo("Asia/Bangkok")  # UTC+7

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ── Расписание тренировок ──────────────────────────────────
# Пн=0  Вт=1  Ср=2  Чт=3  Пт=4  Сб=5  Вс=6
TRAINING_DAYS = {0, 1, 3, 5}   # Пн, Вт, Чт, Сб
BOXING_DAY = 4                  # Пт
REST_DAYS = {2, 6}              # Ср, Вс

# ── Расписание напоминаний (Bangkok UTC+7) ─────────────────
MEAL_REMINDERS = [
    ("08:00", "🍳 Завтрак!\nВремя зарядить тело. Яйца / каша / гранола — выбирай."),
    ("10:30", "🥤 Электролитный коктейль!\nНе забудь утренний микс."),
    ("13:00", "🍚 Обед!\nРис + курица/рыба/креветки. Заправься белком."),
    ("15:30", "⏰ Предтрен!\nПокушай за 1.5 часа до тренировки."),
    ("16:45", "🏋️ Тренировка через 15 минут!\nГотовься, warrior."),
    ("18:00", "🥛 Протеин!\nВремя для посттренировочного шейка."),
    ("19:30", "🍽️ Ужин!\nПриготовь себе что-нибудь из рецептов."),
    ("23:00", "🌙 Казеин / творог!\nМедленный белок на ночь для восстановления."),
]

# Вода: каждые 2 часа с 08:00 до 22:00
WATER_HOURS = [8, 10, 12, 14, 16, 18, 20, 22]

# ── Клавиатуры ─────────────────────────────────────────────

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Открыть кабинет", url=CABINET_URL)],
        [
            InlineKeyboardButton("💧 Вода", callback_data="water"),
            InlineKeyboardButton("📋 Расписание", callback_data="schedule"),
        ],
        [InlineKeyboardButton("🍽️ Рецепты", callback_data="recipes")],
    ])


def back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад", callback_data="back")],
    ])


def cabinet_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Отметить в кабинете", url=CABINET_URL)],
    ])


# ── Команды ────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    ctx.bot_data["chat_id"] = chat_id
    log.info(f"/start от {chat_id}")

    await update.message.reply_text(
        "武道 · BROTHERHOOD · 武道\n\n"
        "Привет, LeXeR! 💪\n\n"
        "Я напоминаю о питании, воде и тренировках.\n"
        "Кнопка ниже — твой кабинет питания.\n\n"
        "Что делаем?",
        reply_markup=main_kb(),
    )


async def cmd_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ)
    day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][now.weekday()]
    wd = now.weekday()

    if wd in TRAINING_DAYS:
        day_type = "🏋️ Тренировка 17:00–18:00"
        kcal = "~2950 ккал"
    elif wd == BOXING_DAY:
        day_type = "🥊 Бокс"
        kcal = "~2950 ккал"
    elif wd == 6:
        day_type = "♨️ Отдых · Сауна + Стрим 17:00"
        kcal = "~2710 ккал"
    else:
        day_type = "😴 Отдых"
        kcal = "~2710 ккал"

    text = (
        f"📅 {day_name} · {now.strftime('%d.%m')}\n"
        f"{day_type}\n\n"
        f"🎯 Цель: {kcal}\n"
        f"🥩 Белок: 190–235 г\n"
        f"🍚 Углеводы: 258–307 г\n"
        f"🧈 Жиры: 76–90 г\n"
        f"💧 Вода: 3.5 л\n\n"
        "08:00 — Завтрак\n"
        "10:30 — Электролиты\n"
        "13:00 — Обед\n"
    )

    if wd in TRAINING_DAYS or wd == BOXING_DAY:
        text += (
            "15:30 — Предтрен еда\n"
            "16:45 — Тренировка\n"
            "18:00 — Протеин\n"
        )

    text += (
        "19:30 — Ужин\n"
        "22:00 — Растяжка + Медитация\n"
        "23:00 — Казеин\n"
    )

    await update.message.reply_text(text, reply_markup=cabinet_kb())


async def cmd_water(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💧 Цель на день: 3.5 литра\n\n"
        "Напоминания каждые 2 часа: 08–22\n"
        "☕ Кофе = −100 мл от прогресса\n\n"
        "Отмечай в кабинете 👇",
        reply_markup=cabinet_kb(),
    )


async def cmd_cabinet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 Твой кабинет питания 👇",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Открыть кабинет", url=CABINET_URL)],
        ]),
    )


# ── Кнопки (callback) ─────────────────────────────────────

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "water":
        await q.edit_message_text(
            "💧 Цель: 3.5 л / день\n\n"
            "Напоминания каждые 2 часа (08:00–22:00)\n"
            "☕ Кофе вычитает 100 мл\n\n"
            "Отмечай прогресс в кабинете 👇",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Отметить воду", url=CABINET_URL)],
                [InlineKeyboardButton("◀️ Назад", callback_data="back")],
            ]),
        )

    elif data == "schedule":
        await q.edit_message_text(
            "📋 Расписание недели\n\n"
            "Пн — 🏋️ Тренировка 17:00\n"
            "Вт — 🏋️ Тренировка 17:00\n"
            "Ср — 😴 Отдых\n"
            "Чт — 🏋️ Тренировка 17:00\n"
            "Пт — 🥊 Бокс\n"
            "Сб — 🏋️ Тренировка 17:00\n"
            "Вс — ♨️ Сауна + Стрим 17:00\n\n"
            "Ежедневно 22:00–23:00 — Растяжка + Медитация",
            reply_markup=back_kb(),
        )

    elif data == "recipes":
        await q.edit_message_text(
            "🍽️ Быстрые рецепты ужинов\n\n"
            "🐔 Курица:\n"
            "• Курица терияки с рисом\n"
            "• Курица с овощами в соевом соусе\n"
            "• Куриные фрикадельки\n\n"
            "🍤 Креветки:\n"
            "• Креветки с чесноком и рисом\n"
            "• Том ям с креветками\n\n"
            "🧈 Тофу:\n"
            "• Тофу с овощами стир-фрай\n\n"
            "Полные рецепты → вкладка «Рецепты» в кабинете 👇",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Рецепты в кабинете", url=CABINET_URL)],
                [InlineKeyboardButton("◀️ Назад", callback_data="back")],
            ]),
        )

    elif data == "back":
        await q.edit_message_text(
            "武道 · BROTHERHOOD · 武道\n\n"
            "Что делаем?",
            reply_markup=main_kb(),
        )


# ── Напоминания (scheduled jobs) ──────────────────────────

async def send_meal_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = ctx.bot_data.get("chat_id")
    if not chat_id:
        return

    text = ctx.job.data["text"]
    tag = ctx.job.data.get("tag", "")

    # Предтрен и тренировка — только в тренировочные дни
    if tag in ("pretrain", "training", "protein"):
        wd = datetime.now(TZ).weekday()
        if wd not in TRAINING_DAYS and wd != BOXING_DAY:
            return

    await ctx.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=cabinet_kb(),
    )


async def send_water_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = ctx.bot_data.get("chat_id")
    if not chat_id:
        return

    hour = datetime.now(TZ).hour
    liters_should = round((hour - 6) * 3.5 / 16, 1)
    liters_should = max(0.5, min(liters_should, 3.5))

    await ctx.bot.send_message(
        chat_id=chat_id,
        text=f"💧 Пей воду!\nК этому часу цель: ~{liters_should} л из 3.5 л",
        reply_markup=cabinet_kb(),
    )


def schedule_reminders(app):
    """Регистрирует все напоминания в JobQueue."""
    jq = app.job_queue

    tags = [
        "breakfast", "electrolytes", "lunch", "pretrain",
        "training", "protein", "dinner", "casein",
    ]

    for (time_str, text), tag in zip(MEAL_REMINDERS, tags):
        h, m = map(int, time_str.split(":"))
        jq.run_daily(
            send_meal_reminder,
            time=time(h, m, tzinfo=TZ),
            data={"text": text, "tag": tag},
            name=f"meal_{tag}",
        )

    # Вода каждые 2 часа
    for hour in WATER_HOURS:
        jq.run_daily(
            send_water_reminder,
            time=time(hour, 0, tzinfo=TZ),
            name=f"water_{hour}",
        )

    log.info("✅ Напоминания зарегистрированы")


# ── ЗАПУСК ─────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("water", cmd_water))
    app.add_handler(CommandHandler("cabinet", cmd_cabinet))

    # Кнопки
    app.add_handler(CallbackQueryHandler(on_button))

    # Напоминания
    schedule_reminders(app)

    log.info("🚀 Brotherhood bot запущен")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
