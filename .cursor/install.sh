#!/usr/bin/env bash
# Idempotent repository bootstrap for the Portfolio Dashboard Agent.
# Installs system + Python dependencies and seeds a local .env.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# System packages (Postgres server + venv support). Guarded so re-runs are cheap.
if ! command -v pg_ctlcluster >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    postgresql postgresql-contrib
fi
if ! python3 -m venv --help >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip
fi

# Python environment. requirements-deploy.txt is the lightweight (no torch) set
# recommended for local development in the README.
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-deploy.txt

# Local development configuration (matches docker-compose.yml defaults).
if [ ! -f .env ]; then
  cat > .env <<'ENV'
PORT=5000
FLASK_DEBUG=0
FREE_PORT=1
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/portfolio
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/portfolio_test
SKIP_TRANSFORMERS=1
ASSESSMENT_MODE=auto
FIB_PROXIMITY_PCT=1.0
ENV
fi

echo "install.sh complete."
