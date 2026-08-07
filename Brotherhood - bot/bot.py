import asyncio
import base64
import logging
import os
import re
import requests
from datetime import time, datetime

from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CallbackQueryHandler,
    CommandHandler, filters, ContextTypes
)

# ─── Конфиг ───────────────────────────────────────────────────────────────────
BOT_TOKEN        = os.environ.get("BOT_TOKEN")
MY_ID            = 385041328
GROUP_ID         = int(os.environ.get("GROUP_ID", -1004307067265))
GITHUB_TOKEN     = os.environ.get("GITHUB_TOKEN")
GITHUB_USER      = "BrotherHood-Lab"
GITHUB_REPO      = "BrotherHood"
GITHUB_FILE      = "index.html"
SITE_URL         = "https://brotherhood-lab.github.io/BrotherHood/"
ANNOUNCE_THREAD_ID = 50

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
PHOTO_WORKOUT    = os.path.join(BASE_DIR, "roof.jpg")
PHOTO_STRETCH    = os.path.join(BASE_DIR, "roof_stretch.jpg")

logging.basicConfig(level=logging.INFO)

# ─── Инвентарь ────────────────────────────────────────────────────────────────
INVENTORY_ICONS = {
    "турник":  '<svg width="14" height="14" viewBox="0 0 28 28" fill="none" stroke="#c9a84c" stroke-width="1.5" stroke-linecap="round"><line x1="4" y1="6" x2="24" y2="6"/><line x1="14" y1="6" x2="14" y2="22"/><line x1="10" y1="22" x2="18" y2="22"/></svg>',
    "брусья":  '<svg width="14" height="14" viewBox="0 0 28 28" fill="none" stroke="#c9a84c" stroke-width="1.5" stroke-linecap="round"><line x1="4" y1="10" x2="24" y2="10"/><line x1="4" y1="18" x2="24" y2="18"/><line x1="6" y1="10" x2="6" y2="22"/><line x1="22" y1="10" x2="22" y2="22"/></svg>',
    "резина":  '<svg width="14" height="14" viewBox="0 0 28 28" fill="none" stroke="#c9a84c" stroke-width="1.5" stroke-linecap="round"><ellipse cx="14" cy="14" rx="10" ry="5"/><ellipse cx="14" cy="14" rx="6" ry="2.5"/></svg>',
    "гантели": '<svg width="14" height="14" viewBox="0 0 28 28" fill="none" stroke="#c9a84c" stroke-width="1.5" stroke-linecap="round"><line x1="4" y1="14" x2="24" y2="14"/><ellipse cx="6" cy="14" rx="2.5" ry="4"/><ellipse cx="22" cy="14" rx="2.5" ry="4"/><line x1="8" y1="14" x2="20" y2="14" stroke-width="2.5"/></svg>',
    "коврик":  '<svg width="14" height="14" viewBox="0 0 28 28" fill="none" stroke="#c9a84c" stroke-width="1.5" stroke-linecap="round"><rect x="4" y="10" width="20" height="10" rx="1"/><line x1="4" y1="13" x2="24" y2="13"/></svg>',
    "стул":    '<svg width="14" height="14" viewBox="0 0 28 28" fill="none" stroke="#c9a84c" stroke-width="1.5" stroke-linecap="round"><rect x="6" y="4" width="16" height="10" rx="1"/><line x1="8" y1="14" x2="8" y2="24"/><line x1="20" y1="14" x2="20" y2="24"/></svg>',
}
INVENTORY_LABELS = {
    "турник": "ТУРНИК", "брусья": "БРУСЬЯ", "резина": "РЕЗИНА",
    "гантели": "ГАНТЕЛИ", "коврик": "КОВРИК", "стул": "СТУЛ",
}
INVENTORY_ORDER = ["турник", "брусья", "резина", "гантели", "коврик", "стул"]
INVENTORY_KEYWORDS = {
    "турник": ["турник"], "брусья": ["брус"], "резина": ["резин"],
    "гантели": ["гантел"], "коврик": ["коврик"], "стул": ["стул"],
}
REST_KEYWORDS = ["выходной", "отдых", "отдыхаем", "rest", "день отдыха"]

