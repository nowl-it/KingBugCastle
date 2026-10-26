#!/bin/bash
cd "$(dirname "$0")"
# Private/local server: the browser cannot round-trip real Google on 127.0.0.1
# (the authorised redirect URI is the public domain), so default the Google button
# to the on-device dev picker. Export GLOGIN_DEV=0 to opt out. run.py sets the same
# default for loopback dev runs.
export GLOGIN_DEV="${GLOGIN_DEV:-1}"
python3 -m uvicorn server:app --host 0.0.0.0 --port 8080 &
PID1=$!
python3 -m uvicorn server:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem &
PID2=$!
trap "kill $PID1 $PID2 2>/dev/null" SIGINT SIGTERM EXIT
wait
