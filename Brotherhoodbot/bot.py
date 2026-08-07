import asyncio
import base64
import logging
import re
import requests
from datetime import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler

from dotenv import load_dotenv
load_dotenv()
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MY_ID = 385041328
GROUP_ID = int(os.environ.get("GROUP_ID", -1004307067265))
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_USER = "BrotherHood-Lab"
GITHUB_REPO = "BrotherHood"
GITHUB_FILE = "index.html"
SITE_URL = "https://brotherhood-lab.github.io/BrotherHood/"

logging.basicConfig(level=logging.INFO)
waiting_for_workout = False


INVENTORY_ICONS_PY = {
    "турник": '<svg width="14" height="14" viewBox="0 0 28 28" fill="none" stroke="#c9a84c" stroke-width="1.5" stroke-linecap="round"><line x1="4" y1="6" x2="24" y2="6"/><line x1="14" y1="6" x2="14" y2="22"/><line x1="10" y1="22" x2="18" y2="22"/></svg>',
    "брусья": '<svg width="14" height="14" viewBox="0 0 28 28" fill="none" stroke="#c9a84c" stroke-width="1.5" stroke-linecap="round"><line x1="4" y1="10" x2="24" y2="10"/><line x1="4" y1="18" x2="24" y2="18"/><line x1="6" y1="10" x2="6" y2="22"/><line x1="22" y1="10" x2="22" y2="22"/></svg>',
    "резина": '<svg width="14" height="14" viewBox="0 0 28 28" fill="none" stroke="#c9a84c" stroke-width="1.5" stroke-linecap="round"><ellipse cx="14" cy="14" rx="10" ry="5"/><ellipse cx="14" cy="14" rx="6" ry="2.5"/></svg>',
    "гантели": '<svg width="14" height="14" viewBox="0 0 28 28" fill="none" stroke="#c9a84c" stroke-width="1.5" stroke-linecap="round"><line x1="4" y1="14" x2="24" y2="14"/><ellipse cx="6" cy="14" rx="2.5" ry="4"/><ellipse cx="22" cy="14" rx="2.5" ry="4"/><line x1="8" y1="14" x2="20" y2="14" stroke-width="2.5"/></svg>',
    "коврик": '<svg width="14" height="14" viewBox="0 0 28 28" fill="none" stroke="#c9a84c" stroke-width="1.5" stroke-linecap="round"><rect x="4" y="10" width="20" height="10" rx="1"/><line x1="4" y1="13" x2="24" y2="13"/></svg>',
    "стул": '<svg width="14" height="14" viewBox="0 0 28 28" fill="none" stroke="#c9a84c" stroke-width="1.5" stroke-linecap="round"><rect x="6" y="4" width="16" height="10" rx="1"/><line x1="8" y1="14" x2="8" y2="24"/><line x1="20" y1="14" x2="20" y2="24"/></svg>',
}

LABELS_PY = {
    "турник": "ТУРНИК",
    "брусья": "БРУСЬЯ",
    "резина": "РЕЗИНА",
    "гантели": "ГАНТЕЛИ",
    "коврик": "КОВРИК",
    "стул": "СТУЛ",
}

# Корни слов для автоопределения инвентаря по тексту тренировки
INVENTORY_KEYWORDS = {
    "турник": ["турник"],
    "брусья": ["брус"],
    "резина": ["резин"],
    "гантели": ["гантел"],
    "коврик": ["коврик"],
    "стул": ["стул"],
}


def detect_inventory(text):
    text_lower = text.lower()
    found = []
    for key, roots in INVENTORY_KEYWORDS.items():
        if any(root in text_lower for root in roots):
            found.append(key)
    return found


def build_inventory_items_html(items):
    return "".join(
        f'<div class="inv-item"><div class="inv-box">{INVENTORY_ICONS_PY[name]}</div>'
        f'<span class="inv-label">{LABELS_PY[name]}</span></div>'
        for name in items if name in INVENTORY_ICONS_PY
    )


# Порядок кнопок в инвентарной клавиатуре
INVENTORY_ORDER = ["турник", "брусья", "резина", "гантели", "коврик", "стул"]

# Тренировки, ожидающие выбора инвентаря: chat_id -> данные тренировки
pending_workouts = {}


