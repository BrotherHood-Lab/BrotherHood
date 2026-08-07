import asyncio
import base64
import json
import logging
import os
import requests
from datetime import time
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# ========================
# НАСТРОЙКИ
# ========================
BOT_TOKEN = "8839542347:AAHjL7cSQivzl4beSu9LNA3wLup4T2Qc654"
MY_ID = 385041328
GROUP_ID = -5161396226
GITHUB_TOKEN = "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"
GITHUB_USER = "BrotherHood-Lab"
GITHUB_REPO = "BrotherHood"
GITHUB_FILE = "index.html"

# ========================
logging.basicConfig(level=logging.INFO)
waiting_for_workout = False


def update_landing(description: str) -> bool:
    """Обновляет секцию 'Сегодня' в HTML файле на GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    # Получаем текущий файл
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        logging.error(f"Ошибка получения файла: {r.text}")
        return False

    data = r.json()
    sha = data["sha"]
    content = base64.b64decode(data["content"]).decode("utf-8")

    # Заменяем описание тренировки
    import re
    new_content = re.sub(
        r'<p class="today-desc[^"]*">.*?</p>',
        f'<p class="today-desc">{description}</p>',
        content,
        flags=re.DOTALL
    )

    if new_content == content:
        logging.warning("Не удалось найти today-desc в HTML")
        return False

    # Загружаем обратно
    encoded = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
    payload = {
        "message": "Обновление тренировки на сегодня",
        "content": encoded,
        "sha": sha
    }

    r2 = requests.put(url, headers=headers, json=payload)
    return r2.status_code in (200, 201)


async def ask_workout(app: Application):
    """Бот пишет тебе первым."""
    global waiting_for_workout
    waiting_for_workout = True
    await app.bot.send_message(
        chat_id=MY_ID,
        text="Привет! 💪 Какая тренировка сегодня?"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ответ на вопрос о тренировке."""
    global waiting_for_workout

    # Только сообщения от тебя в личке
    if update.effective_chat.id != MY_ID:
        return

    if not waiting_for_workout:
        return

    workout_text = update.message.text
    waiting_for_workout = False

    # Обновляем лендинг
    success = update_landing(workout_text)

    if success:
        await update.message.reply_text("✅ Лендинг обновлён!")
    else:
        await update.message.reply_text("⚠️ Не удалось обновить лендинг, проверь логи.")

    # Постим в группу
    await context.bot.send_message(
        chat_id=GROUP_ID,
        text=f"💪 Тренировка сегодня:\n\n{workout_text}"
    )


async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запускаем расписание — каждый день в 9:00
    job_queue = app.job_queue
    job_queue.run_daily(
        lambda ctx: asyncio.create_task(ask_workout(app)),
        time=time(hour=9, minute=0)
    )

    print("Бот запущен! Жду 9:00 для первого вопроса.")
    print("Или отправь боту /test чтобы проверить прямо сейчас.")

    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
