### FILE: Dockerfile ###

FROM python:3.12-slim

# System deps
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gettext \
    curl \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

# App setup
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Requirements
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# App code
COPY . .

# Create necessary dirs
RUN mkdir -p /app/logs /app/media /app/staticfiles

# Collect static
RUN python manage.py collectstatic --noinput || true

# Entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn"]