# pending_workouts: chat_id -> {workout_time, muscles, exercises, inventory, silent}
pending_workouts = {}


def detect_inventory(text):
    tl = text.lower()
    return [k for k, roots in INVENTORY_KEYWORDS.items() if any(r in tl for r in roots)]


def build_inventory_html(items):
    return "".join(
        f'<div class="inv-item"><div class="inv-box">{INVENTORY_ICONS[n]}</div>'
        f'<span class="inv-label">{INVENTORY_LABELS[n]}</span></div>'
        for n in items if n in INVENTORY_ICONS
    )


def build_inventory_keyboard(selected):
    rows = []
    row = []
    for item in INVENTORY_ORDER:
        mark = "✅ " if item in selected else ""
        row.append(InlineKeyboardButton(f"{mark}{INVENTORY_LABELS[item]}", callback_data=f"inv:{item}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Готово ✅", callback_data="inv:done")])
    return InlineKeyboardMarkup(rows)


def site_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Подробнее →", url=SITE_URL)]])


# ─── HTML для лендинга ────────────────────────────────────────────────────────
def build_workout_html(workout_time, muscles, exercises, inventory=None):
    items_html = "".join(
        f'<li class="today-exercise-item"><span class="today-exercise-dot"></span>{ex}</li>'
        for ex in exercises
    )
    inner = (
        f'<div class="today-header-row">'
        f'<p class="today-muscles">{muscles}</p>'
        f'<div class="today-time-block">'
        f'<p class="today-time-label" style="display:none;">Начало</p>'
        f'<p class="today-time-value">{workout_time}</p>'
        f'</div></div>'
        f'<ul class="today-exercise-list">{items_html}</ul>'
        f'</div>'
    )
    inv_list = [i for i in (inventory or []) if i in INVENTORY_ICONS]
    if inv_list:
        inner += (
            '<div id="inventory-block" style="display:block; border-top:1px solid rgba(201,168,76,0.2); '
            'margin-top:20px; padding-top:18px; position:relative; z-index:2;">'
            '<div id="inventory-icons" style="display:flex; gap:16px; flex-wrap:wrap; justify-content:center;">'
            + build_inventory_html(inv_list)
        )
    return inner


def build_stretch_html(stretch_time):
    return (
        '<div class="today-header-row">'
        '<p class="today-muscles">Растяжка</p>'
        '<div class="today-time-block">'
        '<p class="today-time-label" style="display:none;">Начало</p>'
        f'<p class="today-time-value">{stretch_time}</p>'
        '</div></div>'
        '<ul class="today-exercise-list">'
        '<li class="today-exercise-item"><span class="today-exercise-dot"></span>Растяжка. Медитация</li>'
        '</ul>'
        '</div>'
    )


def build_rest_html():
    return (
        '<div class="today-header-row">'
        '<p class="today-muscles">День отдыха</p>'
        '</div>'
        '<ul class="today-exercise-list">'
        '<li class="today-exercise-item today-empty">Сегодня выходной. Отдыхаем</li>'
        '</ul>'
        '</div>'
    )


