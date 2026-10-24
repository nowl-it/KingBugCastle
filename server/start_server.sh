#!/bin/bash
cd "$(dirname "$0")"
python3 -m uvicorn server:app --host 0.0.0.0 --port 8080 &
PID1=$!
python3 -m uvicorn server:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem &
PID2=$!
trap "kill $PID1 $PID2 2>/dev/null" SIGINT SIGTERM EXIT
wait
