"""Dedicated ASGI entry point for the public Player Dashboard (:8082 by default)."""
from fastapi import FastAPI

import google_login
import playerdb
import playerportal
import security


# This process can be started without the game API.  It still owns browser
# sessions and ticket data, so bring the shared database to its current schema
# before accepting any portal request.
playerdb.init()

app = FastAPI(title="KGC Player Dashboard")
google_login.register_portal(app)
playerportal.register(app)
security.register_portal(app)
