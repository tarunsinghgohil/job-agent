#!/bin/sh
# Applies database migrations, then hands off to the real command.
#
# Migrations run here rather than in the image build because they need a live
# database. Alembic is idempotent, so a restart or a second replica re-running
# this is harmless.
set -e

echo "Waiting for the database..."
python - <<'PY'
import os
import sys
import time

from sqlalchemy import create_engine, text

from app.core.config import settings

url = settings.resolved_database_url()
deadline = time.monotonic() + 60
last_error = None

while time.monotonic() < deadline:
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("Database is up.")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - retried until the deadline
        last_error = exc
        time.sleep(2)

print(f"Database did not become reachable in time: {last_error}", file=sys.stderr)
sys.exit(1)
PY

echo "Applying migrations..."
alembic upgrade head

# Seeds the owner account when BOOTSTRAP_EMAIL/PASSWORD are provided. The CLI
# is idempotent, so this is a no-op once the account exists.
if [ -n "${BOOTSTRAP_EMAIL}" ] && [ -n "${BOOTSTRAP_PASSWORD}" ]; then
    echo "Ensuring the owner account exists..."
    python -m app.cli seed --email "${BOOTSTRAP_EMAIL}" --password "${BOOTSTRAP_PASSWORD}"
fi

echo "Starting: $*"
exec "$@"
