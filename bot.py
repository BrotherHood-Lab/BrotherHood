import base64
import logging
import os
import re
import requests

from datetime import time
from telegram import Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
MY_ID = int(os.getenv("MY_ID"))
GROUP_ID = int(os.getenv("GROUP_ID"))

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USER = os.getenv("GITHUB_USER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_FILE = os.getenv("GITHUB_FILE", "BrotherHood.html")

waiting_for_workout = False


def update_landing(description: str) -> bool:
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{GITHUB_FILE}"

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        logging.error(r.text)
        return False

    data = r.json()

    sha = data["sha"]
    content = base64.b64decode(data["content"]).decode()

    new_content = re.sub(
        r'<p class="today-desc[^"]*">.*?</p>',
        f'<p class="today-desc">{description}</p>',
        content,
        flags=re.DOTALL,
    )

    if content == new_content:
        logging.warning("today-desc не найден")
        return False

    encoded = base64.b64encode(new_content.encode()).decode()

    payload = {
        "message": "Update workout",
        "content": encoded,
        "sha": sha,
    }

    r = requests.put(url, headers=headers, json=payload)

    return r.status_code in (200, 201)


async def ask_workout(context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_workout

    waiting_for_workout = True

    await context.bot.send_message(
        chat_id=MY_ID,
        text="💪 Привет! Какая тренировка сегодня?"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_workout

    if update.effective_chat.id != MY_ID:
        return

    if not waiting_for_workout:
        return

    waiting_for_workout = False

    workout = update.message.text

    ok = update_landing(workout)

    if ok:
        await update.message.reply_text("✅ Лендинг обновлен")
    else:
        await update.message.reply_text("❌ Ошибка обновления")

    await context.bot.send_message(
        chat_id=GROUP_ID,
        text=f"💪 Сегодняшняя тренировка:\n\n{workout}",
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    app.job_queue.run_daily(
        ask_workout,
        time=time(hour=9, minute=0),
    )

    print("✅ Бот успешно запущен")

    app.run_polling()


if __name__ == "__main__":
    main()