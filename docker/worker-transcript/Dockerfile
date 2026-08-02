FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY docker/worker-transcript/requirements.txt /tmp/requirements.txt
COPY apps/worker-transcript /app/apps/worker-transcript
COPY config /app/config

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt

CMD ["python", "/app/apps/worker-transcript/main.py"]
