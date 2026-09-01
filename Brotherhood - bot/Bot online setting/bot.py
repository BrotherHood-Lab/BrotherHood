import asyncio
import base64
import logging
import os
import re
import io
import requests
from datetime import time, datetime

from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, MessageHandler, CallbackQueryHandler,
    CommandHandler, PollAnswerHandler, filters, ContextTypes
)

# ─── Конфиг ───────────────────────────────────────────────────────────────────
BOT_TOKEN        = os.environ.get("BOT_TOKEN")
MY_ID            = 385041328
GROUP_ID         = int(os.environ.get("GROUP_ID", -1004307067265))
GITHUB_TOKEN     = os.environ.get("GITHUB_TOKEN")
GITHUB_USER      = "BrotherHood-Lab"
GITHUB_REPO      = "BrotherHood"
GITHUB_FILE      = "index.html"
SITE_URL         = "https://thebrotherhoodclub.com/"
TIMER_URL        = "https://thebrotherhoodclub.com/timer.html"
ANNOUNCE_THREAD_ID = 50
RULES_URL          = "https://t.me/thebrotherhoodclub/470"

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
PHOTO_WORKOUT    = os.path.join(BASE_DIR, "roof.jpg")
PHOTO_STRETCH    = os.path.join(BASE_DIR, "roof_stretch.jpg")

# ─── Supabase (те же данные, что у СенПая — читаем рекорды участников) ────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xcodcnqioajyqiiyfbrk.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_Qv4GTQtlinmb1YMbBG5vmw_Pw-U85-S")
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# Упражнения, за которыми следит СенПай — чтобы подставлять личный рекорд
# в напоминание, если анонс тренировки упоминает что-то из этого списка.
# Зеркало EXERCISE_CONFIG из СенПая/сайта — держать в соответствии,
# иначе разряды и цели тут разъедутся с тем, что человек видит в кабинете.
BODYWEIGHT_EXERCISES = {
    "pushups": {
        "label": "отжимания", "unit": "раз", "step": 1,
        "ranks": [(0, "Новичок"), (10, "Ученик"), (15, "Боец"), (25, "Ронин"),
                  (35, "Воин"), (45, "Самурай"), (60, "Мастер"), (75, "Легенда додзё")],
    },
    "pullups": {
        "label": "подтягивания", "unit": "раз", "step": 1,
        "ranks": [(0, "Новичок"), (4, "Ученик"), (7, "Боец"), (10, "Ронин"),
                  (15, "Воин"), (20, "Самурай"), (30, "Мастер"), (35, "Легенда додзё")],
    },
    "squats": {
        "label": "приседания", "unit": "раз", "step": 3,
        "ranks": [(0, "Новичок"), (10, "Ученик"), (20, "Боец"), (30, "Ронин"),
                  (40, "Воин"), (60, "Самурай"), (75, "Мастер"), (100, "Легенда додзё")],
    },
    "plank": {
        "label": "планка", "unit": "сек", "step": 30,
        "ranks": [(30, "Новичок"), (60, "Ученик"), (90, "Боец"), (120, "Ронин"),
                  (180, "Воин"), (300, "Самурай"), (400, "Мастер"), (600, "Легенда додзё")],
    },
    "bench_dips": {
        "label": "скамейка", "unit": "раз", "step": 1,
        "ranks": [(0, "Новичок"), (10, "Ученик"), (20, "Боец"), (35, "Ронин"),
                  (45, "Воин"), (65, "Самурай"), (75, "Мастер"), (100, "Легенда додзё")],
    },
    "ladder": {
        "label": "лесенка", "unit": "ступень", "step": 1,
        "ranks": [(1, "Новичок"), (3, "Ученик"), (5, "Боец"), (7, "Ронин"), (9, "Воин"), (10, "Самурай")],
    },
}


def rank_for_value(info, value):
    name = info["ranks"][0][1]
    for bound, rname in info["ranks"]:
        if value >= bound:
            name = rname
        else:
            break
    return name


def next_rank_for_value(info, value):
    """Возвращает (следующее_звание, порог) или (None, None), если это уже потолок."""
    for bound, rname in info["ranks"]:
        if bound > value:
            return rname, bound
    return None, None

