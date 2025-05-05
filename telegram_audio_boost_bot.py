#!/usr/bin/env python3
# telegram_audio_boost_bot.py
# Телеграм-бот, который принимает ссылку на YouTube-видео,
# предлагает 4 опции обработки:
# "Аудио +10 dB", "Аудио +20 dB", "Аудио + Видео +10 dB", "Аудио + Видео +20 dB",
# скачивает медиа в нужном формате, усиливает аудио и возвращает пользователю.

import os
import re
import logging
import subprocess
import tempfile
import threading
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    ConversationHandler, CallbackContext
)
import yt_dlp
from yt_dlp.utils import ExtractorError, DownloadError

# Токен бота
TOKEN = os.getenv("BOT_TOKEN")

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Regex для URL
URL_REGEX = re.compile(r'https?://\S+')

# Состояние разговора
CHOOSING_OPTION = 1

# Контроль одного запроса в чате
busy_chats = set()
busy_lock = threading.Lock()


def extract_youtube_url(text: str) -> str:
    """Извлечение первой подходящей YouTube-ссылки из текста"""
    for url in URL_REGEX.findall(text):
        if 'youtube.com' in url or 'youtu.be' in url:
            return url
    return None


def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Привет! Отправьте ссылку на YouTube-видео, чтобы выбрать, как я буду усиливать звук."
    )


def ask_option(update: Update, context: CallbackContext) -> int:
    chat_id = update.effective_chat.id
    url = extract_youtube_url(update.message.text)
    if not url:
        update.message.reply_text("❌ Пожалуйста, отправьте корректную ссылку на YouTube.")
        return ConversationHandler.END

    with busy_lock:
        if chat_id in busy_chats:
            update.message.reply_text("❌ Я уже обрабатываю ваш запрос. Подождите, пожалуйста.")
            return ConversationHandler.END
        busy_chats.add(chat_id)

    context.user_data['url'] = url
    buttons = [
        ['Аудио +10 dB', 'Аудио +20 dB'],
        ['Аудио + Видео +10 dB', 'Аудио + Видео +20 dB']
    ]
    markup = ReplyKeyboardMarkup(buttons, one_time_keyboard=True, resize_keyboard=True)
    update.message.reply_text("Выберите опцию обработки:", reply_markup=markup)
    return CHOOSING_OPTION


def process_choice(update: Update, context: CallbackContext) -> int:
    chat_id = update.effective_chat.id
    choice = update.message.text.strip()
    url = context.user_data.get('url')
    update.message.reply_text("🔄 Начинаю обработку...", reply_markup=ReplyKeyboardRemove())

    # Определяем параметры
    is_video = 'Видео' in choice
    match = re.search(r'\+(\d+)', choice)
    db_value = int(match.group(1)) if match else 20

    # Настройки yt-dlp
    ydl_opts = {'quiet': True}
    if is_video:
        ydl_opts.update({
            'format': 'bestvideo[height<=240]+bestaudio/best[height<=240]',
            'merge_output_format': 'mp4',
            'outtmpl': os.path.join(tmpdir := tempfile.mkdtemp(), '%(id)s.%(ext)s')
        })
        ext = 'mp4'
    else:
        ydl_opts.update({
            'format': 'bestaudio',
            'outtmpl': os.path.join(tmpdir := tempfile.mkdtemp(), '%(id)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        })
        ext = 'mp3'

    try:
        # Скачиваем
        ydl = yt_dlp.YoutubeDL(ydl_opts)
        try:
            info = ydl.extract_info(url, download=True)
        except (ExtractorError, DownloadError) as e:
            logger.error("YT-DLP download error: %s", e)
            # Фоллбек через Invidious
            video_id = re.search(r'(?:v=|youtu\.be/)([^?&]+)', url)
            if video_id:
                vid = video_id.group(1)
                fallback_url = f"https://yewtu.be/watch?v={vid}"
                update.message.reply_text("⚠️ Пробую через Invidious mirror...")
                ydl_fb = yt_dlp.YoutubeDL(ydl_opts)
                try:
                    info = ydl_fb.extract_info(fallback_url, download=True)
                except Exception as e2:
                    logger.error("Invidious fallback failed: %s", e2)
                    update.message.reply_text("❌ Не удалось скачать даже через Invidious.")
                    return ConversationHandler.END
            else:
                update.message.reply_text(
                    "❌ Видео недоступно или требует авторизации/подтверждения возраста."
                )
                return ConversationHandler.END

        input_file = ydl.prepare_filename(info)
        if not is_video:
            input_file = os.path.splitext(input_file)[0] + '.mp3'

        # Усиливаем и конвертируем
        output_file = os.path.join(tmpdir, f"boosted_{info['id']}.{ext}")
        if is_video:
            cmd = [
                'ffmpeg', '-y', '-i', input_file,
                '-vf', 'scale=-2:240',
                '-filter:a', f'volume={db_value}dB',
                '-c:v', 'libx264', '-preset', 'veryfast',
                '-c:a', 'aac', '-b:a', '192k',
                output_file
            ]
        else:
            cmd = [
                'ffmpeg', '-y', '-i', input_file,
                '-filter:a', f'volume={db_value}dB',
                output_file
            ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Отправляем
        with open(output_file, 'rb') as f:
            if is_video:
                context.bot.send_video(chat_id=chat_id, video=f, supports_streaming=True)
            else:
                context.bot.send_audio(chat_id=chat_id, audio=f)

    except Exception:
        logger.exception("Ошибка при обработке:")
        context.bot.send_message(chat_id, "❌ Ошибка обработки. Попробуйте позже.")
    finally:
        # Очистка
        busy_chats.discard(chat_id)
        context.user_data.clear()
        if 'tmpdir' in locals():
            subprocess.run(['rm', '-rf', tmpdir])

    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext) -> int:
    chat_id = update.effective_chat.id
    busy_chats.discard(chat_id)
    context.user_data.clear()
    update.message.reply_text('Отменено.', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def main():
    if not TOKEN:
        logger.error("Не найден BOT_TOKEN. Установите переменную окружения BOT_TOKEN.")
        return
    updater = Updater(TOKEN)
    updater.bot.delete_webhook(drop_pending_updates=True)
    dp = updater.dispatcher
    conv = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex(r'https?://'), ask_option)],
        states={CHOOSING_OPTION: [MessageHandler(
            Filters.regex(r'^(Аудио \+10 dB|Аудио \+20 dB|Аудио \+ Видео \+10 dB|Аудио \+ Видео \+20 dB)$'),
            process_choice
        )]},
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(conv)
    updater.start_polling(drop_pending_updates=True)
    updater.idle()


if __name__ == '__main__':
    main()
