"""
Brotherhood SenPai — бот учёта результатов тренировок.

Любой участник записывает сегодняшний результат по упражнению прямо в
Supabase (таблица exercise_logs) — оттуда его сразу подхватывает личный
кабинет (nutrition.thebrotherhoodclub.com/training/): разряд, стрик и
тренд считаются уже на сайте, здесь дублируется только простая сводка.

Команды:
  /start (или просто "привет") — знакомство: кто это и что делает
  /go (или "на сегодня" / "привет сенпай") — сводка на сегодня + кнопки прямо под сообщением, чтобы отметить результат
  /name (или "имя") — сменить имя, как обращаться
  /stats  — сводка по всем упражнениям за всё время
  /cancel — отменить текущую запись
"""

import os
import logging
from datetime import datetime, timezone, timedelta

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
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

COMMANDS_BUTTON_TEXT = "📋 Список команд"
COMMANDS_KEYBOARD = ReplyKeyboardMarkup(
    [[COMMANDS_BUTTON_TEXT]], resize_keyboard=True, is_persistent=True
)

HELP_TEXT = (
    "Как со мной общаться:\n\n"
    "/go (или «на сегодня», или «привет сенпай») — отметить сегодняшний результат\n"
    "/name — сменить имя, как к тебе обращаться\n"
    "/stats — статистика по всем упражнениям\n"
    "/cancel — отменить текущую запись\n\n"
    "Можно и без слэша: «привет» работает как /start, «на сегодня» и «привет сенпай» — как /go."
)


# Зеркало EXERCISE_CONFIG из training/index.html — держать в соответствии,
# иначе разряды в боте и на сайте разъедутся.
EXERCISE_CONFIG = {
    "pushups": {
        "label": "Отжимания", "unit": "раз",
        "ranks": [(0, "Новичок"), (10, "Ученик"), (15, "Боец"), (25, "Ронин"),
                  (40, "Воин"), (50, "Самурай"), (60, "Мастер"), (75, "Легенда додзё")],
    },
    "pullups": {
        "label": "Подтягивания", "unit": "раз",
        "ranks": [(0, "Новичок"), (4, "Ученик"), (7, "Боец"), (10, "Ронин"),
                  (15, "Воин"), (20, "Самурай"), (30, "Мастер"), (35, "Легенда додзё")],
    },
    "squats": {
        "label": "Приседания", "unit": "раз",
        "ranks": [(0, "Новичок"), (10, "Ученик"), (20, "Боец"), (30, "Ронин"),
                  (40, "Воин"), (60, "Самурай"), (75, "Мастер"), (100, "Легенда додзё")],
    },
    "plank": {
        "label": "Планка", "unit": "сек",
        "ranks": [(30, "Новичок"), (60, "Ученик"), (90, "Боец"), (120, "Ронин"),
                  (180, "Воин"), (300, "Самурай"), (400, "Мастер"), (600, "Легенда додзё")],
    },
    "ladder": {
        "label": "Лесенка", "unit": "ступень", "is_ladder": True, "max": 10,
        "ranks": [(1, "Новичок"), (3, "Ученик"), (5, "Боец"), (7, "Ронин"), (9, "Воин"), (10, "Самурай")],
    },
    "bench_dips": {
        "label": "Скамейка", "unit": "раз",
        "ranks": [(0, "Новичок"), (10, "Ученик"), (20, "Боец"), (35, "Ронин"),
                  (45, "Воин"), (65, "Самурай"), (75, "Мастер"), (100, "Легенда додзё")],
    },
}
EXERCISE_ORDER = ["pushups", "pullups", "squats", "plank", "ladder", "bench_dips"]

