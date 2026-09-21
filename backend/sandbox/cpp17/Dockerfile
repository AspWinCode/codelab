# Окружение "C++17 (g++)" (ADM-001/002/003).
# Собрать: docker build -t codelab-runner:cpp17 backend/sandbox/cpp17
#
# Единственное окружение, которому нужен исполняемый /tmp (Environment.tmp_exec
# в app/services/environments.py снимает noexec с tmpfs только для него) —
# компилятор пишет бинарник решения в /tmp и тут же его исполняет, класть
# скомпилированный файл больше некуда: корневая ФС read-only.
FROM debian:bookworm-slim

WORKDIR /sandbox

RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*
