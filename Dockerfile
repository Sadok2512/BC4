FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

COPY . /app

ARG VCS_REF
ARG APP_VERSION
RUN test -n "$VCS_REF" \
 && test -n "$APP_VERSION" \
 && printf '%s' "$VCS_REF" | grep -Eq '^[0-9a-f]{7,40}$' \
 && python -c "import tomllib; assert tomllib.load(open('pyproject.toml','rb'))['project']['version'] == '$APP_VERSION'"
LABEL org.opencontainers.image.revision=$VCS_REF \
      org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.title="BC4 Backend"

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python -m app.seed.run && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4"]
