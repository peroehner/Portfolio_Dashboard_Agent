#!/usr/bin/env bash
# Per-boot startup: bring up the local Postgres cluster and ensure the app
# databases exist. Safe to run repeatedly.
set -euo pipefail

# Start (or restart) the packaged Postgres 16 cluster.
sudo pg_ctlcluster 16 main start 2>/dev/null \
  || sudo pg_ctlcluster 16 main restart 2>/dev/null \
  || true

# Wait for the server to accept connections.
for _ in $(seq 1 30); do
  if sudo -u postgres pg_isready -q; then break; fi
  sleep 1
done

# Ensure the superuser password matches DATABASE_URL and both databases exist.
sudo -u postgres psql -tc "ALTER USER postgres PASSWORD 'postgres';" >/dev/null
for db in portfolio portfolio_test; do
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${db}'" | grep -q 1; then
    sudo -u postgres createdb "${db}"
  fi
done

echo "Postgres ready; databases ensured (portfolio, portfolio_test)."
