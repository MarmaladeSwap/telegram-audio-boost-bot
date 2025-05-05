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
from yt_dlp.utils import ExtractorError

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

# Ищем YouTube-ссылку в тексте
def extract_youtube_url(text: str):
    for url in URL_REGEX.findall(text):
        if 'youtube.com' in url or 'youtu.be' in url:
            return url
    return None

# Команда /start
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Привет! Отправьте ссылку на YouTube-видео, чтобы выбрать, как я буду усиливать звук."
    )

# Спрашиваем опцию обработки
def ask_option(update: Update, context: CallbackContext):
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

# Обработка выбора опции
def process_choice(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    choice = update.message.text.strip()
    url = context.user_data.get('url')
    update.message.reply_text("🔄 Начинаю обработку...", reply_markup=ReplyKeyboardRemove())

    is_video = 'Видео' in choice
    match = re.search(r'\+(\d+)', choice)
    db_value = int(match.group(1)) if match else 20

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Настройка yt-dlp
            ydl_opts = {'quiet': True}
            if is_video:
                ydl_opts.update({
                    'format': 'bestvideo[height<=240]+bestaudio/best[height<=240]',
                    'merge_output_format': 'mp4',
                    'outtmpl': os.path.join(tmpdir, '%(id)s.%(ext)s'),
                })
                ext = 'mp4'
            else:
                ydl_opts.update({
                    'format': 'bestaudio',
                    'outtmpl': os.path.join(tmpdir, '%(id)s.%(ext)s'),
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }]
                })
                ext = 'mp3'

            ydl = yt_dlp.YoutubeDL(ydl_opts)
            try:
                info = ydl.extract_info(url, download=True)
            except ExtractorError as e:
                logger.error("YT-DLP extract error: %s", e)
                # Особая обработка для ошибок авторизации на YouTube
                if 'Sign in to confirm' in str(e):
                    update.message.reply_text(
                        "❌ Ролик требует авторизации или возрастного подтверждения. "
                        "К сожалению, я не могу его скачать."
                    )
                else:
                    update.message.reply_text(
                        "❌ Не удалось скачать видео. Возможно, оно недоступно или удалено."
                    )
                return ConversationHandler.END

            input_file = ydl.prepare_filename(info)
            if not is_video:
                input_file = os.path.splitext(input_file)[0] + '.mp3'

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

            with open(output_file, 'rb') as f:
                if is_video:
                    context.bot.send_video(chat_id=chat_id, video=f, supports_streaming=True)
                else:
                    context.bot.send_audio(chat_id=chat_id, audio=f)

    except Exception:
        logger.exception("Ошибка при обработке:")
        context.bot.send_message(chat_id, "❌ Ошибка обработки. Попробуйте позже.")
    finally:
        with busy_lock:
            busy_chats.discard(chat_id)
        context.user_data.clear()

    return ConversationHandler.END

# Отмена
def cancel(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    with busy_lock:
        busy_chats.discard(chat_id)
    context.user_data.clear()
    update.message.reply_text('Отменено.', reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# Основная функция
def main():
    if not TOKEN:
        logger.error("Не найден BOT_TOKEN. Установите переменную окружения BOT_TOKEN.")
        return
    updater = Updater(TOKEN)
    updater.bot.delete_webhook(drop_pending_updates=True)
    dp = updater.dispatcher
    conv = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex(r'https?://'), ask_option)],
        states={
            CHOOSING_OPTION: [MessageHandler(
                Filters.regex(r'^(Аудио \+10 dB|Аудио \+20 dB|Аудио \+ Видео \+10 dB|Аудио \+ Видео \+20 dB)$'),
                process_choice
            )]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(conv)
    # Начинаем polling с дропом старых обновлений
    updater.start_polling(drop_pending_updates=True)
    updater.idle()

if __name__ == '__main__':
    main()
