FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY docker/worker-download/requirements.txt /tmp/requirements.txt
COPY apps/worker-download /app/apps/worker-download
COPY config /app/config

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt

CMD ["python", "/app/apps/worker-download/main.py"]