def build_inventory_keyboard(selected):
    rows = []
    row = []
    for item in INVENTORY_ORDER:
        mark = "✅ " if item in selected else ""
        row.append(InlineKeyboardButton(f"{mark}{LABELS_PY[item]}", callback_data=f"inv:{item}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Готово ✅", callback_data="inv:done")])
    return InlineKeyboardMarkup(rows)


def parse_workout(text):
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    first = lines[0]
    parts = re.split(r'[,\-]+', first)
    parts = [p.strip() for p in parts if p.strip()]

    time_match = re.search(r'\d{1,2}[:\s]\d{2}', parts[0])
    if time_match:
        workout_time = time_match.group().replace(' ', ':')
        muscles = parts[1:]
    else:
        workout_time = "17:00"
        muscles = parts

    muscles_str = " · ".join(m.strip().capitalize() for m in muscles)

    exercises = []
    for line in lines[1:]:
        # Строку "Инвентарь: ..." не показываем как упражнение — из неё только берём значки
        if line.lower().startswith("инвентарь"):
            continue
        for item in re.split(r',', line):
            item = item.strip()
            if item:
                exercises.append(item.capitalize())

    inventory = detect_inventory(text)

    return workout_time, muscles_str, exercises, inventory


def build_inner_html(workout_time, muscles, exercises, inventory=None):
    items_html = "".join(
        f'<li class="today-exercise-item"><span class="today-exercise-dot"></span>{ex}</li>'
        for ex in exercises
    )
    header_and_list = (
        f'<div class="today-header-row">'
        f'<p class="today-muscles">{muscles}</p>'
        f'<div class="today-time-block">'
        f'<p class="today-time-label">&#1053;&#1072;&#1095;&#1072;&#1083;&#1086;</p>'
        f'<p class="today-time-value">{workout_time}</p>'
        f'</div></div>'
        f'<ul class="today-exercise-list">{items_html}</ul>'
        f'</div>'  # закрывает .today-inner
    )

    inv_list = [i for i in (inventory or []) if i in INVENTORY_ICONS_PY]
    if not inv_list:
        # Не открываем inventory-block — закрывающие теги для today-block/section
        # остаются в исходном файле и всё равно корректно закроют разметку.
        return header_and_list

    inv_items_html = build_inventory_items_html(inv_list)
    inventory_html = (
        '<div id="inventory-block" style="display:block; border-top:1px solid rgba(201,168,76,0.2); '
        'margin-top:20px; padding-top:18px; position:relative; z-index:2;">'
        '<div id="inventory-icons" style="display:flex; gap:16px; flex-wrap:wrap; justify-content:center;">'
        f'{inv_items_html}'
    )
    return header_and_list + inventory_html


def build_tg_message(workout_time, muscles, exercises, inventory=None):
    muscles_line = muscles.replace(" · ", ", ")
    return f"Тренировка сегодня — {workout_time}\n{muscles_line}"


def site_link_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Подробнее →", url=SITE_URL)]])


def update_landing(inner_html):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        logging.error(f"GitHub GET failed: {r.status_code}")
        return False

    data = r.json()
    sha = data["sha"]

    # Для больших файлов GitHub возвращает пустой content и даёт download_url
    if data.get("content"):
        raw = base64.b64decode(data["content"].replace("\n", ""))
        content = raw.decode("utf-8")
    else:
        download_url = data.get("download_url")
        logging.info(f"Using download_url: {download_url}")
        r2 = requests.get(download_url)
        content = r2.text

    # Находим индексы начала и конца today-inner
    start_tag = '<div class="today-inner">'
    end_tag = '</div>\n  </div>\n</section>'

    start_idx = content.find(start_tag)
    end_idx = content.find(end_tag, start_idx)

    logging.info(f"start_idx={start_idx}, end_idx={end_idx}")

    if start_idx == -1 or end_idx == -1:
        # Попробуем с \r\n
        end_tag2 = '</div>\r\n  </div>\r\n</section>'
        end_idx = content.find(end_tag2, start_idx)
        logging.info(f"Попытка с CRLF: end_idx={end_idx}")
        if end_idx != -1:
            end_tag = end_tag2

    if start_idx == -1 or end_idx == -1:
        logging.error("today-inner block not found!")
        logging.error(f"Content length: {len(content)}")
        logging.error(f"First 200 chars: {repr(content[:200])}")
        idx2 = content.find("today-block")
        logging.error(f"today-block idx: {idx2}")
        if idx2 != -1:
            logging.error(f"Around today-block: {repr(content[idx2:idx2+300])}")
        return False

    new_content = (
        content[:start_idx + len(start_tag)] +
        inner_html +
        content[end_idx:]
    )

    encoded = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
    payload = {
        "message": "Update today workout",
        "content": encoded,
        "sha": sha
    }

    r2 = requests.put(url, headers=headers, json=payload)
    logging.info(f"GitHub PUT status: {r2.status_code}")
    return r2.status_code in (200, 201)


