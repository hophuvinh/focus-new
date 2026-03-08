#!/bin/bash
set -e

pip install --no-cache-dir -r requirements.txt

# Start API
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} &
API_PID=$!

# Wait until API is ready
echo "Waiting for API..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:${PORT:-8000}/health > /dev/null 2>&1; then
        echo "API ready ✅"
        break
    fi
    sleep 1
done

# Start bot
python bot.py &
BOT_PID=$!

wait $API_PID $BOT_PID
