"""Gunicorn configuration for production zero-downtime serving.

Used by serve_public.sh.
Supports zero-downtime rolling reload via `kill -HUP <pid>`.
"""
import os
import multiprocessing

# Network Binding
http_port = os.environ.get("HTTP_PORT", "8080")
bind = f"0.0.0.0:{http_port}"

# Worker configuration
# Default: 4 workers or 2*cores + 1 (capped reasonably for VPS)
default_workers = max(2, min(8, (multiprocessing.cpu_count() * 2) + 1))
workers = int(os.environ.get("KGC_WORKERS", default_workers))
worker_class = "uvicorn.workers.UvicornWorker"

# Connections & Timeouts
# Cloudflare keepalive timeout is 60s; 65s prevents race conditions
keepalive = 65
timeout = 120

# Graceful worker restart timeout (seconds)
# Gives in-flight requests time to finish when reloading with SIGHUP
graceful_timeout = 30

# Process tracking
pidfile = "/tmp/kgc_server.pid"

# MUST be False so worker reloads (SIGHUP) re-import fresh code and data from disk
preload_app = False

# Logging
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")
accesslog = None  # App handles its own logging / rate tracking
errorlog = "/tmp/kgc_gunicorn.log"

def on_starting(server):
    print(f"[gunicorn] master process starting on {bind} with {workers} uvicorn workers (pid: {os.getpid()})")

def on_reload(server):
    print(f"[gunicorn] SIGHUP received: performing zero-downtime worker reload")

def worker_exit(server, worker):
    pass
