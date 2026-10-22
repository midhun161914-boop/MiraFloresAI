"""resolve_ref: the edge resolver of the evidence graph.

Every pointer in the packet (``readme.reference_formats``) goes through here and
comes back as the same shape: what kind of node it is, the node itself, a
human label, and a deep link into the UI. Trace views, source chips and
diagnostics never parse references on their own.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional
from urllib.parse import quote

from pydantic import BaseModel

from app.services.loader import PacketIndex


class RefResolution(BaseModel):
    ref: str
    found: bool
    kind: str
    id: Optional[str] = None
    label: str
    link: Optional[str] = None
    # Trace contract for anything that lives on a document page. A real PDF can
    # replace the rendered page later without changing this shape.
    document_id: Optional[str] = None
    page: Optional[int] = None
    position: Optional[dict[str, float]] = None
    version: Optional[str] = None
    note: Optional[str] = None
    target: Any = None


# Bare tokens the packet uses as sources that are not in the pointer grammar.
ALIASES = {
    "prior_preparer_depreciation_schedule": "py:/prior_preparer_workpaper/depreciation_schedule",
}

_LINE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9-]*\.[A-Za-z0-9.-]+$")


def _short(text: str, n: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _dump(obj: Any) -> Any:
    return obj.model_dump(by_alias=True) if isinstance(obj, BaseModel) else obj


def _inspector(ref: str) -> str:
    return f"/ref?r={quote(ref, safe='')}"


def json_pointer(doc: Any, pointer: str) -> Any:
    """RFC 6901. Raises KeyError/IndexError when the path does not exist."""
    if pointer in ("", "/"):
        return doc
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    cur = doc
    for raw in pointer[1:].split("/"):
        tok = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            cur = cur[int(tok)]
        elif isinstance(cur, dict):
            cur = cur[tok]
        else:
            raise KeyError(tok)
    return cur


def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return f"{v:,.2f}" if isinstance(v, float) and not v.is_integer() else f"{v:,.0f}"
    return str(v)


class RefResolver:
    def __init__(self, idx: PacketIndex):
        self.idx = idx
        self._handlers: list[tuple[re.Pattern[str], Callable[..., RefResolution]]] = [
            (re.compile(r"^ev-\d{4}$"), self._ev),
            (re.compile(r"^D\d{2}$"), self._doc),
            (re.compile(r"^doc:(D\d{2})#page(\d+)$"), self._doc_page),
            (re.compile(r"^qa-\d+$"), self._questionnaire),
            (re.compile(r"^msg-\d+$"), self._message),
            (re.compile(r"^call-\d+$"), self._call),
            (re.compile(r"^py:(/.*)$"), self._prior),
            (re.compile(r"^agency:(/.*)$"), self._agency),
            (re.compile(r"^asset:(.+)$"), self._asset),
            (re.compile(r"^household:(.+)$"), self._person),
            (re.compile(r"^ref:param\.(.+)$"), self._param),
            (re.compile(r"^ref:fx\.([A-Z]{3})\.(.+)$"), self._fx),
            (re.compile(r"^timeline:(.+)$"), self._timeline),
            (re.compile(r"^v\d+$"), self._version),
            (re.compile(r"^R-[A-Z0-9-]+$"), self._rule),
            (_LINE_KEY, self._line),
        ]

    # ------------------------------------------------------------------ api
    def resolve(self, ref: str, version: Optional[str] = None) -> RefResolution:
        ref = ref.strip()
        target = ALIASES.get(ref, ref)
        for pattern, handler in self._handlers:
            m = pattern.match(target)
            if m:
                try:
                    res = handler(m, version or self.idx.current_version)
                except (KeyError, IndexError, ValueError):
                    res = None
                if res is not None:
                    res.ref = ref
                    if target != ref:
                        res.note = (res.note + " " if res.note else "") + f"Alias of {target}."
                    return res
        return RefResolution(ref=ref, found=False, kind="unknown",
                             label=f"Unresolved reference: {ref}")

    # ------------------------------------------------------------- handlers
    def _ev(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        ev = self.idx.values.get(m.group(0))
        if ev is None:
            return None
        doc = self.idx.documents[ev.document_id]
        return RefResolution(
            ref=ev.id, found=True, kind="extracted_value", id=ev.id,
            label=f"{ev.label}: {ev.text_as_read or '(blank)'} · {doc.id} p.{ev.page}",
            link=f"/documents/{doc.id}?page={ev.page}&ev={ev.id}",
            document_id=doc.id, page=ev.page, position=ev.position.model_dump(),
            target=_dump(ev),
        )

    def _doc(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        d = self.idx.documents.get(m.group(0))
        if d is None:
            return None
        summary = {k: v for k, v in _dump(d).items() if k != "pages"}
        return RefResolution(
            ref=d.id, found=True, kind="document", id=d.id, label=f"{d.id} · {d.title}",
            link=f"/documents/{d.id}", document_id=d.id, target=summary,
        )

    def _doc_page(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        d = self.idx.documents.get(m.group(1))
        n = int(m.group(2))
        if d is None or not 1 <= n <= d.page_count:
            return None
        read = any(e.page == n for e in self.idx.values_by_doc.get(d.id, []))
        return RefResolution(
            ref=m.group(0), found=True, kind="document_page", id=f"{d.id}#page{n}",
            label=f"{d.id} p.{n} · {d.title}", link=f"/documents/{d.id}?page={n}",
            document_id=d.id, page=n,
            note=None if read else "No values were extracted from this page.",
            target=_dump(d.pages[n - 1]),
        )

    def _questionnaire(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        q = self.idx.by_id["questionnaire"].get(m.group(0))
        if q is None:
            return None
        return RefResolution(
            ref=q.id, found=True, kind="questionnaire", id=q.id,
            label=f"Questionnaire {q.id}: {_short(q.question, 60)} → {_short(q.answer, 40)}",
            link=_inspector(q.id), target=_dump(q),
        )

    def _message(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        msg = self.idx.by_id["message"].get(m.group(0))
        if msg is None:
            return None
        return RefResolution(
            ref=msg.id, found=True, kind="message", id=msg.id,
            label=f"Message {msg.id} from {msg.from_} ({msg.sent_at[:10]}): {_short(msg.text, 50)}",
            link=_inspector(msg.id), target=_dump(msg),
        )

    def _call(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        c = self.idx.by_id["call_note"].get(m.group(0))
        if c is None:
            return None
        return RefResolution(
            ref=c.id, found=True, kind="call_note", id=c.id,
            label=f"Call notes {c.id} ({c.date}) with {', '.join(c.participants)}",
            link=_inspector(c.id), target=_dump(c),
        )

    def _prior(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        pointer = m.group(1)
        value = json_pointer(self.idx.raw["prior_years"], pointer)
        parts = [p for p in pointer.split("/") if p]
        label = "Prior years › " + " › ".join(parts)
        if len(parts) == 3 and parts[:2] == ["return_2024", "lines"]:
            lbl = self.idx.packet.prior_years.return_2024.line_labels.get(parts[2])
            label = f"2024 return {parts[2]}{' · ' + lbl if lbl else ''} = {_fmt(value)}"
        elif not isinstance(value, (dict, list)):
            label += f" = {_fmt(value)}"
        return RefResolution(
            ref=m.group(0), found=True, kind="prior_year", id=pointer, label=label,
            link=_inspector(m.group(0)), target=value,
        )

    def _agency(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        pointer = m.group(1)
        value = json_pointer(self.idx.raw["tax_agency_records"], pointer)
        parts = [p for p in pointer.split("/") if p]
        label = "Agency records › " + " › ".join(parts)
        if isinstance(value, dict) and "type" in value:
            label = f"{value.get('agency', '')} {value['type']} ({value.get('dated', '')})".strip()
        return RefResolution(
            ref=m.group(0), found=True, kind="agency_record", id=pointer, label=label,
            link=_inspector(m.group(0)), target=value,
        )

    def _asset(self, m: re.Match[str], version: str) -> Optional[RefResolution]:
        aid = m.group(1)
        ver = self.idx.versions.get(version) or self.idx.current
        asset = next((a for a in ver.assets if a.asset_id == aid), None)
        if asset is not None:
            return RefResolution(
                ref=m.group(0), found=True, kind="asset", id=aid, version=ver.version,
                label=f"Asset {aid} · {asset.description}", link=_inspector(m.group(0)),
                target=_dump(asset),
            )
        prior = self.idx.by_id["prior_asset"].get(aid)
        if prior is None:
            return None
        return RefResolution(
            ref=m.group(0), found=True, kind="asset", id=aid,
            label=f"Asset {aid} · {prior.description} (prior-year record)",
            link=_inspector(m.group(0)), target=_dump(prior),
        )

    def _person(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        p = self.idx.by_id["person"].get(m.group(1))
        if p is None:
            return None
        return RefResolution(
            ref=m.group(0), found=True, kind="person", id=p.id,
            label=f"{p.name} ({p.role}{', ' + p.relationship if p.relationship else ''})",
            link=_inspector(m.group(0)), target=_dump(p),
        )

    def _param(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        name = m.group(1)
        value = self.idx.packet.engine_reference.parameters[name]
        shown = _fmt(value) if not isinstance(value, (dict, list)) else "table"
        return RefResolution(
            ref=m.group(0), found=True, kind="parameter", id=name,
            label=f"Engine parameter {name} = {shown}", link=_inspector(m.group(0)),
            target=value,
        )

    def _fx(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        ccy, rate = m.group(1), m.group(2)
        value = self.idx.packet.engine_reference.parameters["fx"][ccy][rate]
        return RefResolution(
            ref=m.group(0), found=True, kind="fx_rate", id=f"{ccy}.{rate}",
            label=f"{ccy} per USD, {rate.replace('_', ' ')} = {value}",
            link=_inspector(m.group(0)), target=value,
        )

    def _timeline(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        t = self.idx.by_id["timeline"].get(m.group(1))
        if t is None:
            return None
        return RefResolution(
            ref=m.group(0), found=True, kind="timeline_event", id=t.id,
            label=f"{t.event.replace('_', ' ')} · {t.at[:10]}", link=_inspector(m.group(0)),
            target=_dump(t),
        )

    def _version(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        v = self.idx.versions.get(m.group(0))
        if v is None:
            return None
        return RefResolution(
            ref=v.version, found=True, kind="return_version", id=v.version, version=v.version,
            label=f"Return {v.version} computed {v.computed_at[:10]}",
            link=_inspector(v.version),
            target={k: val for k, val in _dump(v).items() if k not in ("lines",)},
        )

    def _rule(self, m: re.Match[str], _v: str) -> Optional[RefResolution]:
        text = self.idx.packet.engine_reference.rules.get(m.group(0))
        if text is None:
            return None
        return RefResolution(
            ref=m.group(0), found=True, kind="rule", id=m.group(0),
            label=f"Rule {m.group(0)}: {_short(text, 70)}", link=_inspector(m.group(0)),
            target={"id": m.group(0), "description": text},
        )

    def _line(self, m: re.Match[str], version: str) -> Optional[RefResolution]:
        key = m.group(0)
        order = [version] + [v for v in reversed(list(self.idx.lines)) if v != version]
        for ver in order:
            line = self.idx.lines.get(ver, {}).get(key)
            if line is not None:
                note = None if ver == version else f"Not in {version}; shown from {ver}."
                return RefResolution(
                    ref=key, found=True, kind="return_line", id=key, version=ver,
                    label=f"{key} · {line.label} = {_fmt(line.value)}",
                    link=f"/lines/{quote(key, safe='')}" + ("" if ver == self.idx.current_version else f"?version={ver}"),
                    note=note, target=_dump(line),
                )
        return None


def all_packet_refs(idx: PacketIndex) -> set[str]:
    """Every reference string the packet itself uses (for regression tests)."""
    p = idx.packet
    refs: set[str] = set()
    for v in p.return_versions:
        for ln in v.lines:
            refs.update(ln.sources)
            refs.update(ln.inputs)
        for a in v.assets:
            refs.update(a.sources)
        for d in v.diagnostics:
            refs.update(d.refs)
        refs.update(v.documents_used + v.documents_superseded)
    for t in p.timeline:
        refs.update(t.refs)
    for a in p.prior_years.asset_records:
        refs.update(a.sources)
    refs.update(p.prior_years.return_2024.line_sources.values())
    return refs
