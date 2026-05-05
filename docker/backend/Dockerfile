FROM python:3.12-bookworm

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR='/var/cache/pypoetry' \
    POETRY_HOME='/usr/local' \
    POETRY_VERSION=2.3.2

RUN curl -sSL https://install.python-poetry.org | python3 -
RUN apt-get update && apt-get install -y libgomp1 git

WORKDIR /backend

COPY backend/pyproject.toml backend/poetry.lock* ./
RUN poetry install --no-interaction --no-ansi --no-root

COPY backend/ ./
COPY .env .env
