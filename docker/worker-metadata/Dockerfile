FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY docker/worker-metadata/requirements.txt /tmp/requirements.txt
COPY apps/worker-metadata /app/apps/worker-metadata
COPY config /app/config

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt

CMD ["python", "/app/apps/worker-metadata/main.py"]
