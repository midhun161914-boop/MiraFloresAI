"""FastAPI entry point.

    uvicorn app.main:app --reload        (from backend/)

At startup the packet is staged, validated and indexed once; if it fails any
integrity check the process exits instead of serving partial data. When a built
frontend exists (frontend/dist) it is served from the same origin, so the
production deploy is a single process.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.api.change_routes import router as change_router
from app.api.status_routes import router as status_router
from app.api.lifecycle_routes import client_router as lifecycle_client_router, router as lifecycle_router
from app.api.health_routes import router as health_router
from app.api.review_routes import client_router, router as review_router
from app.api.routes import public, router
from app.services.actors import ACTOR_HEADER, all_actors
from app.services.loader import PacketIndex, load_packet
from app.services.redact import Redactor
from app.services.refs import RefResolver
from app.services.trace import TraceIndex
from app.services.events import EventStore
from app.services.review import ReviewService
from app.services.health import HealthService
from app.services.changes import ChangeService
from app.services.versions import VersionService
from app.services.lifecycle import LifecycleService
from app.services.budget import TimeService
from app.services.status import StatusService

log = logging.getLogger("workpaper")


def create_app(index: Optional[PacketIndex] = None, frontend_dist: Optional[Path] = None,
               events_db: Optional[Path | str] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        idx = index or load_packet()
        app.state.index = idx
        app.state.resolver = RefResolver(idx)
        app.state.redactor = Redactor(idx)
        app.state.actors = {a.id: a for a in all_actors(idx)}
        app.state.trace = TraceIndex(idx, app.state.resolver)
        # Workpaper state: append-only events, persisted next to the staged packet.
        app.state.events = EventStore(events_db or config.EVENTS_DB)
        app.state.review = ReviewService(idx, app.state.trace, app.state.events, app.state.actors)
        app.state.health = HealthService(idx, app.state.trace, app.state.review)
        app.state.changes = ChangeService(app.state.review, app.state.health)
        app.state.versions = VersionService(app.state.review)
        app.state.lifecycle = LifecycleService(app.state.review, app.state.health, app.state.changes, app.state.redactor)
        app.state.time = TimeService(app.state.review)
        app.state.status = StatusService(app.state.review, app.state.health, app.state.lifecycle, app.state.time)
        log.warning(
            "Packet loaded: %d documents, %d extracted values, %d return versions (sha256 %s…)",
            len(idx.packet.documents), len(idx.packet.extracted_values),
            len(idx.packet.return_versions), idx.sha256[:12],
        )
        yield

    app = FastAPI(title="Miraflores Workpaper API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"], allow_headers=["*", ACTOR_HEADER],
    )
    app.include_router(public)
    app.include_router(router)
    app.include_router(review_router)
    app.include_router(health_router)
    app.include_router(change_router)
    app.include_router(client_router)
    app.include_router(lifecycle_router)
    app.include_router(lifecycle_client_router)
    app.include_router(status_router)

    dist = frontend_dist or config.FRONTEND_DIST
    if (dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = dist / path
            if path and candidate.is_file() and dist in candidate.resolve().parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