# Сообщения участникам про "Буду" отправляются от имени СенПая (не этого
# бота) — напрямую через его токен, минуя Application этого процесса.
SENPAI_BOT_TOKEN = os.environ.get("SENPAI_BOT_TOKEN", "8762167254:AAEuRIRLQU9qW43Yiu7hfJIQrwPO_KJcExY")
SENPAI_USERNAME = "@BrotherHoodSenPaiBot"


def send_as_senpai(chat_id: int, text: str, parse_mode: str = "HTML"):
    """Возвращает (ok, error_description)."""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{SENPAI_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            return False, data.get("description", "unknown error")
        return True, None
    except Exception as e:
        return False, str(e)


# poll_id → метаданные анонса, чтобы понять, на какой именно опрос ответили
# «Буду», и что написать участнику. Хранится в памяти процесса — этого
# достаточно, опрос актуален только на сегодняшний день.
TRAINING_POLLS = {}


def fetch_personal_record(user_id: str, exercise_key: str):
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/exercise_logs",
            headers=SUPABASE_HEADERS,
            params={
                "user_id": f"eq.{user_id}",
                "exercise": f"eq.{exercise_key}",
                "select": "value",
                "order": "value.desc",
                "limit": 1,
            },
            timeout=10,
        )
        rows = resp.json()
        return float(rows[0]["value"]) if resp.ok and rows else None
    except Exception as e:
        logging.error("Supabase PR fetch failed: %s", e)
        return None


def fetch_profile_name(telegram_id: str):
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/user_profiles",
            headers=SUPABASE_HEADERS,
            params={"telegram_id": f"eq.{telegram_id}", "select": "nickname", "limit": 1},
            timeout=10,
        )
        rows = resp.json()
        return rows[0]["nickname"] if resp.ok and rows else None
    except Exception as e:
        logging.error("Supabase profile fetch failed: %s", e)
        return None


def save_training_poll(poll_id: str, meta: dict) -> None:
    """Сохраняет данные опроса в Supabase, чтобы они не терялись при рестарте
    сервиса (TRAINING_POLLS в памяти обнуляется при каждом деплое)."""
    payload = {
        "poll_id": poll_id,
        "exercises": meta.get("exercises"),
        "muscles": meta.get("muscles"),
        "workout_time": meta.get("workout_time"),
    }
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/training_polls",
            headers={**SUPABASE_HEADERS, "Prefer": "resolution=merge-duplicates"},
            params={"on_conflict": "poll_id"},
            json=payload,
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        logging.error("Supabase save_training_poll failed: %s", e)


def fetch_training_poll(poll_id: str):
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/training_polls",
            headers=SUPABASE_HEADERS,
            params={"poll_id": f"eq.{poll_id}", "select": "exercises,muscles,workout_time", "limit": 1},
            timeout=10,
        )
        rows = resp.json()
        if resp.ok and rows:
            return rows[0]
    except requests.exceptions.RequestException as e:
        logging.error("Supabase fetch_training_poll failed: %s", e)
    return None


def match_bodyweight_exercise(announced_name: str):
    """Пытается сопоставить строку из анонса (например 'Отжимания') с тем,
    что трекает СенПай, чтобы можно было подставить личный рекорд."""
    name = announced_name.strip().lower()
    for key, info in BODYWEIGHT_EXERCISES.items():
        label = info["label"]
        if label in name or name in label:
            return key, info
    return None, None

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

# pending_card: хранит путь к SVG пока ждём подтверждения
pending_card = {}

