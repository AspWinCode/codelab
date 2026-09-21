# Окружение "Python 3.12 + pandas/numpy" (ADM-001/002/003).
# Собрать: docker build -t codelab-runner:python3.12-data backend/sandbox/python3-data
#
# Отдельный образ от базового codelab-runner:python3.12 — задачи без
# pandas/numpy не должны платить временем сборки/размером образа за них,
# и наоборот: обновление версии pandas не трогает базовый образ.
FROM python:3.12-slim

WORKDIR /sandbox

# Версии фиксируются здесь (ADM-002): захотели другую версию pandas/numpy —
# новый тег образа, старое окружение не трогаем.
RUN pip install --no-cache-dir pandas==2.2.2 numpy==1.26.4

# Никаких дополнительных пакетов ОС и сетевого доступа в рантайме — контейнер
# запускается с --network none (см. app/services/runner_docker.py).
