#!/usr/bin/env python3
# telegram_audio_boost_bot.py
# Телеграм-бот, который принимает ссылки на YouTube-видео, скачивает их,
# отслеживает прогресс, усиливает аудиодорожку в 20 dB и возвращает готовый файл.

import os
import re
import logging
import subprocess
import tempfile
import threading
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, run_async
import yt_dlp

# Читаем токен из переменной окружения
TOKEN = os.getenv("BOT_TOKEN")

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Параметры yt-dlp
YTDL_OPTS = {
    'format': 'bestvideo+bestaudio',
    'merge_output_format': 'mp4',
    'quiet': True,
}

# Regex для поиска URL
URL_REGEX = re.compile(r'https?://\S+')

# Множество занятых чатов (для предотвращения параллельной обработки одного пользователя)
busy_chats = set()
busy_lock = threading.Lock()


def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Привет! Пришли ссылку на YouTube-видео, и я верну файл с усиленным звуком (×2, ≈20 dB)."
    )


def extract_youtube_url(text: str):
    for url in URL_REGEX.findall(text):
        if 'youtube.com' in url or 'youtu.be' in url:
            return url
    return None


@run_async
def process_link(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    # Проверяем, не занял ли чат обработку
    with busy_lock:
        if chat_id in busy_chats:
            update.message.reply_text(
                "❌ Я уже обрабатываю ваше предыдущее видео. Пожалуйста, дождитесь результата."
            )
            return
        busy_chats.add(chat_id)

    try:
        url = extract_youtube_url(update.message.text)
        if not url:
            update.message.reply_text("❌ Отправьте корректную ссылку на YouTube-видео.")
            return

        # Инициализация прогресса
        status_msg = update.message.reply_text("🔄 Подготовка к загрузке...")

        # Хук для отслеживания прогресса загрузки
        def progress_hook(d):
            try:
                if d['status'] == 'downloading':
                    pct = d.get('_percent_str', '').strip()
                    status_msg.edit_text(f"📥 Загрузка: {pct}")
                elif d['status'] == 'finished':
                    status_msg.edit_text("✅ Загрузка завершена. Усиливаю аудио...")
            except Exception:
                pass  # Игнорируем ошибки обновления статуса

        with tempfile.TemporaryDirectory() as tmpdir:
            # Шаг 1: скачать видео с прогрессом
            ydl_opts = YTDL_OPTS.copy()
            ydl_opts['outtmpl'] = os.path.join(tmpdir, '%(id)s.%(ext)s')
            ydl_opts['progress_hooks'] = [progress_hook]
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                input_file = ydl.prepare_filename(info)

            # Шаг 2: усиление аудио
            output_file = os.path.join(tmpdir, f"boosted_{info['id']}.mp4")
            status_msg.edit_text("🔊 Усиление аудио: ~20 dB...")
            cmd = [
                'ffmpeg', '-y', '-i', input_file,
                '-filter:a', 'volume=20dB',
                '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                output_file
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Шаг 3: отправка результата
            status_msg.edit_text("📤 Отправляю готовый файл...")
            with open(output_file, 'rb') as f:
                context.bot.send_document(chat_id=chat_id, document=f)

        # Очистка и удаление статуса
        status_msg.delete()

    except Exception:
        logger.exception("Ошибка при обработке видео:")
        update.message.reply_text("❌ Что-то пошло не так. Попробуйте позже.")

    finally:
        # Освобождаем чат
        with busy_lock:
            busy_chats.discard(chat_id)


def main():
    if not TOKEN:
        logger.error("Не найден BOT_TOKEN. Установите переменную окружения BOT_TOKEN.")
        return

    updater = Updater(TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, process_link))

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