# ─── GitHub ───────────────────────────────────────────────────────────────────
def update_landing(inner_html):
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    api_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    r = requests.get(api_url, headers=headers)
    if r.status_code != 200:
        logging.error(f"GitHub GET error: {r.status_code}")
        return False

    data = r.json()
    sha = data["sha"]
    download_url = data["download_url"]
    logging.info(f"Using download_url: {download_url}")

    content_r = requests.get(download_url)
    html = content_r.text

    start_marker = '<div class="today-inner">'
    end_marker = '</section>'
    start_idx = html.find(start_marker)
    if start_idx == -1:
        logging.error("today-inner marker not found")
        return False
    start_idx += len(start_marker)

    section_end = html.find(end_marker, start_idx)
    end_markers = ['</div>\n</section>', '</div>\n\n</section>']
    end_idx = section_end
    for em in end_markers:
        idx = html.rfind('</div>', start_idx, section_end)
        if idx != -1:
            end_idx = idx
            break

    # Найдём конец today-inner блока
    end_idx = html.find('</div>', start_idx)
    # Ищем секцию расписания как ориентир
    schedule_marker = '<hr class="divider">'
    schedule_idx = html.find(schedule_marker, start_idx)
    if schedule_idx != -1:
        end_idx = html.rfind('</div>', start_idx, schedule_idx)

    logging.info(f"start_idx={start_idx}, end_idx={end_idx}")

    new_html = html[:start_idx] + "\n    " + inner_html + "\n  " + html[end_idx:]
    encoded = base64.b64encode(new_html.encode("utf-8")).decode("utf-8")

    put_r = requests.put(api_url, headers=headers, json={
        "message": "Update today block",
        "content": encoded,
        "sha": sha,
    })
    logging.info(f"GitHub PUT status: {put_r.status_code}")
    return put_r.status_code in (200, 201)


# ─── Парсинг тренировки ───────────────────────────────────────────────────────
def parse_workout(text):
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    first = lines[0]
    parts = [p.strip() for p in re.split(r'[,\-]+', first) if p.strip()]

    time_match = re.search(r'\d{1,2}[:\s]\d{2}', parts[0])
    if time_match:
        workout_time = time_match.group().replace(' ', ':')
        muscles = parts[1:]
    else:
        workout_time = "17:00"
        muscles = parts

    muscles_str = " · ".join(m.capitalize() for m in muscles)

    exercises = []
    for line in lines[1:]:
        if line.lower().startswith("инвентарь"):
            continue
        for item in re.split(r',', line):
            item = item.strip()
            if item:
                exercises.append(item.capitalize())

    inventory = detect_inventory(text)
    return workout_time, muscles_str, exercises, inventory


# ─── Отправка в группу ────────────────────────────────────────────────────────
async def send_to_group(context, text, photo_path=None, is_stretch=False):
    """Отправляет анонс в группу: фото (если есть) + опрос."""
    if photo_path and os.path.exists(photo_path):
        with open(photo_path, "rb") as photo:
            await context.bot.send_photo(
                chat_id=GROUP_ID,
                photo=photo,
                caption=text,
                reply_markup=site_keyboard(),
                message_thread_id=ANNOUNCE_THREAD_ID
            )
    else:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=text,
            reply_markup=site_keyboard(),
            message_thread_id=ANNOUNCE_THREAD_ID
        )

    poll_options = ["Будду", "Не Будду"] if is_stretch else ["Буду", "Пропущу"]
    await context.bot.send_poll(
    	chat_id=GROUP_ID,
    	question="Будете сегодня? 💪",  # ← вот это меняем
    	options=poll_options,
    	is_anonymous=False,
    	message_thread_id=ANNOUNCE_THREAD_ID
    )


# ─── Обработка тренировки/растяжки/выходного ─────────────────────────────────
async def process_text(text, silent, update, context):
    text = text.strip()

    # Растяжка
    if text.lower().startswith("растяжка"):
        parts = text.split()
        stretch_time = parts[1] if len(parts) > 1 else "22:00"
        success = True  # сайт временно отключён
        tg_text = f"Растяжка сегодня — {stretch_time}"
        if silent:
            await update.message.reply_text("✅ Готово.")
        else:
            await update.message.reply_text("✅ Отправлено в группу!")
            await send_to_group(context, tg_text, PHOTO_STRETCH, is_stretch=True)
        return

    # Выходной
    if any(kw in text.lower() for kw in REST_KEYWORDS):
        success = True  # сайт временно отключён
        tg_text = "Сегодня выходной. Отдыхаем!"
        if silent:
            await update.message.reply_text("✅ Готово.")
        else:
            await update.message.reply_text("✅ Отправлено в группу!")
            await send_to_group(context, tg_text, PHOTO_WORKOUT)
        return

    # Тренировка
    workout_time, muscles, exercises, auto_inv = parse_workout(text)
    has_explicit_inv = any(l.strip().lower().startswith("инвентарь") for l in text.split("\n"))

    if has_explicit_inv:
        # Публикуем сразу
        await finalize(workout_time, muscles, exercises, set(auto_inv), silent, update, context)
    else:
        # Спрашиваем инвентарь кнопками
        pending_workouts[update.effective_chat.id] = {
            "workout_time": workout_time,
            "muscles": muscles,
            "exercises": exercises,
            "inventory": set(auto_inv),
            "silent": silent,
        }
        await update.message.reply_text(
            "Какой инвентарь нужен сегодня?",
            reply_markup=build_inventory_keyboard(set(auto_inv))
        )


