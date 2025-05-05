#!/usr/bin/env python3
# telegram_audio_boost_bot.py
# Телеграм-бот, который принимает ссылки на YouTube-видео,
# спрашивает формат (аудио или аудио+видео),
# скачивает медиа, усиливает аудио в 20 dB и возвращает готовый файл.

import os
import re
import logging
import subprocess
import tempfile
import threading
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    ConversationHandler, CallbackContext, run_async
)
import yt_dlp

# Читаем токен из переменной окружения
TOKEN = os.getenv("BOT_TOKEN")

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Regex для поиска URL
URL_REGEX = re.compile(r'https?://\S+')

# Состояние разговора
CHOOSING_FORMAT = 1

# Для контроля одного запроса в чате
busy_chats = set()
busy_lock = threading.Lock()


def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Привет! Пришли ссылку на YouTube-видео, и я спрошу формат обработки."
    )


def extract_youtube_url(text: str):
    for url in URL_REGEX.findall(text):
        if 'youtube.com' in url or 'youtu.be' in url:
            return url
    return None


def ask_format(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    url = extract_youtube_url(update.message.text)
    if not url:
        update.message.reply_text("❌ Пожалуйста, отправьте корректную ссылку на YouTube.")
        return ConversationHandler.END

    with busy_lock:
        if chat_id in busy_chats:
            update.message.reply_text(
                "❌ Я уже обрабатываю ваш предыдущий запрос. Пожалуйста, дождитесь результата."
            )
            return ConversationHandler.END
        busy_chats.add(chat_id)

    context.user_data['url'] = url
    # Клавиатура для выбора формата
    buttons = [['Аудио только'], ['Аудио + Видео']]
    markup = ReplyKeyboardMarkup(buttons, one_time_keyboard=True, resize_keyboard=True)
    update.message.reply_text(
        "Выберите, что вы хотите получить:", reply_markup=markup
    )
    return CHOOSING_FORMAT


@run_async
def process_choice(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    choice = update.message.text
    url = context.user_data.get('url')
    # Убираем клавиатуру
    update.message.reply_text("🔄 Обрабатываю...", reply_markup=ReplyKeyboardRemove())

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Настройка формата yt-dlp
            ydl_opts = {'quiet': True}
            if choice == 'Аудио только':
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
            else:
                ydl_opts.update({
                    'format': 'bestvideo[height<=240]+bestaudio/best[height<=240]',
                    'merge_output_format': 'mp4',
                    'outtmpl': os.path.join(tmpdir, '%(id)s.%(ext)s'),
                })
                ext = 'mp4'

            # Скачиваем
            ydl = yt_dlp.YoutubeDL(ydl_opts)
            info = ydl.extract_info(url, download=True)
            input_file = ydl.prepare_filename(info)
            if choice == 'Аудио только':
                input_file = os.path.splitext(input_file)[0] + '.mp3'

            # Если видео+аудио, усиливаем аудио внутри MP4
            if choice == 'Аудио + Видео':
                output_file = os.path.join(tmpdir, f"boosted_{info['id']}.mp4")
                cmd = [
                    'ffmpeg', '-y', '-i', input_file,
                    '-filter:a', 'volume=20dB',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                    output_file
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                # Для MP3 достаточно увеличить громкость в новой дорожке
                output_file = os.path.join(tmpdir, f"boosted_{info['id']}.mp3")
                cmd = [
                    'ffmpeg', '-y', '-i', input_file,
                    '-filter:a', 'volume=20dB',
                    output_file
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Отправляем файл
            with open(output_file, 'rb') as f:
                context.bot.send_document(chat_id=chat_id, document=f)

    except Exception as e:
        logger.exception("Ошибка при обработке:")
        context.bot.send_message(chat_id, "❌ Ошибка обработки. Попробуйте позже.")

    finally:
        with busy_lock:
            busy_chats.discard(chat_id)
        context.user_data.clear()

    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    with busy_lock:
        busy_chats.discard(chat_id)
    context.user_data.clear()
    update.message.reply_text(
        'Отменено.', reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


def main():
    if not TOKEN:
        logger.error("Не найден BOT_TOKEN. Установите переменную окружения BOT_TOKEN.")
        return

    updater = Updater(TOKEN)
    dp = updater.dispatcher

    conv = ConversationHandler(
        entry_points=[MessageHandler(Filters.text & ~Filters.command, ask_format)],
        states={CHOOSING_FORMAT: [MessageHandler(Filters.regex('^(Аудио только|Аудио \+ Видео)$'), process_choice)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(conv)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