# Таблица прогрессии подтягиваний 5x30 — 30 недель, 5 подходов, индекс 0 = неделя 1.
# Зеркалируется в JS-константе PULLUP_PLAN в training.html — держать в соответствии.
PULLUP_PLAN = [
    (6, 5, 5, 4, 3), (7, 6, 5, 4, 4), (8, 6, 5, 5, 4), (8, 7, 5, 5, 5), (9, 7, 6, 5, 5),
    (10, 7, 6, 6, 5), (10, 8, 6, 6, 6), (11, 8, 7, 6, 6), (12, 8, 7, 7, 6), (12, 9, 7, 7, 7),
    (13, 9, 8, 7, 7), (14, 9, 8, 8, 7), (14, 10, 8, 8, 8), (15, 10, 9, 8, 8), (16, 10, 9, 9, 8),
    (16, 11, 9, 9, 9), (17, 11, 10, 9, 9), (18, 11, 10, 10, 9), (18, 12, 10, 10, 10), (19, 12, 11, 10, 10),
    (20, 12, 11, 11, 10), (20, 13, 11, 11, 11), (21, 13, 12, 11, 11), (22, 13, 12, 12, 11), (22, 14, 12, 12, 12),
    (23, 14, 13, 12, 12), (24, 14, 13, 13, 12), (24, 15, 13, 13, 13), (25, 15, 14, 13, 13), (26, 15, 14, 14, 13),
]


def plan_for_week(week: int) -> tuple:
    """Целевые 5 подходов для недели, week зажимается в диапазон 1..30."""
    week = max(1, min(30, week))
    return PULLUP_PLAN[week - 1]


def find_starting_week(first_set: int) -> int:
    """Максимальная неделя плана, где Подход1 <= first_set (колонка Подход1
    не убывает от недели к неделе, так что это просто её последнее вхождение
    не выше first_set); неделя 1, если first_set меньше минимума таблицы."""
    week = 1
    for i, targets in enumerate(PULLUP_PLAN, start=1):
        if targets[0] <= first_set:
            week = i
        else:
            break
    return week


ASK_NAME, CHOOSING, ENTERING, ASK_PULLUP_START, PULLUP_CONFIRM = range(5)

# Общий порядок званий — одинаковый для всех упражнений (лесенка упирается в
# потолок "Самурай"). Общий статус участника = звание САМОГО СЛАБОГО
# упражнения, а не среднее и не проценты — так сразу видно, что подтягивать.
RANK_ORDER = ["Новичок", "Ученик", "Боец", "Ронин", "Воин", "Самурай", "Мастер", "Легенда додзё"]


def rank_index(name):
    try:
        return RANK_ORDER.index(name)
    except ValueError:
        return 0


def rank_for_value(cfg, value):
    name = cfg["ranks"][0][1]
    for bound, rname in cfg["ranks"]:
        if value >= bound:
            name = rname
        else:
            break
    return name


def next_rank_after(cfg, value):
    """Следующее звание и порог для него, или (None, None) если это потолок."""
    for bound, rname in cfg["ranks"]:
        if bound > value:
            return rname, bound
    return None, None


def unit_plural(cfg):
    return "ступеней" if cfg.get("is_ladder") else cfg["unit"]


def today_str():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def save_exercise(user_id: str, exercise: str, value: float, unit: str, partial: float = None) -> bool:
    payload = {"user_id": user_id, "exercise": exercise, "value": value, "date": today_str(), "unit": unit}
    payload["partial"] = partial
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
                "select": "value,date,partial",
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


def fetch_pullup_program(user_id: str):
    """Текущая неделя программы подтягиваний, или None если ещё не начата
    (или запрос не удался — как и fetch_display_name, эти случаи не различаются)."""
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/pullup_program",
            headers=HEADERS,
            params={"user_id": f"eq.{user_id}", "select": "current_week", "limit": 1},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        logger.error("Supabase fetch pullup_program failed: %s", e)
        return None
    if resp.status_code >= 300:
        logger.error("Supabase fetch pullup_program error: %s %s", resp.status_code, resp.text)
        return None
    rows = resp.json()
    return rows[0]["current_week"] if rows else None


