FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      alsa-utils \
      build-essential \
      curl \
      libasound2 \
      libportaudio2 \
      netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY voice_gateway.py /app/voice_gateway.py

CMD ["python", "/app/voice_gateway.py", "--config", "/app/config.yaml"]