async def finalize(workout_time, muscles, exercises, inventory, silent, update, context):
    inv_list = list(inventory)
    success = True  # сайт временно отключён

    exercises_text = "\n".join(f"• {ex}" for ex in exercises) if exercises else ""
    tg_text = f"Тренировка сегодня — {workout_time}\n{muscles.replace(' · ', ', ')}"
    if exercises_text:
        tg_text += f"\n\n{exercises_text}"

    if silent:
        await update.message.reply_text("✅ Готово.")
    else:
        await update.message.reply_text("✅ Отправлено в группу!")
        await send_to_group(context, tg_text, PHOTO_WORKOUT)


# ─── Обработчики ─────────────────────────────────────────────────────────────
async def inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat.id

    if chat_id != MY_ID:
        await query.answer()
        return

    data = pending_workouts.get(chat_id)
    if not data:
        await query.answer("Сессия устарела.", show_alert=True)
        return

    action = query.data.split(":", 1)[1]

    if action == "done":
        del pending_workouts[chat_id]
        # Создаём фиктивный update для finalize
        await finalize(
            data["workout_time"], data["muscles"], data["exercises"],
            data["inventory"], data["silent"], query, context
        )
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer()
        return

    if action in data["inventory"]:
        data["inventory"].discard(action)
    else:
        data["inventory"].add(action)

    await query.edit_message_reply_markup(reply_markup=build_inventory_keyboard(data["inventory"]))
    await query.answer()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != MY_ID:
        return

    # Игнорируем старые сообщения (накопились при перезапуске)
    age = (datetime.now(update.message.date.tzinfo) - update.message.date).total_seconds()
    if age > 60:
        logging.info(f"Skipping stale message ({age:.0f}s old)")
        return

    text = update.message.text.strip()
    normalized = text[1:] if text.startswith("/") else text
    first_word = normalized.lower().split()[0] if normalized.split() else ""

    # Команда "сайт ..." — только лендинг, без поста в группу
    if first_word == "сайт":
        silent_text = normalized[4:].strip()
        if not silent_text:
            await update.message.reply_text(
                "Напиши после слова «сайт»:\n\nсайт тренировка 17:00, Плечи, Грудь\nПриседания х4\n\n"
                "или:\nсайт растяжка 22:00\nсайт выходной"
            )
            return
        await process_text(silent_text, silent=True, update=update, context=context)
        return

    # Тренировка, растяжка, выходной — обрабатываем
    if first_word in ("тренировка", "растяжка", "выходной", "отдых"):
        # Убираем первое слово-триггер если это "тренировка", остальное передаём как есть
        if first_word == "тренировка":
            payload = normalized[len("тренировка"):].strip()
            if not payload:
                await update.message.reply_text(
                    "Напиши тренировку в формате:\n\nтренировка 17:00, Плечи, Грудь\nПриседания х4\nОтжимания х3"
                )
                return
        else:
            payload = normalized
        await process_text(payload, silent=False, update=update, context=context)
        return

    # Всё остальное — приветствие/произвольное сообщение
    await update.message.reply_text(
        "Братан 🤙\n\n"
        "Чтобы добавить тренировку напиши:\n"
        "тренировка 17:00, Плечи\nПриседания х4\n\n"
        "Чтобы сделать растяжку напиши:\n"
        "растяжка 22:00\n\n"
        "Выходной:\n"
        "выходной\n\n"
        "Чтобы только сайт обновить:\n"
        "сайт тренировка 17:00, Плечи\n\n"
        "Голосования в группу:\n"
        "/poll — как самочувствие?\n"
        "/pain — что болит?\n"
        "/porabotaem — поработаем?\n"
        "/buddu — опрос Будду / Не Будду"
    )


