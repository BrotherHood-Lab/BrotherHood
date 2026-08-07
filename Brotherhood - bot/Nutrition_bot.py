import logging
import asyncio
from datetime import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, JobQueue
)

# ── НАСТРОЙКИ ──
TELEGRAM_TOKEN = "8745378951:AAGfF8ELuRUYpObcM0rPpFmLvvhkC12M0Eo"
CABINET_URL = "https://brotherhood-lab.github.io/Nutrition/"
LEXER_CHAT_ID = None  # заполнится автоматически при /start

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ── КЛАВИАТУРА ──
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Открыть кабинет", url=CABINET_URL)],
        [InlineKeyboardButton("💧 Напомни про воду", callback_data="water")],
        [InlineKeyboardButton("📋 Моё расписание", callback_data="schedule")],
        [InlineKeyboardButton("⚙️ Напоминания", callback_data="reminders")],
    ])

# ── КОМАНДЫ ──
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LEXER_CHAT_ID
    LEXER_CHAT_ID = update.effective_chat.id
    # Сохраняем chat_id для напоминаний
    context.bot_data['chat_id'] = update.effective_chat.id

    await update.message.reply_text(
        "武道 · BROTHERHOOD · 道\n\n"
        "Привет, LeXeR! 💪\n\n"
        "Я твой помощник по питанию и расписанию.\n"
        "Напоминаю о приёмах пищи, воде и тренировках.\n\n"
        "Что делаем?",
        reply_markup=main_keyboard()
    )

async def cabinet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 Твой личный кабинет Brotherhood:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Открыть →", url=CABINET_URL)]
        ])
    )

async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 *Твой план на сегодня*\n\n"
        "🌅 08:00 — Электролит + завтрак\n"
        "🥤 10:30 — Протеиновый коктейль\n"
        "🍚 13:00 — Обед (купить в кафе)\n"
        "🏋️ 17:00 — Тренировка\n"
        "🥤 18:00 — Протеин после тренировки\n"
        "🍳 19:30 — Ужин\n"
        "🧘 22:00 — Растяжка и медитация\n"
        "🌙 23:00 — Казеин / творог\n\n"
        "💧 Норма воды: 3.5 литра"
    )
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Отметить приёмы →", url=CABINET_URL)]
        ])
    )

async def water(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💧 Норма воды: *3.5 литра* в день\n\n"
        "В жару Таиланда теряешь больше — пей регулярно.\n"
        "Кофе = -100 мл к балансу.\n"
        "После тренировки — +700 мл сразу.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Отметить воду →", url=CABINET_URL)]
        ])
    )

# ── КНОПКИ ──
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "water":
        await query.message.reply_text(
            "💧 *Вода сегодня*\n\n"
            "Норма: 3.5 литра\n"
            "Отмечай стаканы в кабинете 👇",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Открыть кабинет →", url=CABINET_URL)]
            ])
        )

    elif query.data == "schedule":
        await query.message.reply_text(
            "📋 *Расписание тренировок*\n\n"
            "🟡 Понедельник — 17:00–18:00\n"
            "🟡 Вторник — 17:00–18:00\n"
            "⬜ Среда — Отдых\n"
            "🟡 Четверг — 17:00–18:00\n"
            "🥊 Пятница — Бокс\n"
            "🟡 Суббота — 17:00–18:00\n"
            "⬜ Воскресенье — Сауна + Отдых\n\n"
            "🧘 Ежедневно 22:00–23:00 — Растяжка",
            parse_mode='Markdown'
        )

    elif query.data == "reminders":
        await query.message.reply_text(
            "⚙️ *Напоминания включены*\n\n"
            "Я напомню тебе:\n"
            "🌅 08:00 — Завтрак\n"
            "🥤 10:30 — Протеиновый коктейль\n"
            "🍚 13:00 — Обед\n"
            "⚡ 15:30 — Покушай до тренировки\n"
            "🏋️ 16:45 — Тренировка через 15 мин\n"
            "🥤 18:00 — Протеин после\n"
            "🍳 19:30 — Ужин\n"
            "🌙 23:00 — Казеин\n"
            "💧 Каждые 2 часа — Вода",
            parse_mode='Markdown'
        )

# ── НАПОМИНАНИЯ ──
async def remind_breakfast(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.bot_data.get('chat_id')
    if not chat_id: return
    await context.bot.send_message(
        chat_id,
        "🌅 *08:00 — Время завтрака!*\n\n"
        "Электролитный коктейль + завтрак.\n"
        "Не забудь папайю 🍈",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Отметить завтрак →", url=CABINET_URL)]
        ])
    )

