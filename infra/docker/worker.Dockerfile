FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY services/worker/pyproject.toml ./pyproject.toml
COPY services/worker/app ./app
RUN pip install --upgrade pip && pip install .

CMD ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=INFO"]
