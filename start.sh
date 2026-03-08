#!/bin/bash
# Run API server + Bot concurrently
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} &
API_PID=$!
sleep 2  # wait for API to be ready
python bot.py &
BOT_PID=$!
wait $API_PID $BOT_PID