async def remind_shake(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.bot_data.get('chat_id')
    if not chat_id: return
    await context.bot.send_message(
        chat_id,
        "🥤 *10:30 — Протеиновый коктейль*\n\n"
        "Протеин + овсянка + банан 🍌",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Отметить →", url=CABINET_URL)]
        ])
    )

async def remind_lunch(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.bot_data.get('chat_id')
    if not chat_id: return
    await context.bot.send_message(
        chat_id,
        "🍚 *13:00 — Обед*\n\n"
        "Рис + курица / рыба / креветки.\n"
        "Купи в кафе, попроси двойную порцию белка 💪",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Отметить обед →", url=CABINET_URL)]
        ])
    )

async def remind_pretrain(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.bot_data.get('chat_id')
    if not chat_id: return
    await context.bot.send_message(
        chat_id,
        "⚡ *15:30 — Покушай до тренировки*\n\n"
        "Тренировка через 1.5 часа.\n"
        "Лёгкий перекус — банан, орехи.",
        parse_mode='Markdown'
    )

async def remind_train(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.bot_data.get('chat_id')
    if not chat_id: return
    await context.bot.send_message(
        chat_id,
        "🏋️ *16:45 — Тренировка через 15 минут!*\n\n"
        "It's you against you. 武道",
        parse_mode='Markdown'
    )

async def remind_post(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.bot_data.get('chat_id')
    if not chat_id: return
    await context.bot.send_message(
        chat_id,
        "🥤 *18:00 — Протеин после тренировки!*\n\n"
        "Выпей шейк прямо сейчас — анаболическое окно 💪\n"
        "Потом закат, потом ужин.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Отметить →", url=CABINET_URL)]
        ])
    )

async def remind_dinner(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.bot_data.get('chat_id')
    if not chat_id: return
    await context.bot.send_message(
        chat_id,
        "🍳 *19:30 — Время ужина*\n\n"
        "Готовь дома или уже готово?\n"
        "Не забудь отметить в кабинете 👇",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Отметить ужин →", url=CABINET_URL)]
        ])
    )

async def remind_casein(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.bot_data.get('chat_id')
    if not chat_id: return
    await context.bot.send_message(
        chat_id,
        "🌙 *23:00 — Казеин / творог*\n\n"
        "Последний приём пищи.\n"
        "Защищает мышцы ночью 💤",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Отметить →", url=CABINET_URL)]
        ])
    )

async def remind_water(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.bot_data.get('chat_id')
    if not chat_id: return
    await context.bot.send_message(
        chat_id,
        "💧 Выпил воду? Норма 3.5 литра в день.\n"
        "В Таиланде особенно важно — жара!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Отметить воду →", url=CABINET_URL)]
        ])
    )

# ── ЗАПУСК ──
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cabinet", cabinet))
    app.add_handler(CommandHandler("plan", plan))
    app.add_handler(CommandHandler("water", water))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Напоминания (время Bangkok UTC+7 = UTC+0 минус 7 часов)
    # 08:00 Bangkok = 01:00 UTC
    jq = app.job_queue
    jq.run_daily(remind_breakfast, time(hour=1,  minute=0))   # 08:00 BKK
    jq.run_daily(remind_shake,     time(hour=3,  minute=30))  # 10:30 BKK
    jq.run_daily(remind_lunch,     time(hour=6,  minute=0))   # 13:00 BKK
    jq.run_daily(remind_pretrain,  time(hour=8,  minute=30))  # 15:30 BKK
    jq.run_daily(remind_train,     time(hour=9,  minute=45))  # 16:45 BKK
    jq.run_daily(remind_post,      time(hour=11, minute=0))   # 18:00 BKK
    jq.run_daily(remind_dinner,    time(hour=12, minute=30))  # 19:30 BKK
    jq.run_daily(remind_casein,    time(hour=16, minute=0))   # 23:00 BKK

    # Вода каждые 2 часа с 10:00 до 20:00
    jq.run_daily(remind_water, time(hour=3,  minute=0))   # 10:00
    jq.run_daily(remind_water, time(hour=5,  minute=0))   # 12:00
    jq.run_daily(remind_water, time(hour=7,  minute=0))   # 14:00
    jq.run_daily(remind_water, time(hour=9,  minute=0))   # 16:00
    jq.run_daily(remind_water, time(hour=13, minute=0))   # 20:00

    print("Brotherhood Bot запущен! 武道")
    app.run_polling()

if __name__ == "__main__":
    main()