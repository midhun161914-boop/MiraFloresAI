"""Paths and settings. Everything is overridable by environment variable so the
same code runs locally, in Docker, and on a container host."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

PACKET_FILE_NAME = "okafor_lindqvist_2025_packet.json"

# Canonical, read-only source: the packet at the project root, exactly as delivered.
PACKET_SOURCE = Path(os.environ.get("PACKET_PATH", PROJECT_ROOT / PACKET_FILE_NAME))

# Load path: the packet is copied here at startup and parsed from here.
DATA_DIR = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data"))

# Append-only workpaper event store (SQLite). Survives restarts; delete only to start over.
EVENTS_DB = Path(os.environ.get("EVENTS_DB", DATA_DIR / "workpaper.sqlite"))

# Built frontend (vite build output). Served by FastAPI when present.
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", PROJECT_ROOT / "frontend" / "dist"))

# The return the workpaper treats as current (readme.where_now_is says v3).
CURRENT_VERSION = os.environ.get("CURRENT_VERSION", "v3")

EXPECTED_COUNTS = {"documents": 74, "extracted_values": 3012, "return_versions": 3}
