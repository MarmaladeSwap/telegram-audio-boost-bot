#!/usr/bin/env python3
# telegram_audio_boost_bot.py
# Телеграм-бот, который принимает ссылку на видео (например, YouTube), скачивает его,
# усиливает аудиодорожку в 20 dB и возвращает пользователю результат.

import os
import logging
import subprocess
import tempfile
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import yt_dlp

# Получите токен вашего бота у @BotFather и сохраните его в переменной окружения BOT_TOKEN
TOKEN = os.getenv("BOT_TOKEN")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Привет! Отправь мне ссылку на видео, и я верну тебе файл с усиленной громкостью x2 (≈20dB)."  
    )


def process_link(update: Update, context: CallbackContext):
    url = update.message.text.strip()
    chat_id = update.effective_chat.id
    status_msg = update.message.reply_text("🔄 Обрабатываю видео, подожди пожалуйста...")

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input.mp4")
        output_path = os.path.join(tmpdir, "output.mp4")

        # Шаг 1: Скачать видео через yt-dlp
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': input_path,
            'quiet': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            logger.error(f"Ошибка при загрузке видео: {e}")
            status_msg.edit_text("❌ Не удалось скачать видео.")
            return

        # Шаг 2: Усилить аудио с помощью FFmpeg на 20 dB (приблизительно x10)
        ffmpeg_cmd = [
            'ffmpeg', '-y', '-i', input_path,
            '-filter:a', 'volume=20dB',
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k',
            output_path
        ]
        try:
            subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка FFmpeg: {e.stderr.decode()}")
            status_msg.edit_text("❌ Не удалось обработать видео.")
            return

        # Шаг 3: Отправить пользователю обработанный файл
        with open(output_path, 'rb') as f:
            context.bot.send_document(chat_id=chat_id, document=f)

        status_msg.delete()


def main():
    if not TOKEN:
        logger.error("Не установлен BOT_TOKEN. Установите переменную окружения перед запуском.")
        return

    updater = Updater(TOKEN)
    dp = updater.dispatcher

    # Обработчики
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.entity("url") & Filters.text, process_link))

    # Запускаем бота
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
