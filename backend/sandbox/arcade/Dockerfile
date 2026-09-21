# Окружение "Python 3.12 + Arcade" (ADM-001/002/003) — статус "beta", см.
# Environment.status_note в app/services/environments.py: автопроверка тут —
# дымовой тест (программа запустилась и не упала под виртуальным дисплеем),
# не сравнение визуального результата игры с эталоном.
#
# Собрать: docker build -t codelab-runner:arcade backend/sandbox/arcade
FROM python:3.12-slim

WORKDIR /sandbox

# Arcade рисует через OpenGL — нужен виртуальный X-дисплей (xvfb-run) и
# минимальный набор системных библиотек для его инициализации, иначе
# `import arcade` или создание окна падает уже на старте, до кода ученика.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       xvfb libgl1 libglx-mesa0 libx11-6 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir arcade==2.6.17
