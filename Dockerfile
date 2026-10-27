# Smart Restaurant Review Intelligence Platform — runnable (pure-Python) build.
# No native wheels, no Node: everything imports under strict security policies.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

# Install runtime deps first for layer caching.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY backend/ ./

# SQLite lives on a mountable volume; ensure the dir exists.
ENV DATABASE_PATH=/data/app.db \
    APP_ENV=dev \
    AI_PROVIDER=demo
RUN mkdir -p /data

EXPOSE 8008

# Apply migrations (idempotent) then serve. Seed with demo data only in non-prod.
CMD ["sh", "-c", "python manage.py migrate && uvicorn app.main:app --host 0.0.0.0 --port 8008"]
