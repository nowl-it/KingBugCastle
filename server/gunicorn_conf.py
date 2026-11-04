"""Gunicorn configuration for production zero-downtime serving.

Used by serve_public.sh.
Supports zero-downtime rolling reload via `kill -HUP <pid>`.
"""
import os
import multiprocessing

# Network Binding
http_port = os.environ.get("HTTP_PORT", "8080")
bind_host = os.environ.get("KGC_BIND_HOST", "0.0.0.0")
bind = f"{bind_host}:{http_port}"

# Worker configuration
# Each worker imports server:app independently (preload_app=False, needed for
# SIGHUP zero-downtime code reload), so RSS per worker is roughly the full app
# footprint (~150-180MB on this box). Cap workers to what the box can host with
# room for the recycle window: 2 cores -> 3 workers ~= 500MB, leaves headroom
# for Caddy + dashboard + swap. Override via KGC_WORKERS if the box grows.
default_workers = max(2, min(4, multiprocessing.cpu_count() + 1))
workers = int(os.environ.get("KGC_WORKERS", default_workers))
worker_class = "uvicorn.workers.UvicornWorker"

# Worker recycling. The TLS uvicorn that used to front Caddy grew past 500MB in
# 160s under a backlog spike and got OOM-killed; gunicorn's UvicornWorker has
# the same growth path. Recycle each worker after ~800 requests (+/- 80 jitter
# so a traffic burst does not kill five workers at once). New workers fork from
# the master and re-import the app, so any leak resets every few minutes without
# touching the master or the listening socket.
max_requests = int(os.environ.get("KGC_MAX_REQUESTS", 800))
max_requests_jitter = int(os.environ.get("KGC_MAX_REQUESTS_JITTER", 80))

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