# last_workout_data: упражнения последней утверждённой тренировки
last_workout_data = {
    "exercises": [
        {"name": "Разминка", "type": "РАЗ", "sets": 1, "restSec": 0, "isWarmup": True, "durationLabel": "10 мин"},
        {"name": "Подтягивания широким хватом", "type": "ДИН", "sets": 4, "restSec": 120},
        {"name": "Отжимания классические", "type": "ДИН", "sets": 4, "restSec": 120},
        {"name": "Комплекс на поясницу лёжа", "type": "ДИН", "sets": 1, "restSec": 60},
        {"name": "Полупланка + трицепц и кор", "type": "ДИН", "sets": 3, "restSec": 60},
        {"name": "Бронсон 5: Тяга стула на плечи", "fire": True, "type": "ИЗО", "sets": 1, "restSec": 60, "isBronson": True},
        {"name": "Бронсон 7: Отведение локтя назад", "type": "ИЗО", "sets": 1, "restSec": 60, "isBronson": True},
        {"name": "Комплекс на пресс", "fire": True, "type": "КАР", "sets": 1, "restSec": 0},
    ],
    "title": "Спина + Кор + Плечи"
}


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
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Присоединиться →", url=SITE_URL),
        InlineKeyboardButton("▶ Таймер", web_app=WebAppInfo(url=TIMER_URL)),
    ]])


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
async def send_to_group(context, text, photo_path=None, is_stretch=False,
                         exercises=None, muscles=None, workout_time=None):
    """Отправляет анонс в группу: фото (если есть) + опрос.

    Если это анонс тренировки (exercises передан) — запоминаем poll_id,
    чтобы потом написать в личку тем, кто отметит «Буду»."""
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
    poll_msg = await context.bot.send_poll(
    	chat_id=GROUP_ID,
    	question="Будете сегодня? 💪",  # ← вот это меняем
    	options=poll_options,
    	is_anonymous=False,
    	message_thread_id=ANNOUNCE_THREAD_ID
    )

    if exercises:
        meta = {"exercises": exercises, "muscles": muscles, "workout_time": workout_time}
        TRAINING_POLLS[poll_msg.poll.id] = meta
        save_training_poll(poll_msg.poll.id, meta)


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
        await send_to_group(
            context, tg_text, PHOTO_WORKOUT,
            exercises=exercises, muscles=muscles, workout_time=workout_time,
        )


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
HELP_TEXT = (
    "📋 Команды:\n\n"
    "растяжка 22:00 — анонс растяжки\n"
    "выходной — анонс выходного\n"
    "17:00 Грудь, Спина — анонс тренировки\n\n"
    "/sport — карточка тренировки\n"
    "/practice — карточка вечерней практики\n"
    "/skip — отправить практику в группу\n"
    "/poll — опрос самочувствия\n"
    "/pain — опрос что болит\n"
    "/porabotaem — мотивация в группу\n"
    "/med — медитация\n"
    "/setworkout — установить время\n"
    "/start — это меню"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != MY_ID:
        await update.message.reply_text(
            "Привет! 👋\n\n"
            f"Сначала зарегистрируйся на сайте — {SITE_URL} — и нажми там кнопку «Войти».\n\n"
            "А потом возвращайся сюда и отмечай свои тренировки через "
            "@BrotherHoodSenPaiBot командой /go — так у тебя будут разряды, "
            "серия и статистика, а я смогу присылать напоминания и рекорды "
            "перед тренировкой."
        )
        return
    await update.message.reply_text(f"Братан 🤙\n\n{HELP_TEXT}")



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


# ─── Карточка тренировки ─────────────────────────────────────────────────────
async def svg_to_png(svg_path: str) -> bytes:
    """Конвертирует SVG в PNG через cairosvg (без Chromium)."""
    import cairosvg
    with open(svg_path, "r", encoding="utf-8") as f:
        svg_data = f.read()
    return cairosvg.svg2png(bytestring=svg_data.encode("utf-8"), scale=2)


async def cmd_setworkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /setworkout — принимает JSON с упражнениями следующим сообщением,
    сохраняет в last_workout_data для использования в /sport.
    """
    if update.effective_chat.id != MY_ID:
        return
    pending_card["awaiting_workout_json"] = True
    await update.message.reply_text(
        "Пришли JSON с упражнениями следующим сообщением.\n"
        "Формат: <code>{\"title\": \"Название\", \"exercises\": [...]}</code>",
        parse_mode="HTML"
    )


async def handle_workout_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает JSON тренировки текстом."""
    if update.effective_chat.id != MY_ID:
        return
    if not pending_card.get("awaiting_workout_json"):
        return
    import json
    try:
        data = json.loads(update.message.text)
        exercises = data.get("exercises", data if isinstance(data, list) else None)
        title = data.get("title", last_workout_data.get("title", "Тренировка"))
        if not exercises:
            raise ValueError("Нет поля exercises")
        last_workout_data["exercises"] = exercises
        last_workout_data["title"] = title
        pending_card.pop("awaiting_workout_json", None)
        await update.message.reply_text(f"✅ Тренировка «{title}» сохранена ({len(exercises)} упражнений).")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка парсинга JSON: {e}")


async def cmd_med(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /med [время] — публикует готовую карточку "Вечерняя Практика · Медитация".
    По умолчанию время 22:00. SVG-файл лежит рядом с ботом: meditation_card.svg
    """
    if update.effective_chat.id != MY_ID:
        return

    med_time = context.args[0] if context.args else "22:00"
    svg_path = os.path.join(BASE_DIR, "meditation_card.svg")

    if not os.path.exists(svg_path):
        await update.message.reply_text(
            "❌ Не найден файл meditation_card.svg рядом с ботом.\n"
            "Скачай карточку медитации из чата и положи в папку с ботом под этим именем."
        )
        return

    await _publish_card(
        svg_path, med_time, "Медитация", update, context,
        cleanup=False,
        poll_question="Будете на медитации?",
        poll_options=["Буду 🙏", "Не Будду"]
    )



async def cmd_sport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /sport — отправляет карточку тренировки в группу.
    Ждёт SVG-файл с подписью: 17:00 Спина + Бицепс
    """
    if update.effective_chat.id != MY_ID:
        return

    args = context.args
    if args and os.path.exists(args[0]):
        svg_path = args[0]
        workout_time = args[1] if len(args) > 1 else "17:00"
        description = " ".join(args[2:]) if len(args) > 2 else "Тренировка"
        await _publish_card(svg_path, workout_time, description, update, context)
        return

    pending_card[MY_ID] = "sport"
    await update.message.reply_text(
        "Пришли SVG-файл карточки тренировки.\n"
        "Подпись: <code>17:00 Спина + Бицепс</code>",
        parse_mode="HTML"
    )


async def cmd_practice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /practice 22:00 — анонс вечерней практики без карточки.
    Постит в группу: Начало в 22:00 + опрос Буду / Не Будду.
    """
    if update.effective_chat.id != MY_ID:
        return

    args = context.args
    practice_time = args[0] if args else "22:00"

    # Если приложен SVG — ждём документ
    pending_card[MY_ID] = "practice"
    pending_card["practice_time"] = practice_time
    await update.message.reply_text(
        f"Пришли SVG карточку практики (или нажми /skip чтобы без карточки).\n"
        f"Время: <b>{practice_time}</b>",
        parse_mode="HTML"
    )


async def cmd_practice_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет анонс практики без карточки."""
    if update.effective_chat.id != MY_ID:
        return
    practice_time = context.args[0] if context.args else pending_card.get("practice_time", "22:00")
    await _publish_practice(practice_time, update, context)


async def _publish_practice(practice_time: str, update, context):
    """Постит анонс вечерней практики в группу."""
    caption = f"🧘 Вечерняя практика — начало в {practice_time}"

    await context.bot.send_message(
        chat_id=GROUP_ID,
        text=caption,
        message_thread_id=ANNOUNCE_THREAD_ID
    )

    await context.bot.send_poll(
        chat_id=GROUP_ID,
        question="Будете на практике?",
        options=["Буду 🙏", "Не Будду"],
        is_anonymous=False,
        message_thread_id=ANNOUNCE_THREAD_ID
    )

    pending_card.pop("practice_time", None)
    await update.message.reply_text(f"✅ Анонс практики {practice_time} отправлен в группу!")


async def handle_card_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает SVG-документ и публикует карточку в группу."""
    if update.effective_chat.id != MY_ID:
        return

    card_type = pending_card.get(MY_ID)
    if not card_type:
        return

    doc = update.message.document
    if not doc:
        return

    filename = doc.file_name or ""
    is_svg = filename.lower().endswith(".svg") or doc.mime_type in ("image/svg+xml", "text/xml", "application/xml")
    if not is_svg:
        await update.message.reply_text("Это не SVG-файл. Пришли файл с расширением .svg")
        return

    import tempfile
    file = await context.bot.get_file(doc.file_id)
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
        svg_path = tmp.name
    await file.download_to_drive(svg_path)

    caption = (update.message.caption or "").strip()
    parts = caption.split(None, 1)
    workout_time = parts[0] if parts and re.match(r'\d{1,2}:\d{2}', parts[0]) else (
        pending_card.get("practice_time", "22:00") if card_type == "practice" else "17:00"
    )
    description = parts[1] if len(parts) > 1 else (parts[0] if parts else (
        "Вечерняя Практика" if card_type == "practice" else "Тренировка Brotherhood"
    ))

    pending_card.pop(MY_ID, None)
    pending_card.pop("practice_time", None)

    if card_type == "practice":
        await _publish_card(svg_path, workout_time, description, update, context,
                           cleanup=True, poll_options=["Буду 🙏", "Не Будду"],
                           poll_question="Будете на практике?")
    else:
        workout_data = last_workout_data.get("exercises")
        await _publish_card(svg_path, workout_time, description, update, context,
                           cleanup=True, workout_data=workout_data)


def push_timer_to_github(timer_html: str) -> bool:
    """Пушит timer.html на GitHub."""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    api_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/timer.html"
    r = requests.get(api_url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None

    encoded = base64.b64encode(timer_html.encode("utf-8")).decode("utf-8")
    payload = {"message": "Update timer", "content": encoded}
    if sha:
        payload["sha"] = sha

    put_r = requests.put(api_url, headers=headers, json=payload)
    logging.info(f"Timer GitHub PUT: {put_r.status_code}")
    return put_r.status_code in (200, 201)


def build_timer_html(workout: list, title: str) -> str:
    """Генерирует timer.html с упражнениями текущей тренировки."""
    import json
    # Читаем шаблон из файла
    template_path = os.path.join(BASE_DIR, "timer_template.html")
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()
    workout_json = json.dumps(workout, ensure_ascii=False)
    return template.replace("__WORKOUT_JSON__", workout_json).replace("__TITLE__", title)


async def _publish_card(svg_path, workout_time, description, update, context,
                        cleanup=False, workout_data=None,
                        poll_question=None, poll_options=None):
    """Конвертирует SVG → PNG, отправляет в группу и обновляет timer.html на GitHub."""
    await update.message.reply_text("⏳ Конвертирую карточку...")

    try:
        png_data = await svg_to_png(svg_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка конвертации: {e}\n\nУстанови cairosvg: pip install cairosvg")
        return
    finally:
        if cleanup and os.path.exists(svg_path):
            os.remove(svg_path)

    caption = (
        f"⚔️ Тренировка сегодня — {workout_time}\n"
        f"{description}\n\n"
        f"Присоединиться → {SITE_URL}"
    )

    await context.bot.send_photo(
        chat_id=GROUP_ID,
        photo=io.BytesIO(png_data),
        caption=caption,
        message_thread_id=ANNOUNCE_THREAD_ID
    )

    # Опрос — кастомный или стандартный для тренировки
    q = poll_question or "Будете сегодня? 💪"
    opts = poll_options or ["Не тряпка 🔥", "Пропущу", "Не смогу"]

    poll_msg = await context.bot.send_poll(
        chat_id=GROUP_ID,
        question=q,
        options=opts,
        is_anonymous=False,
        message_thread_id=ANNOUNCE_THREAD_ID
    )

    if workout_data:
        exercise_names = [ex.get("name", "").strip() for ex in workout_data if ex.get("name")]
        meta = {"exercises": exercise_names, "muscles": description, "workout_time": workout_time}
        TRAINING_POLLS[poll_msg.poll.id] = meta
        save_training_poll(poll_msg.poll.id, meta)

    # Обновляем timer.html на GitHub если есть данные тренировки
    if workout_data:
        timer_html = build_timer_html(workout_data, description)
        ok = push_timer_to_github(timer_html)
        status = "✅ Таймер обновлён на GitHub!" if ok else "⚠️ Не удалось обновить таймер на GitHub"
        await update.message.reply_text(f"✅ Карточка и опрос отправлены в группу!\n{status}")
    else:
        await update.message.reply_text("✅ Карточка и опрос отправлены в группу!")


# ─── Main ─────────────────────────────────────────────────────────────────────
# ─── Приветствие новых участников ─────────────────────────────────────────────
async def greet_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        name = member.first_name or "друг"
        text = (
            f"Добро пожаловать, {name}. 🤜🤛\n"
            "Для начала загляни в «Правила» — там объясняется, "
            "как всё устроено и с чего начать."
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📜 Читать правила", url=RULES_URL)
        ]])
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=keyboard,
            message_thread_id=update.message.message_thread_id
        )


def build_training_dm(display_name: str, telegram_id: str, meta: dict) -> str:
    lines = [
        f"Привет, {display_name}! 👋",
        "",
        f"Сегодня у тебя тренировка — {meta['workout_time']}, {meta['muscles']}.",
        "",
        "Задачи на сегодня:",
    ]

    for ex in meta["exercises"]:
        key, info = match_bodyweight_exercise(ex)
        if not key:
            continue
        pr = fetch_personal_record(f"tg_{telegram_id}", key)
        if pr is None:
            continue
        target = pr + info["step"]
        lines.append(
            f"{ex} — <b>{pr:g} {info['unit']}</b>, цель на сегодня <b>{target:g} {info['unit']}</b>."
        )

    lines += [
        "",
        "Как отработаешь — напиши мне /go, чтобы результат попал в статистику.",
        "",
        "Хорошей тренировки! 💪",
    ]
    return "\n".join(lines)


async def on_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кто-то ответил на опрос в группе. Если это сегодняшний опрос
    «Будете сегодня?» и человек выбрал «Буду» — пишем ему в личку список
    упражнений на сегодня и его личные рекорды по СенПаю."""
    answer = update.poll_answer
    meta = TRAINING_POLLS.get(answer.poll_id) or fetch_training_poll(answer.poll_id)
    if not meta:
        return
    if 0 not in answer.option_ids:
        return  # отметил "Пропущу"/снял голос — не пишем

    user = answer.user
    telegram_id = str(user.id)
    display_name = fetch_profile_name(telegram_id) or user.first_name or "боец"

    text = build_training_dm(display_name, telegram_id, meta)
    ok, err = send_as_senpai(user.id, text)
    if not ok:
        logging.warning("СенПай не смог написать %s (%s): %s", display_name, telegram_id, err)
        try:
            await context.bot.send_message(
                chat_id=MY_ID,
                text=f"⚠ СенПай не смог написать {display_name} (id {telegram_id}) в личку — "
                     f"он(а) ещё ни разу не запускал(а) {SENPAI_USERNAME}. "
                     f"Попроси его/её написать /start этому боту хотя бы раз.",
            )
        except Exception:
            pass


async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("sport", cmd_sport))
    app.add_handler(CommandHandler("med", cmd_med))
    app.add_handler(CommandHandler("practice", cmd_practice))
    app.add_handler(CommandHandler("skip", cmd_practice_send))
    app.add_handler(CommandHandler("setworkout", cmd_setworkout))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_card_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_workout_json), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message), group=1)
    app.add_handler(CallbackQueryHandler(inventory_callback, pattern=r"^inv:"))
    app.add_handler(CommandHandler("poll", cmd_poll))
    app.add_handler(CommandHandler("pain", cmd_pain))
    app.add_handler(CommandHandler("porabotaem", cmd_porabotaem))
    app.add_handler(CommandHandler("buddu", cmd_buddu))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, greet_new_member))
    app.add_handler(PollAnswerHandler(on_poll_answer))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^привет\W*$"), cmd_start), group=2)

    # Расписание
    async def job_auto_rest(ctx):
        await auto_rest(ctx.application)
    async def job_morning_ask(ctx):
        await morning_ask(ctx.application)

    app.job_queue.run_daily(job_auto_rest,   time=time(0, 1))
    app.job_queue.run_daily(job_morning_ask,  time=time(9, 0))

    print("Бот запущен!")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
