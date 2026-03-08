#!/bin/bash
set -e

# Force reinstall to avoid cached wrong versions
pip install --no-cache-dir -r requirements.txt

# Start API server in background
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} &
API_PID=$!

# Wait for API to be ready
sleep 3

# Start bot
python bot.py &
BOT_PID=$!

wait $API_PID $BOT_PID
