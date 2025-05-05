# Используем лёгкий образ с Python 3.11
FROM python:3.11-slim

# Рабочая директория внутри контейнера
WORKDIR /app

# Сначала копируем только requirements, чтобы кэшировать слои
COPY requirements.txt .

# Устанавливаем ffmpeg и компилятор (для yt-dlp)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg gcc && \
    pip install --no-cache-dir -r requirements.txt

# Копируем весь код
COPY . .

# Точка входа
CMD ["python", "telegram_audio_boost_bot.py"]