def build_stretch_html(stretch_time):
    return (
        '<div class="today-header-row">'
        '<p class="today-muscles">Растяжка</p>'
        '<div class="today-time-block">'
        '<p class="today-time-label">&#1053;&#1072;&#1095;&#1072;&#1083;&#1086;</p>'
        f'<p class="today-time-value">{stretch_time}</p>'
        '</div></div>'
        '<ul class="today-exercise-list">'
        '<li class="today-exercise-item"><span class="today-exercise-dot"></span>Растяжка всего тела</li>'
        '</ul>'
        '</div>'  # закрывает .today-inner (без инвентаря на растяжке)
    )


def build_rest_html():
    return (
        '<div class="today-header-row">'
        '<p class="today-muscles">День отдыха</p>'
        '</div>'
        '<ul class="today-exercise-list">'
        '<li class="today-exercise-item today-empty">Сегодня выходной. Отдыхаем</li>'
        '</ul>'
        '</div>'  # закрывает .today-inner (без инвентаря на выходном)
    )


REST_KEYWORDS = ["выходной", "отдых", "отдыхаем", "rest", "день отдыха"]


async def process_workout_text(text, silent, update, context):
    """Общая логика для растяжки / выходного / тренировки.
    silent=True — обновляем только сайт, без сообщения в группу."""
    text = text.strip()

    if text.lower().startswith("растяжка"):
        parts = text.split()
        stretch_time = parts[1] if len(parts) > 1 else "22:00"
        html = build_stretch_html(stretch_time)
        success = update_landing(html)
        if silent:
            await update.message.reply_text("✅ Лендинг обновлён (без оповещения)." if success else "⚠️ Не удалось обновить лендинг.")
        else:
            tg_message = f"Растяжка сегодня — {stretch_time}"
            await update.message.reply_text(f"✅ Лендинг обновлён!\n\n{tg_message}" if success else "⚠️ Не удалось обновить лендинг.")
            await context.bot.send_message(chat_id=GROUP_ID, text=tg_message, reply_markup=site_link_keyboard())
        return

    if any(kw in text.lower() for kw in REST_KEYWORDS):
        html = build_rest_html()
        success = update_landing(html)
        if silent:
            await update.message.reply_text("✅ Лендинг обновлён — выходной (без оповещения)." if success else "⚠️ Не удалось обновить лендинг.")
        else:
            tg_message = "Сегодня выходной. Отдыхаем!"
            await update.message.reply_text("✅ Лендинг обновлён — выходной!" if success else "⚠️ Не удалось обновить лендинг.")
            await context.bot.send_message(chat_id=GROUP_ID, text=tg_message, reply_markup=site_link_keyboard())
        return

    workout_time, muscles, exercises, auto_inventory = parse_workout(text)

    # Явно указан инвентарь строкой "Инвентарь: ..." — публикуем сразу, без диалога
    explicit_inventory = any(
        l.strip().lower().startswith("инвентарь") for l in text.split("\n")
    )
    if explicit_inventory:
        result_text = await finalize_workout(workout_time, muscles, exercises, auto_inventory, silent, context)
        await update.message.reply_text(result_text)
        return

    # Иначе — спрашиваем инвентарь кнопками (авто-найденные значки уже отмечены)
    chat_id = update.effective_chat.id
    pending_workouts[chat_id] = {
        "workout_time": workout_time,
        "muscles": muscles,
        "exercises": exercises,
        "inventory": set(auto_inventory),
        "silent": silent,
    }
    await update.message.reply_text(
        "Какой инвентарь нужен сегодня? Отметь и нажми «Готово».",
        reply_markup=build_inventory_keyboard(set(auto_inventory))
    )


