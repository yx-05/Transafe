#!/bin/bash
# Deploy script for Cloud Studio — installs deps and starts the server
set -e

echo "=== Installing dependencies ==="
pip install --no-cache-dir -q -r requirements-deploy.txt 2>&1 | tail -5

echo "=== Starting TranSafe server ==="
exec python -m uvicorn main_prod:app --host 0.0.0.0 --port 8000