def save_pullup_program(user_id: str, week: int, started_at: str = None) -> bool:
    payload = {"user_id": user_id, "current_week": week}
    if started_at:
        payload["started_at"] = started_at
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/pullup_program",
            headers={**HEADERS, "Prefer": "resolution=merge-duplicates"},
            params={"on_conflict": "user_id"},
            json=payload,
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        logger.error("Supabase save pullup_program failed: %s", e)
        return False
    if resp.status_code >= 300:
        logger.error("Supabase save pullup_program error: %s %s", resp.status_code, resp.text)
        return False
    return True


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


def compute_overall_status(uid: str):
    """Звание по самому слабому упражнению, или None, если данных ещё нет."""
    best = None
    for key in EXERCISE_ORDER:
        cfg = EXERCISE_CONFIG[key]
        history = fetch_history(uid, key)
        if not history:
            continue
        pr = max(float(h["value"]) for h in history)
        rank = rank_for_value(cfg, pr)
        if best is None or rank_index(rank) < rank_index(best):
            best = rank
    return best


# ── /start — знакомство. Спрашиваем имя один раз, дальше используем его,
# а не телеграмный логин/first_name. ──
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = raw_telegram_id(update)
    name = fetch_display_name(telegram_id)
    if name:
        await send_greeting(update, name, telegram_id)
        return ConversationHandler.END

    await update.message.reply_text(
        "Привет! Я СенПай, твой помощник по тренировкам в Brotherhood. 👋\n\n"
        "Как мне к тебе обращаться?"
    )
    return ASK_NAME


async def save_name_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    save_display_name(raw_telegram_id(update), name)
    if context.user_data.pop("renaming", False):
        await update.message.reply_text(
            f"Готово, теперь буду звать тебя {name} 👊", reply_markup=COMMANDS_KEYBOARD
        )
    else:
        await send_greeting(update, name, raw_telegram_id(update))
    return ConversationHandler.END


async def cmd_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["renaming"] = True
    await update.message.reply_text("Как мне теперь к тебе обращаться?")
    return ASK_NAME


async def send_greeting(update: Update, name: str, telegram_id: str):
    status = compute_overall_status(f"tg_{telegram_id}")
    opening = f"Привет, {status} {name}! 👊" if status else f"Привет, {name}! 👊"
    await update.message.reply_text(
        f"{opening}\n\n"
        "Буду записывать твои результаты, считать разряды и серию тренировок "
        "подряд — чтобы тебе не приходилось держать это в голове.\n\n"
        "/go (или просто напиши «на сегодня» / «привет сенпай») — отметить сегодняшний результат\n"
        "/name — сменить имя, если захочешь\n"
        "/stats — статистика по всем упражнениям\n\n"
        f"А ещё загляни на сайт — {SITE_URL} — и нажми там кнопку «Войти», "
        "чтобы попасть в свой личный кабинет: там разряды, серия и графики уже "
        "собраны вместе.",
        reply_markup=COMMANDS_KEYBOARD,
    )


def picker_keyboard():
    rows = [[InlineKeyboardButton(EXERCISE_CONFIG[k]["label"], callback_data=f"ex:{k}")] for k in EXERCISE_ORDER]
    rows.append([InlineKeyboardButton("Готово ✅", callback_data="done")])
    return InlineKeyboardMarkup(rows)