async def finalize_workout(workout_time, muscles, exercises, inventory, silent, context):
    """Пишет тренировку на лендинг и, если не silent, шлёт сообщение в группу.
    Возвращает текст для ответа автору."""
    inventory = list(inventory)
    inner_html = build_inner_html(workout_time, muscles, exercises, inventory)
    success = update_landing(inner_html)

    if silent:
        return "✅ Лендинг обновлён (без оповещения)." if success else "⚠️ Не удалось обновить лендинг."

    tg_message = build_tg_message(workout_time, muscles, exercises, inventory)
    if success:
        await context.bot.send_poll(
            chat_id=GROUP_ID,
            question=tg_message,
            options=["Буду", "Пропущу", "Помолюсь за вас"],
            is_anonymous=False,
            reply_markup=site_link_keyboard()
        )
        return f"✅ Лендинг обновлён!\n\n{tg_message}"
    return "⚠️ Не удалось обновить лендинг."


async def inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat.id

    if chat_id != MY_ID:
        await query.answer()
        return

    data = pending_workouts.get(chat_id)
    if not data:
        await query.answer("Тренировка уже опубликована или сессия устарела.", show_alert=True)
        return

    action = query.data.split(":", 1)[1]

    if action == "done":
        result_text = await finalize_workout(
            data["workout_time"], data["muscles"], data["exercises"],
            data["inventory"], data["silent"], context
        )
        del pending_workouts[chat_id]
        await query.edit_message_text(result_text)
        await query.answer()
        return

    # Переключаем выбранный пункт инвентаря
    if action in data["inventory"]:
        data["inventory"].discard(action)
    else:
        data["inventory"].add(action)
    await query.edit_message_reply_markup(reply_markup=build_inventory_keyboard(data["inventory"]))
    await query.answer()


async def ask_workout(app):
    global waiting_for_workout
    waiting_for_workout = True
    await app.bot.send_message(chat_id=MY_ID, text="Привет! 💪 Какая тренировка сегодня?\n\nФормат:\n17:00, Плечи, Грудь\nПриседания, бой с тенью\nОтжимания х4\nИнвентарь: турник, гантели")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_workout

    if update.effective_chat.id != MY_ID:
        return

    if not waiting_for_workout:
        waiting_for_workout = True
        await update.message.reply_text("Окей, жду описание тренировки!\n\nФормат:\n17:00, Плечи, Грудь\nПриседания х4\nБег х5")
        return

    workout_text = update.message.text.strip()
    waiting_for_workout = False

    # "сайт ..." или "/сайт ..." — обновление только лендинга, без оповещения группы
    normalized = workout_text[1:] if workout_text.startswith("/") else workout_text
    if normalized.lower().startswith("сайт"):
        silent_text = normalized[4:].strip()
        if not silent_text:
            await update.message.reply_text("Напиши тренировку после слова сайт.\n\nПример:\nсайт 17:00, Плечи, Грудь\nПриседания х4\nИнвентарь: турник, гантели")
            waiting_for_workout = True
            return
        await process_workout_text(silent_text, silent=True, update=update, context=context)
        return

    await process_workout_text(workout_text, silent=False, update=update, context=context)


async def send_poll(app):
    await app.bot.send_poll(
        chat_id=GROUP_ID,
        question="Как самочувствие, бандиты? 💪",
        options=[
            "Отлично 🔥",
            "Полон сил ⚡️",
            "Среднее, но рабочее 😐",
            "Всё болит, едва хожу 😩",
            "Я хочу домой, к маме 🥺"
        ],
        is_anonymous=False
    )


async def poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != MY_ID:
        return
    await send_poll(context.application)
    await update.message.reply_text("✅ Опрос отправлен в группу!")


async def workout_poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != MY_ID:
        return
    await context.bot.send_poll(
        chat_id=GROUP_ID,
        question="Поработаем? 💪",
        options=[
            "Работаем 🔥",
            "Пропущу 🙏"
        ],
        is_anonymous=False
    )
    await update.message.reply_text("✅ Опрос отправлен в группу!")


async def main():
    from telegram.ext import CommandHandler
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(inventory_callback, pattern=r"^inv:"))
    app.add_handler(CommandHandler("poll", poll_command))
    app.add_handler(CommandHandler("porabotaem", workout_poll_command))
    app.job_queue.run_daily(
        lambda ctx: asyncio.create_task(ask_workout(app)),
        time=time(hour=9, minute=0)
    )
    app.job_queue.run_daily(
        lambda ctx: asyncio.create_task(send_poll(app)),
        time=time(hour=10, minute=0)
    )
    print("Бот запущен!")
    async with app:
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