# ─── Автоматика ──────────────────────────────────────────────────────────────
def is_rest_day():
    return datetime.now().weekday() in (2, 6)  # Среда, Воскресенье


async def morning_ask(app):
    if is_rest_day():
        return
    await app.bot.send_message(
        chat_id=MY_ID,
        text="Привет! Какая тренировка сегодня?\n\nФормат:\n17:00, Плечи, Грудь\nПриседания х4\nИнвентарь: турник, гантели"
    )


async def auto_rest(app):
    if not is_rest_day():
        return
    update_landing(build_rest_html())


# ─── Команды ─────────────────────────────────────────────────────────────────
async def cmd_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Опрос «Как самочувствие?»"""
    if update.effective_chat.id != MY_ID:
        return
    await context.application.bot.send_poll(
        chat_id=GROUP_ID,
        question="Как самочувствие, бандиты? 💪",
        options=["Отлично 🔥", "Полон сил ⚡️", "Среднее, но рабочее 😐", "Всё болит, едва хожу 😩", "Я хочу домой, к маме 🥺"],
        is_anonymous=False,
        message_thread_id=ANNOUNCE_THREAD_ID
    )
    await update.message.reply_text("✅ Опрос отправлен!")


async def cmd_pain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Опрос «Что болит?»"""
    if update.effective_chat.id != MY_ID:
        return
    await context.application.bot.send_poll(
        chat_id=GROUP_ID,
        question="Что болит?",
        options=["Грудь", "Спина", "Бицепс", "Трицепс", "Ноги", "Плечи", "Не был, болит душа"],
        is_anonymous=False,
        allows_multiple_answers=True,
        message_thread_id=ANNOUNCE_THREAD_ID
    )
    await update.message.reply_text("✅ Опрос отправлен!")


async def cmd_porabotaem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Опрос «Поработаем?»"""
    if update.effective_chat.id != MY_ID:
        return
    await context.application.bot.send_poll(
        chat_id=GROUP_ID,
        question="Поработаем? 💪",
        options=["Работаем 🔥", "Пропущу 🙏"],
        is_anonymous=False,
        message_thread_id=ANNOUNCE_THREAD_ID
    )
    await update.message.reply_text("✅ Опрос отправлен!")


async def cmd_buddu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Опрос «Будду / Не Будду»"""
    if update.effective_chat.id != MY_ID:
        return
    await context.application.bot.send_poll(
        chat_id=GROUP_ID,
        question="Будете сегодня?",
        options=["Будду 🙏", "Не Будду"],
        is_anonymous=False,
        message_thread_id=ANNOUNCE_THREAD_ID
    )
    await update.message.reply_text("✅ Опрос отправлен!")


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(inventory_callback, pattern=r"^inv:"))
    app.add_handler(CommandHandler("poll", cmd_poll))
    app.add_handler(CommandHandler("pain", cmd_pain))
    app.add_handler(CommandHandler("porabotaem", cmd_porabotaem))
    app.add_handler(CommandHandler("buddu", cmd_buddu))

    # Расписание
    app.job_queue.run_daily(lambda ctx: asyncio.create_task(auto_rest(app)),  time=time(0, 1))
    app.job_queue.run_daily(lambda ctx: asyncio.create_task(morning_ask(app)), time=time(9, 0))

    print("Бот запущен!")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
