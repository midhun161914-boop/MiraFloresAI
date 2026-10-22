"""Append-only event store (SQLite via SQLAlchemy Core).

Every workpaper action is one immutable row: who, when, what kind, against which
node of the evidence graph (a line key, ``ev-NNNN``, ``D09``, ``return``), and a
JSON payload. Nothing is ever updated or deleted. SQLite triggers reject UPDATE
and DELETE at the database level, so append-only is a property of the store,
not a convention in the code.

Why events rather than mutable tables:
* the audit trail and change history *are* the data, not a side log;
* "what changed since I last looked" is ``seq > my_last_seq``;
* undo is a new event that reverts an earlier one (``reverts``);
* any past state of the review layer can be rebuilt by folding events up to a
  point, which is what version compare needs.

``seq`` is a monotonically increasing integer; clients use it for optimistic
concurrency (a write states the last seq it saw for an item; if someone else
wrote in between, the write is refused instead of silently overwritten).
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from pydantic import BaseModel
from sqlalchemy import (
    Column, Integer, MetaData, String, Table, Text, create_engine, event, select, text,
)
from sqlalchemy.engine import Engine

metadata = MetaData()
events_table = Table(
    "events", metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("id", String(32), nullable=False, unique=True),
    Column("at", String(32), nullable=False),
    Column("actor", String(32), nullable=False),
    Column("actor_role", String(32), nullable=False),
    Column("type", String(64), nullable=False, index=True),
    Column("node", String(128), nullable=True, index=True),
    Column("version", String(16), nullable=True),
    Column("payload", Text, nullable=False),
    Column("reverts", String(32), nullable=True),
)

_GUARDS = [
    "CREATE TRIGGER IF NOT EXISTS events_append_only_update BEFORE UPDATE ON events "
    "BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;",
    "CREATE TRIGGER IF NOT EXISTS events_append_only_delete BEFORE DELETE ON events "
    "BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;",
]


class Event(BaseModel):
    seq: int
    id: str
    at: str
    actor: str
    actor_role: str
    type: str
    node: Optional[str] = None
    version: Optional[str] = None
    payload: dict[str, Any]
    reverts: Optional[str] = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EventStore:
    def __init__(self, path: Path | str):
        url = "sqlite://" if str(path) == ":memory:" else f"sqlite:///{Path(path).as_posix()}"
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url, future=True, connect_args={"check_same_thread": False})

        @event.listens_for(self.engine, "connect")
        def _pragmas(conn: Any, _record: Any) -> None:  # durability + concurrent readers
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            for ddl in _GUARDS:
                conn.execute(text(ddl))
        self._lock = threading.Lock()
        self._listeners: list[Callable[[Event], None]] = []
        self._policies: list[Callable[[dict[str, Any]], None]] = []

    # -------------------------------------------------------------------- write
    def add_policy(self, fn: Callable[[dict[str, Any]], None]) -> None:
        """A rule checked inside the write lock before every append; raising refuses the write."""
        self._policies.append(fn)

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        self._listeners.append(fn)

    def append(self, *, actor: str, actor_role: str, type: str, node: Optional[str] = None,
               version: Optional[str] = None, payload: Optional[dict[str, Any]] = None,
               reverts: Optional[str] = None,
               guard: Optional[Callable[[], None]] = None) -> Event:
        """Append one event. ``guard`` runs inside the write lock, so a rule check
        and the write it protects cannot interleave with another writer."""
        with self._lock:
            draft = {"actor": actor, "actor_role": actor_role, "type": type, "node": node, "version": version,
                     "payload": payload or {}}
            for policy in self._policies:   # store-wide rules (e.g. the filed return is frozen)
                policy(draft)
            if guard is not None:
                guard()
            row = {
                "id": uuid.uuid4().hex, "at": now_iso(), "actor": actor, "actor_role": actor_role,
                "type": type, "node": node, "version": version,
                "payload": json.dumps(payload or {}, separators=(",", ":"), default=str),
                "reverts": reverts,
            }
            with self.engine.begin() as conn:
                seq = conn.execute(events_table.insert().values(**row)).inserted_primary_key[0]
            ev = Event(seq=seq, **{**row, "payload": payload or {}})
            for fn in self._listeners:
                fn(ev)
            return ev

    # --------------------------------------------------------------------- read
    def _rows(self, stmt: Any) -> list[Event]:
        with self.engine.connect() as conn:
            return [Event(**{**r._mapping, "payload": json.loads(r.payload)}) for r in conn.execute(stmt)]

    def all(self) -> list[Event]:
        return self._rows(select(events_table).order_by(events_table.c.seq))

    def query(self, *, since: int = 0, node: Optional[str] = None, actor: Optional[str] = None,
              types: Optional[Iterable[str]] = None, type_prefix: Optional[str] = None,
              limit: int = 500, newest_first: bool = True) -> list[Event]:
        c = events_table.c
        stmt = select(events_table).where(c.seq > since)
        if node:
            stmt = stmt.where(c.node == node)
        if actor:
            stmt = stmt.where(c.actor == actor)
        if types:
            stmt = stmt.where(c.type.in_(list(types)))
        if type_prefix:
            stmt = stmt.where(c.type.like(f"{type_prefix}%"))
        stmt = stmt.order_by(c.seq.desc() if newest_first else c.seq).limit(limit)
        return self._rows(stmt)

    def last_seq(self) -> int:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT COALESCE(MAX(seq), 0) FROM events")).scalar_one()

    def count(self) -> int:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM events")).scalar_one()
