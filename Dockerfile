FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY whozit/ whozit/
COPY static/ static/

ENV WHOZIT_CACHE_DIR=/models
ENV WHOZIT_PEOPLE_PATH=/data/people.json
ENV WHOZIT_ATTENDANCE_PATH=/data/attendance.json
ENV PYTHONUNBUFFERED=1

RUN mkdir -p /data /models

EXPOSE 8088

# Models download on first warmup at startup; mount volume to persist:
#   -v whozit-models:/models -v whozit-data:/data
VOLUME ["/data", "/models"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
