"""Load the packet, prove it is intact, and build in-memory indexes.

Flow: root packet (canonical, never touched) -> copied into DATA_DIR -> hash
compared with the original -> parsed into Pydantic models (schema-drift guard)
-> integrity assertions (counts and referential consistency) -> PacketIndex.

If any assertion fails the app refuses to start: a workpaper that silently
loads half a packet is worse than one that does not load.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app import config
from app.models.packet import (
    Document, ExtractedValue, Packet, ReturnLine, ReturnVersion,
)
from app.services.locate import TextMatch, locate


class PacketIntegrityError(RuntimeError):
    def __init__(self, failures: list[str]):
        self.failures = failures
        super().__init__("Packet failed integrity checks:\n  - " + "\n  - ".join(failures))


@dataclass
class PacketIndex:
    packet: Packet
    raw: dict[str, Any]  # parsed JSON, used for JSON-pointer refs (py:/, agency:/)
    sha256: str
    source_path: Path
    load_path: Path
    current_version: str
    documents: dict[str, Document] = field(default_factory=dict)
    values: dict[str, ExtractedValue] = field(default_factory=dict)
    values_by_doc: dict[str, list[ExtractedValue]] = field(default_factory=dict)
    versions: dict[str, ReturnVersion] = field(default_factory=dict)
    lines: dict[str, dict[str, ReturnLine]] = field(default_factory=dict)  # version -> key -> line
    text_matches: dict[str, TextMatch] = field(default_factory=dict)  # ev id -> match
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)  # misc id maps

    @property
    def current(self) -> ReturnVersion:
        return self.versions[self.current_version]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stage_packet(source: Path, data_dir: Path) -> tuple[Path, str]:
    """Copy the canonical packet into the load path; the original is only read."""
    if not source.is_file():
        raise FileNotFoundError(f"Packet not found at {source}")
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / source.name
    src_hash = _sha256(source)
    if source.resolve() != target.resolve():
        if not target.exists() or _sha256(target) != src_hash:
            if target.exists():
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
            shutil.copy2(source, target)
        os.chmod(target, stat.S_IREAD)  # the working copy is read-only too
    if _sha256(target) != src_hash:
        raise PacketIntegrityError([f"Staged copy {target} does not match {source}"])
    return target, src_hash


def check_integrity(p: Packet) -> list[str]:
    """Counts from the brief plus referential consistency inside the packet."""
    fails: list[str] = []
    counts = {
        "documents": len(p.documents),
        "extracted_values": len(p.extracted_values),
        "return_versions": len(p.return_versions),
    }
    for k, want in config.EXPECTED_COUNTS.items():
        if counts[k] != want:
            fails.append(f"expected {want} {k}, found {counts[k]}")

    def dupes(ids: list[str], what: str) -> None:
        seen: set[str] = set()
        for i in ids:
            if i in seen:
                fails.append(f"duplicate {what} id {i}")
            seen.add(i)

    dupes([d.id for d in p.documents], "document")
    dupes([e.id for e in p.extracted_values], "extracted value")
    dupes([v.version for v in p.return_versions], "return version")

    docs = {d.id: d for d in p.documents}
    per_doc: dict[str, int] = defaultdict(int)
    for d in p.documents:
        if len(d.pages) != d.page_count:
            fails.append(f"{d.id}: page_count {d.page_count} but {len(d.pages)} pages")
        if [pg.page for pg in d.pages] != list(range(1, len(d.pages) + 1)):
            fails.append(f"{d.id}: pages are not numbered 1..n")
    for e in p.extracted_values:
        d = docs.get(e.document_id)
        if d is None:
            fails.append(f"{e.id}: unknown document {e.document_id}")
            continue
        per_doc[d.id] += 1
        if not 1 <= e.page <= d.page_count:
            fails.append(f"{e.id}: page {e.page} outside {d.id} (1..{d.page_count})")
    for d in p.documents:
        if per_doc[d.id] != d.extraction.values:
            fails.append(
                f"{d.id}: extraction.values={d.extraction.values} but {per_doc[d.id]} values present"
            )

    ev_ids = {e.id for e in p.extracted_values}
    for v in p.return_versions:
        keys = {ln.key for ln in v.lines}
        if len(keys) != len(v.lines):
            fails.append(f"{v.version}: duplicate line keys")
        for ln in v.lines:
            for s in ln.sources:
                if s.startswith("ev-") and s not in ev_ids:
                    fails.append(f"{v.version} {ln.key}: source {s} not in extracted_values")
            for i in ln.inputs:
                if i not in keys:
                    fails.append(f"{v.version} {ln.key}: input {i} not a line in {v.version}")
            if ln.rule not in p.engine_reference.rules:
                fails.append(f"{v.version} {ln.key}: rule {ln.rule} not in engine_reference.rules")
        for did in v.documents_used + v.documents_superseded:
            if did not in docs:
                fails.append(f"{v.version}: unknown document {did}")
    return fails


def build_index(p: Packet, raw: dict[str, Any], sha: str, source: Path, load_path: Path) -> PacketIndex:
    idx = PacketIndex(
        packet=p, raw=raw, sha256=sha, source_path=source, load_path=load_path,
        current_version=config.CURRENT_VERSION,
    )
    idx.documents = {d.id: d for d in p.documents}
    idx.values = {e.id: e for e in p.extracted_values}
    by_doc: dict[str, list[ExtractedValue]] = defaultdict(list)
    for e in p.extracted_values:
        by_doc[e.document_id].append(e)
    idx.values_by_doc = {k: sorted(v, key=lambda e: (e.page, e.id)) for k, v in by_doc.items()}
    idx.versions = {v.version: v for v in p.return_versions}
    idx.lines = {v.version: {ln.key: ln for ln in v.lines} for v in p.return_versions}

    for e in p.extracted_values:
        page = idx.documents[e.document_id].pages[e.page - 1].printed_content
        idx.text_matches[e.id] = locate(e.text_as_read, page, e.field, e.label, e.value, e.value_type)

    idx.by_id = {
        "questionnaire": {q.id: q for q in p.client.questionnaire},
        "message": {m.id: m for m in p.client.messages},
        "call_note": {c.id: c for c in p.client.call_notes},
        "person": {x.id: x for x in p.household.people},
        "timeline": {t.id: t for t in p.timeline},
        "staff": {s.id: s for s in p.firm.staff},
        "client_user": {c.id: c for c in p.firm.client_users},
        "prior_asset": {a.asset_id: a for a in p.prior_years.asset_records},
    }
    if idx.current_version not in idx.versions:
        raise PacketIntegrityError([f"current version {idx.current_version} not in packet"])
    return idx


def load_packet(source: Path | None = None, data_dir: Path | None = None) -> PacketIndex:
    source = source or config.PACKET_SOURCE
    data_dir = data_dir or config.DATA_DIR
    load_path, sha = stage_packet(source, data_dir)
    raw_bytes = load_path.read_bytes()
    packet = Packet.model_validate_json(raw_bytes)
    fails = check_integrity(packet)
    if fails:
        raise PacketIntegrityError(fails)
    return build_index(packet, json.loads(raw_bytes), sha, source, load_path)
