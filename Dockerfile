FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run sets PORT; 8080 is its default.
ENV PORT=8080
EXPOSE 8080

# Threads, not just processes: most requests are short DB reads, and the
# chat/search polls are IO-bound. Keep workers low — every worker holds its
# own connection pool, and Cloud SQL's connection budget is
# (instances x workers x pool size).
CMD exec gunicorn \
    --bind 0.0.0.0:$PORT \
    --workers ${WEB_CONCURRENCY:-2} \
    --threads ${WEB_THREADS:-8} \
    --timeout 120 \
    --access-logfile - \
    app:app