def build_today_text(uid: str, name: str = None) -> str:
    today = today_str()
    header = f"{name}, вот твоя сводка на {today}:" if name else f"Сегодня, {today}"

    rows = []
    for key in EXERCISE_ORDER:
        cfg = EXERCISE_CONFIG[key]
        history = fetch_history(uid, key)
        pr = max(float(h["value"]) for h in history) if history else None
        rank = rank_for_value(cfg, pr) if pr is not None else None
        rows.append({"key": key, "cfg": cfg, "history": history, "pr": pr, "rank": rank})

    tracked = [r for r in rows if r["rank"] is not None]
    weakest_keys = set()
    if tracked:
        min_idx = min(rank_index(r["rank"]) for r in tracked)
        weakest_keys = {r["key"] for r in tracked if rank_index(r["rank"]) == min_idx}

    blocks = [header]
    if tracked:
        weakest_rows = [r for r in tracked if r["key"] in weakest_keys]
        overall_rank = weakest_rows[0]["rank"]
        parts = []
        for r in weakest_rows:
            next_name, next_bound = next_rank_after(r["cfg"], r["pr"])
            if next_name:
                parts.append(
                    f"{r['cfg']['label']} (ещё {next_bound - r['pr']:g} {unit_plural(r['cfg'])} до «{next_name}»)"
                )
            else:
                parts.append(f"{r['cfg']['label']} (на потолке)")
        label = "слабое место" if len(parts) == 1 else "слабые места"
        blocks.append(f"Общий статус: {overall_rank} · {label} — " + ", ".join(parts))

    for r in rows:
        key, cfg, history, pr, rank = r["key"], r["cfg"], r["history"], r["pr"], r["rank"]
        mark = "👉 " if key in weakest_keys else ""
        if not history:
            blocks.append(f"{mark}{cfg['label']} — нет данных\nсегодня: ещё не отмечено")
            continue
        next_name, next_bound = next_rank_after(cfg, pr)
        remain = max(0, next_bound - pr) if next_name else 0
        last = history[-1]
        if last["date"] == today:
            today_val = f"{float(last['value']):g} {cfg['unit']}"
            if last.get("partial") is not None:
                today_val += f" (на след. ступени дошёл до {float(last['partial']):g})"
        else:
            today_val = "ещё не отмечено"

        line = f"{mark}{cfg['label']} — {rank}"
        if remain > 0:
            line += f" · осталось {remain:g} {unit_plural(cfg)} до «{next_name}»"
        if cfg.get("is_ladder"):
            line += f"\nследующая ступень: {min(cfg['max'], pr + 1):g}"
        line += f"\nсегодня: {today_val}"
        blocks.append(line)
    return "\n\n".join(blocks)


# ── /go — сводка + кнопки под сообщением ──
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = user_id_for(update)
    name = fetch_display_name(raw_telegram_id(update))
    await update.message.reply_text(build_today_text(uid, name), reply_markup=picker_keyboard())
    return CHOOSING


def pullup_plan_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Сделал", callback_data="pullup:done"),
        InlineKeyboardButton("❌ Не сделал", callback_data="pullup:skip"),
    ]])


def format_pullup_plan_text(week: int) -> str:
    targets = plan_for_week(week)
    sets_line = " / ".join(str(t) for t in targets)
    header = "Неделя 30 из 30 (финал программы)" if week >= 30 else f"Неделя {week} из 30"
    return f"Подтягивания — {header}:\n{sets_line}\n\nСделал сегодня все 5 подходов?"


async def show_pullup_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, week: int, edit: bool):
    context.user_data["pullup_week"] = week
    text = format_pullup_plan_text(week)
    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=pullup_plan_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=pullup_plan_keyboard())
    return PULLUP_CONFIRM


async def enter_pullup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip().replace(",", ".")
    try:
        first_set = int(float(raw))
    except ValueError:
        await update.message.reply_text("Нужно число, например 8. Попробуй ещё раз.")
        return ASK_PULLUP_START

    week = find_starting_week(first_set)
    uid = user_id_for(update)
    if not save_pullup_program(uid, week, started_at=today_str()):
        await update.message.reply_text("Не получилось сохранить — попробуй ещё раз чуть позже.")
        return ConversationHandler.END

    return await show_pullup_plan(update, context, week, edit=False)


