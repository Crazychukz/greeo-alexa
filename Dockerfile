FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements/ /app/backend/requirements/
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/backend/requirements/dev.txt

COPY . /app

WORKDIR /app/backend

