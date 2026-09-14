#!/usr/bin/env bash
set -e

echo "Starting bdhost infrastructure containers (PostgreSQL, Redis)..."
docker compose up -d postgres redis

echo "Waiting for services to become healthy..."
sleep 2

echo "Running database migrations..."
uv run alembic upgrade head

echo "Seeding database with default plans and admin account..."
uv run python scripts/seed.py

echo "Setup complete! You can run services directly using the fastapi command:"
echo "  uv run fastapi dev api/main.py --port 8000"
echo "  uv run fastapi dev app_runtime/main.py --port 8001"
echo "  uv run arq worker.main.WorkerSettings --watch worker"