async def pullup_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    done = query.data.split(":", 1)[1] == "done"
    week = context.user_data.get("pullup_week", 1)
    uid = user_id_for(update)

    if not done:
        await query.edit_message_text("Ок, повторим в следующий раз. Цели этой недели остаются прежними.")
    else:
        cfg = EXERCISE_CONFIG["pullups"]
        targets = plan_for_week(week)
        value = max(targets)

        if not save_exercise(uid, "pullups", value, cfg["unit"]):
            await query.edit_message_text("Не получилось сохранить результат — попробуй ещё раз чуть позже.")
            return CHOOSING

        next_week = min(30, week + 1)
        save_pullup_program(uid, next_week)

        rank = rank_for_value(cfg, value)
        next_name, next_bound = next_rank_after(cfg, value)
        remain = max(0, next_bound - value) if next_name else 0

        text = f"Записано: Подтягивания — {value:g}\nРазряд: {rank}"
        if remain > 0:
            text += f" · осталось {remain:g} {unit_plural(cfg)} до «{next_name}»"
        text += "\n\nПрограмма завершена 🏆" if week >= 30 else f"\n\nНеделя выросла до {next_week} из 30!"
        await query.edit_message_text(text)

    name = fetch_display_name(raw_telegram_id(update))
    await query.message.reply_text(build_today_text(uid, name), reply_markup=picker_keyboard())
    return CHOOSING


