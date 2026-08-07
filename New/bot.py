import asyncio
import base64
import logging
import re
import requests
from datetime import time
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

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

logging.basicConfig(level=logging.INFO)
waiting_for_workout = False


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
        for item in re.split(r',', line):
            item = item.strip()
            if item:
                exercises.append(item.capitalize())

    return workout_time, muscles_str, exercises


def build_inner_html(workout_time, muscles, exercises):
    items_html = "".join(
        f'<li class="today-exercise-item"><span class="today-exercise-dot"></span>{ex}</li>'
        for ex in exercises
    )
    return (
        f'<div class="today-header-row">'
        f'<p class="today-muscles">{muscles}</p>'
        f'<div class="today-time-block">'
        f'<p class="today-time-label">&#1053;&#1072;&#1095;&#1072;&#1083;&#1086;</p>'
        f'<p class="today-time-value">{workout_time}</p>'
        f'</div></div>'
        f'<ul class="today-exercise-list">{items_html}</ul>'
    )


def build_tg_message(workout_time, muscles, exercises):
    muscles_line = muscles.replace(" · ", ", ")
    ex_lines = "\n".join(f"• {ex}" for ex in exercises)
    return f"\U0001f4aa Тренировка сегодня — {workout_time}\n{muscles_line}\n\n{ex_lines}"


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


async def ask_workout(app):
    global waiting_for_workout
    waiting_for_workout = True
    await app.bot.send_message(chat_id=MY_ID, text="Привет! 💪 Какая тренировка сегодня?\n\nФормат:\n17:00, Плечи, Грудь\nПриседания, бой с тенью\nОтжимания х4")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_workout

    if update.effective_chat.id != MY_ID:
        return

    if not waiting_for_workout:
        waiting_for_workout = True
        await update.message.reply_text("Окей, жду описание тренировки!\n\nФормат:\n17:00, Плечи, Грудь\nПриседания х4\nБег х5")
        return

    workout_text = update.message.text
    waiting_for_workout = False

    # Проверяем растяжку
    if workout_text.strip().lower().startswith("растяжка"):
        parts = workout_text.strip().split()
        stretch_time = parts[1] if len(parts) > 1 else "22:00"
        stretch_html = (
            '<div class="today-header-row">'
            '<p class="today-muscles">Растяжка</p>'
            '<div class="today-time-block">'
            '<p class="today-time-label">&#1053;&#1072;&#1095;&#1072;&#1083;&#1086;</p>'
            f'<p class="today-time-value">{stretch_time}</p>'
            '</div></div>'
            '<ul class="today-exercise-list">'
            '<li class="today-exercise-item"><span class="today-exercise-dot"></span>Растяжка всего тела</li>'
            '</ul>'
        )
        tg_message = f"🧘 Растяжка сегодня — {stretch_time}"
        success = update_landing(stretch_html)
        if success:
            await update.message.reply_text(f"✅ Лендинг обновлён!\n\n{tg_message}")
        else:
            await update.message.reply_text("⚠️ Не удалось обновить лендинг.")
        await context.bot.send_message(chat_id=GROUP_ID, text=tg_message)
        return

    # Проверяем выходной
    rest_keywords = ["выходной", "отдых", "отдыхаем", "rest", "день отдыха"]
    if any(kw in workout_text.lower() for kw in rest_keywords):
        rest_html = (
            '<div class="today-header-row">'
            '<p class="today-muscles">День отдыха</p>'
            '</div>'
            '<ul class="today-exercise-list">'
            '<li class="today-exercise-item today-empty">Сегодня выходной. Отдыхаем</li>'
            '</ul>'
        )
        tg_message = "😴 Сегодня выходной. Отдыхаем!"
        success = update_landing(rest_html)
        if success:
            await update.message.reply_text("✅ Лендинг обновлён — выходной!")
        else:
            await update.message.reply_text("⚠️ Не удалось обновить лендинг.")
        await context.bot.send_message(chat_id=GROUP_ID, text=tg_message)
        return

    workout_time, muscles, exercises = parse_workout(workout_text)
    inner_html = build_inner_html(workout_time, muscles, exercises)
    tg_message = build_tg_message(workout_time, muscles, exercises)

    success = update_landing(inner_html)

    if success:
        await update.message.reply_text(f"✅ Лендинг обновлён!\n\n{tg_message}")
    else:
        await update.message.reply_text("⚠️ Не удалось обновить лендинг.")

    await context.bot.send_message(chat_id=GROUP_ID, text=tg_message)


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
