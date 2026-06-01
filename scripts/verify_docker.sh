#!/usr/bin/env bash
# scripts/verify_docker.sh
# Verify the Docker setup builds and starts without errors.
# Run from the project root: bash scripts/verify_docker.sh
set -euo pipefail

echo "[verify] Building Docker image..."
docker-compose build

echo "[verify] Starting services..."
docker-compose up -d

echo "[verify] Waiting for service to be ready..."
sleep 5

echo "[verify] Checking health endpoint..."
curl -sf http://localhost:8000/health && echo " OK"

echo "[verify] Docker setup verified successfully."
docker-compose down
