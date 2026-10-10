FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# All dependencies ship manylinux wheels, so no compiler is needed.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 bot && chown -R bot:bot /app
USER bot

# Applies migrations, seeds demo data (SEED_DEMO), then starts long polling.
CMD ["python", "-m", "app.main"]
