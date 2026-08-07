# One image, four commands. web, admin, collector and worker share a codebase
# and differ only in their entrypoint and their database role -- separate images
# would be four builds to keep in sync for no isolation gain, because the
# isolation that matters is the Postgres grant, not the filesystem.
FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ common/
COPY db/ db/
COPY web/ web/
COPY admin/ admin/
COPY collector/ collector/
COPY worker/ worker/
COPY scripts/ scripts/
COPY templates/ templates/
COPY static/ static/
COPY data/ data/

# Non-root, and the app never needs to write to its own tree.
RUN useradd --system --uid 10001 fo && chown -R fo:fo /srv
USER fo

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/healthz" || exit 1

EXPOSE 8000
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "3", "web.app:app"]


# dbt runs on its own schedule and pulls a large dependency tree; keeping it out
# of the app image keeps the thing that serves customers small.
#
# The layout mirrors the app image (/srv/dbt, /srv/db, /srv/scripts) because
# scripts/run_dbt.py resolves the project relative to itself and writes every
# run into meta.dbt_runs -- which is where fo_mart_last_build_timestamp and the
# freshness alert get their numbers. Running bare `dbt build` here would build
# the marts and tell nobody it had.
FROM python:3.12-slim AS dbt
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
RUN pip install --no-cache-dir dbt-postgres==1.9.0 "psycopg[binary,pool]==3.2.3"
COPY dbt/ dbt/
COPY db/ db/
COPY scripts/run_dbt.py scripts/
RUN useradd --system --uid 10001 fo && chown -R fo:fo /srv
USER fo
CMD ["python", "-m", "scripts.run_dbt", "--schedule"]