async def choose_exercise_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    context.user_data["exercise"] = key

    if key == "pullups":
        uid = user_id_for(update)
        week = fetch_pullup_program(uid)
        if week is None:
            await query.edit_message_text(
                "Сколько подтягиваний одним подходом можешь сделать сейчас? "
                "По этому числу подберём стартовую неделю программы."
            )
            return ASK_PULLUP_START
        return await show_pullup_plan(update, context, week, edit=True)

    cfg = EXERCISE_CONFIG[key]
    prompt = f"{cfg['label']} — сколько сделал сегодня? ({cfg['unit']})"
    if cfg.get("is_ladder"):
        prompt += (
            "\n\nЕсли начал следующую ступень, но не одолел её целиком — "
            "напиши через слэш: сначала ступень, до которой дошёл полностью, "
            "потом сколько сделал на следующей. Например 8/6 — восьмая ступень "
            "пройдена, а на девятой сделал только 6."
        )
    await query.edit_message_text(prompt, reply_markup=None)
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
    partial = None
    try:
        if "/" in raw:
            head, tail = raw.split("/", 1)
            value = float(head.strip())
            partial = float(tail.strip())
        else:
            value = float(raw)
    except ValueError:
        await update.message.reply_text(
            "Нужно число, например 45, или пройденная ступень и попытка следующей "
            "через слэш, например 8/6. Попробуй ещё раз."
        )
        return ENTERING

    key = context.user_data["exercise"]
    cfg = EXERCISE_CONFIG[key]
    uid = user_id_for(update)

    if not save_exercise(uid, key, value, cfg["unit"], partial):
        await update.message.reply_text("Не получилось сохранить — попробуй ещё раз чуть позже.")
        return ConversationHandler.END

    rank = rank_for_value(cfg, value)
    next_name, next_bound = next_rank_after(cfg, value)
    remain = max(0, next_bound - value) if next_name else 0

    text = f"Записано: {cfg['label']} — {value:g}"
    if partial is not None:
        text += f"\nНа следующей ступени дошёл до {partial:g} — это не в счёт, просто для истории"
    text += f"\nРазряд: {rank}"
    if remain > 0:
        text += f" · осталось {remain:g} {unit_plural(cfg)} до «{next_name}»"
    if cfg.get("is_ladder"):
        text += f"\nСледующая ступень: {min(cfg['max'], value + 1):g}"
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

    rows = []
    for key in EXERCISE_ORDER:
        cfg = EXERCISE_CONFIG[key]
        history = fetch_history(uid, key)
        pr = max(float(h["value"]) for h in history) if history else None
        rank = rank_for_value(cfg, pr) if pr is not None else None
        rows.append({"key": key, "cfg": cfg, "history": history, "pr": pr, "rank": rank})

    tracked = [r for r in rows if r["rank"] is not None]
    weakest_keys = set()
    if tracked:
        min_idx = min(rank_index(r["rank"]) for r in tracked)
        weakest_keys = {r["key"] for r in tracked if rank_index(r["rank"]) == min_idx}

    lines = []
    if tracked:
        weakest_rows = [r for r in tracked if r["key"] in weakest_keys]
        overall_rank = weakest_rows[0]["rank"]
        parts = []
        for r in weakest_rows:
            next_name, next_bound = next_rank_after(r["cfg"], r["pr"])
            if next_name:
                parts.append(
                    f"{r['cfg']['label']} (ещё {next_bound - r['pr']:g} {unit_plural(r['cfg'])} до «{next_name}»)"
                )
            else:
                parts.append(f"{r['cfg']['label']} (на потолке)")
        label = "слабое место" if len(parts) == 1 else "слабые места"
        lines.append(f"Общий статус: {overall_rank} · {label} — " + ", ".join(parts))
        lines.append("")

    for r in rows:
        key, cfg, history, pr, rank = r["key"], r["cfg"], r["history"], r["pr"], r["rank"]
        mark = "👉 " if key in weakest_keys else ""
        if not history:
            lines.append(f"{mark}{cfg['label']} — нет данных")
            continue
        current = float(history[-1]["value"])
        next_name, next_bound = next_rank_after(cfg, pr)
        remain = max(0, next_bound - pr) if next_name else 0
        week_count = sum(1 for h in history if h["date"] >= week_ago)

        line = f"{mark}{cfg['label']}: {current:g} {cfg['unit']} · {rank}"
        if remain > 0:
            line += f" (осталось {remain:g} {unit_plural(cfg)} до «{next_name}»)"
        line += f" · за неделю: {week_count}"
        lines.append(line)

        if key == "pullups":
            program_week = fetch_pullup_program(uid)
            if program_week is not None:
                lines.append(
                    "  Программа: завершена 🏆" if program_week >= 30
                    else f"  Программа: неделя {program_week} из 30"
                )

    await update.message.reply_text("Твоя статистика:\n\n" + "\n".join(lines))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, reply_markup=COMMANDS_KEYBOARD)


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
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.Regex(r"(?i)^привет\W*$"), cmd_start),
            CommandHandler("name", cmd_rename),
            MessageHandler(filters.Regex(r"(?i)^/?имя\W*$"), cmd_rename),
        ],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_name_step)],
        },
        fallbacks=[
            CommandHandler("start", cmd_start),
            CommandHandler("name", cmd_rename),
            MessageHandler(filters.Regex(r"(?i)^/?имя\W*$"), cmd_rename),
        ],
    )

    today_conv = ConversationHandler(
        entry_points=[
            CommandHandler("go", cmd_today),
            MessageHandler(filters.Regex(r"(?i)^на\s*сегодня\W*$"), cmd_today),
            MessageHandler(filters.Regex(r"(?i)^привет[,!]?\s+сенпай\W*$"), cmd_today),
        ],
        states={
            CHOOSING: [
                CallbackQueryHandler(choose_exercise_cb, pattern=r"^ex:"),
                CallbackQueryHandler(finish_cb, pattern=r"^done$"),
                MessageHandler(filters.Regex(f"^{COMMANDS_BUTTON_TEXT}$"), cmd_help),
            ],
            ENTERING: [
                MessageHandler(filters.Regex(f"^{COMMANDS_BUTTON_TEXT}$"), cmd_help),
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_value),
            ],
            ASK_PULLUP_START: [
                MessageHandler(filters.Regex(f"^{COMMANDS_BUTTON_TEXT}$"), cmd_help),
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_pullup_start),
            ],
            PULLUP_CONFIRM: [
                CallbackQueryHandler(pullup_confirm_cb, pattern=r"^pullup:"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("go", cmd_today),
            MessageHandler(filters.Regex(r"(?i)^на\s*сегодня\W*$"), cmd_today),
            MessageHandler(filters.Regex(r"(?i)^привет[,!]?\s+сенпай\W*$"), cmd_today),
            CommandHandler("start", cmd_start),
        ],
    )

    app.add_handler(start_conv)
    app.add_handler(today_conv)
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.Regex(f"^{COMMANDS_BUTTON_TEXT}$"), cmd_help))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
