"""Bidirectional evidence tracing over the packet's graph.

Down (number -> evidence):  line --sources--> extracted value --> document/page/position
Down (number -> math):      line --inputs--> line --inputs--> ... --> leaves with sources
Up   (evidence -> number):  document --> values --> every line that cites them
Up   (math -> total):       line --used_by--> lines that take it as an input

Every edge is followed through ``resolve_ref``; nothing here parses reference
strings by hand except to expand records that *contain* evidence (a prior-year
line points at its own extracted value; an asset record lists its sources).

When a document does not land anywhere, the reason is derived from the data
(supersession lists, field-by-field duplicate matching, extraction status,
mentions elsewhere in the packet), never from a hard-coded list of documents.
"""

from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache
from typing import Any, Literal, Optional

from pydantic import BaseModel

from app.models.packet import Document, ReturnLine, ReturnVersion
from app.services.loader import PacketIndex
from app.services.refs import RefResolution, RefResolver, json_pointer

EV = re.compile(r"\bev-\d{4}\b")
DOC = re.compile(r"\bD\d{2}\b")

LandingStatus = Literal[
    "lands", "lands_indirectly", "superseded", "duplicate", "not_extracted", "support_only", "not_used",
]


# --------------------------------------------------------------------- models
class Landing(BaseModel):
    """One evidence edge: value -> line. ``via`` is the record it travelled through."""
    ev: str
    line: str
    via: Optional[str] = None


class LineBrief(BaseModel):
    key: str
    label: str
    value: Any
    form: str
    line: str
    jurisdiction: str
    rule: str


class Reason(BaseModel):
    code: str
    tone: Literal["neutral", "open", "warning", "error", "verified"]
    title: str
    detail: str
    refs: list[str] = []


class LandedLine(BaseModel):
    line: LineBrief
    evidence: list[Landing]


class VersionUse(BaseModel):
    version: str
    use: Literal["used", "superseded", "not_used"]
    lines: int


class DocumentLanding(BaseModel):
    document_id: str
    version: str
    status: LandingStatus
    headline: str
    reasons: list[Reason]
    lines: list[LandedLine]
    values_total: int
    values_cited: int
    unread_pages: list[int]  # pages the pipeline reports it did not read
    pages_without_values: int  # includes pages with nothing to read ("no further transactions")
    mentions: list[RefResolution]
    by_version: list[VersionUse]
    replaced_by: Optional[str] = None
    duplicate_of: Optional[str] = None


class Excerpt(BaseModel):
    text: str
    start: int  # highlight span within ``text``
    end: int
    clipped_left: bool
    clipped_right: bool


class TraceSource(BaseModel):
    ref: str
    resolution: RefResolution
    excerpt: Optional[Excerpt] = None
    document_status: Optional[LandingStatus] = None
    behind: list["TraceSource"] = []  # evidence inside a record (prior-year line, asset)


class VersionValue(BaseModel):
    version: str
    value: Any = None
    present: bool
    change: Optional[str] = None


class PriorYear(BaseModel):
    ref: str
    label: Optional[str] = None
    value: Any


class LineTrace(BaseModel):
    version: str
    line: ReturnLine
    rule_text: Optional[str]
    sources: list[TraceSource]
    inputs: list[LineBrief]
    used_by: list[LineBrief]
    by_version: list[VersionValue]
    prior_year: Optional[PriorYear] = None
    diagnostics: list[dict[str, Any]] = []
    closure_size: int  # lines reachable through inputs (how deep the math goes)
    depth: int


class GraphNode(BaseModel):
    key: str
    label: str
    value: Any
    form: str
    line: str
    jurisdiction: str
    rule: str
    rule_text: Optional[str]
    inputs: list[str]
    used_by: list[str]
    sources: list[str]
    note: Optional[str] = None
    used_by_count: int


class CalcGraph(BaseModel):
    version: str
    root: str
    direction: Literal["down", "up"]
    nodes: dict[str, GraphNode]
    depth: int


# ---------------------------------------------------------------------- index
def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def brief(ln: ReturnLine) -> LineBrief:
    return LineBrief(key=ln.key, label=ln.label, value=ln.value, form=ln.form, line=ln.line,
                     jurisdiction=ln.jurisdiction, rule=ln.rule)


class TraceIndex:
    def __init__(self, idx: PacketIndex, resolver: RefResolver):
        self.idx = idx
        self.resolver = resolver
        self.ev_lines: dict[str, dict[str, list[Landing]]] = {}
        self.used_by: dict[str, dict[str, list[str]]] = {}
        for v in idx.packet.return_versions:
            evl: dict[str, list[Landing]] = defaultdict(list)
            parents: dict[str, list[str]] = defaultdict(list)
            for ln in v.lines:
                for src in ln.sources:
                    if EV.fullmatch(src):
                        evl[src].append(Landing(ev=src, line=ln.key))
                    else:
                        for ev in self.evs_behind(src, v.version):
                            evl[ev].append(Landing(ev=ev, line=ln.key, via=src))
                for inp in ln.inputs:
                    parents[inp].append(ln.key)
            self.ev_lines[v.version] = dict(evl)
            self.used_by[v.version] = dict(parents)
        self.mentions = self._collect_mentions()
        self._landing_cache: dict[tuple[str, str], DocumentLanding] = {}

    # ---- evidence inside records -------------------------------------------------
    def evs_behind(self, ref: str, version: str, _depth: int = 0) -> list[str]:
        """Extracted values that a non-value reference stands on."""
        if _depth > 2:
            return []
        p = self.idx.packet
        if ref.startswith("py:/return_2024/lines/"):
            key = ref.rsplit("/", 1)[1]
            src = p.prior_years.return_2024.line_sources.get(key)
            return [src] if src and EV.fullmatch(src) else []
        if ref.startswith("asset:"):
            aid = ref.split(":", 1)[1]
            ver = self.idx.versions[version]
            asset = next((a for a in ver.assets if a.asset_id == aid), None)
            prior = self.idx.by_id["prior_asset"].get(aid)
            out: list[str] = []
            for s in (asset.sources if asset else []):
                if EV.fullmatch(s):
                    out.append(s)
                elif s == "py:/asset_records" and prior is not None:
                    out += [x for x in prior.sources if EV.fullmatch(x)]
            return list(dict.fromkeys(out))
        if ref.startswith("py:/"):
            try:
                val = json_pointer(self.idx.raw["prior_years"], ref[3:])
            except (KeyError, IndexError, ValueError):
                return []
            return list(dict.fromkeys(EV.findall(str(val))))
        return []

    # ---- where documents are mentioned outside documents/values -------------------
    def _collect_mentions(self) -> dict[str, list[str]]:
        """doc id -> refs of records that name the document or one of its values."""
        ev_doc = {e.id: e.document_id for e in self.idx.packet.extracted_values}
        found: dict[str, list[str]] = defaultdict(list)
        raw = self.idx.raw

        def add(doc: str, ref: str) -> None:
            if doc in self.idx.documents and ref not in found[doc]:
                found[doc].append(ref)

        def scan(value: Any, ref: str) -> None:
            text = str(value)
            for d in DOC.findall(text):
                add(d, ref)
            for ev in EV.findall(text):
                if ev in ev_doc:
                    add(ev_doc[ev], ref)

        for t in raw["timeline"]:
            scan(t.get("refs", []), f"timeline:{t['id']}")
        for i, n in enumerate(raw["tax_agency_records"].get("notices", [])):
            scan(n, f"agency:/notices/{i}")
        pw = raw["prior_years"]
        for name, rows in pw.get("basis_records", {}).items():
            for i, row in enumerate(rows):
                scan(row, f"py:/basis_records/{name}/{i}")
        scan(pw.get("prior_preparer_workpaper", {}).get("source_document", ""),
             "py:/prior_preparer_workpaper")
        for q in raw["client"]["messages"]:
            scan(q["text"], q["id"])
        cur = self.idx.current
        for ln in cur.lines:
            if ln.note:
                for d in DOC.findall(ln.note):
                    add(d, ln.key)
        return dict(found)

    # ---- per-value / per-document landing ----------------------------------------
    def lands_in(self, ev: str, version: Optional[str] = None) -> list[str]:
        v = version or self.idx.current_version
        return list(dict.fromkeys(x.line for x in self.ev_lines[v].get(ev, [])))

    def doc_lines(self, doc_id: str, version: str) -> dict[str, list[Landing]]:
        out: dict[str, list[Landing]] = defaultdict(list)
        for e in self.idx.values_by_doc.get(doc_id, []):
            for land in self.ev_lines[version].get(e.id, []):
                out[land.line].append(land)
        return dict(out)

    def _duplicate_of(self, doc: Document, version: str) -> Optional[tuple[str, int, int]]:
        """Another document of the same type whose read values match field by field."""
        mine = {e.field: str(e.value) for e in self.idx.values_by_doc.get(doc.id, [])}
        if len(mine) < 3:
            return None
        best: Optional[tuple[str, int, int]] = None
        for other in self.idx.packet.documents:
            if other.id == doc.id or other.document_type != doc.document_type:
                continue
            if not self.doc_lines(other.id, version):
                continue  # only a document that itself lands can be "the one counted"
            theirs = {e.field: str(e.value) for e in self.idx.values_by_doc.get(other.id, [])}
            common = set(mine) & set(theirs)
            if len(common) < 3:
                continue
            same = sum(mine[f] == theirs[f] for f in common)
            if same / len(common) >= 0.9 and (best is None or same > best[1]):
                best = (other.id, same, len(common))
        return best

    def _replaced_by(self, doc: Document, v: ReturnVersion) -> Optional[str]:
        cands = [
            d for d in self.idx.packet.documents
            if d.id in v.documents_used and d.id != doc.id
            and d.document_type == doc.document_type and d.issuer == doc.issuer
        ]
        cands.sort(key=lambda d: (not d.marked_corrected, d.received_at))
        return cands[0].id if cands else None

    def landing(self, doc_id: str, version: Optional[str] = None) -> DocumentLanding:
        v = self.idx.versions[version or self.idx.current_version]
        key = (doc_id, v.version)
        if key in self._landing_cache:
            return self._landing_cache[key]
        doc = self.idx.documents[doc_id]
        values = self.idx.values_by_doc.get(doc_id, [])
        lines = self.doc_lines(doc_id, v.version)
        cited = {land.ev for lands in lines.values() for land in lands}
        direct = any(land.via is None for lands in lines.values() for land in lands)
        read_pages = {e.page for e in values}
        no_values = [pg.page for pg in doc.pages if pg.page not in read_pages]
        # "Unread" means the pipeline says so (pages named in extraction.reason). Pages that
        # simply carry no fields ("no further transactions") are not unread.
        named = [int(n) for n in re.findall(r"\b[Pp]ages? (\d+)", doc.extraction.reason or "")]
        unread = [n for n in named if 1 <= n <= doc.page_count] if named else (
            no_values if doc.extraction.status == "partial" else [])
        reasons: list[Reason] = []
        replaced_by = duplicate_of = None

        if doc_id in v.documents_superseded:
            status: LandingStatus = "superseded"
            replaced_by = self._replaced_by(doc, v)
            since = next((x for x in self.idx.packet.return_versions if doc_id in x.documents_superseded), v)
            earlier = [x for x in self.idx.packet.return_versions if doc_id in x.documents_used]
            detail = f"Listed as superseded in {v.version}"
            if replaced_by:
                rb = self.idx.documents[replaced_by]
                detail += f"; replaced by {replaced_by}" + (" (issuer marked CORRECTED)" if rb.marked_corrected else "")
            detail += f". Since {since.version}: {since.trigger}"
            if earlier:
                detail += f" Earlier versions that used it: {', '.join(x.version for x in earlier)}."
            reasons.append(Reason(code="SUPERSEDED", tone="error", title="Superseded — must not flow through",
                                  detail=detail, refs=[r for r in [replaced_by, since.version] if r]))
        elif doc_id not in v.documents_used:
            status = "not_used"
            reasons.append(Reason(
                code="NOT_USED", tone="neutral", title=f"Not used by the engine in {v.version}",
                detail=doc.extraction.reason or "The document is in the file but the return does not draw on it.",
            ))
        elif direct:
            status = "lands"
        elif lines:
            status = "lands_indirectly"
            vias = sorted({land.via for lands in lines.values() for land in lands if land.via})
            reasons.append(Reason(
                code="INDIRECT", tone="open", title="Lands through another record",
                detail="No line cites these values directly; they reach the return through "
                       + ", ".join(vias[:4]) + (" …" if len(vias) > 4 else "") + ".",
                refs=vias[:6],
            ))
        else:
            dup = self._duplicate_of(doc, v.version)
            if dup is not None:
                status = "duplicate"
                duplicate_of, same, common = dup
                note_lines = [r for r in self.mentions.get(doc_id, []) if r in self.idx.lines[v.version]]
                detail = (f"{same} of {common} fields read from {doc_id} match {duplicate_of} exactly "
                          f"(same document type). {duplicate_of} is counted; {doc_id} is not.")
                for lk in note_lines:
                    detail += f" Line {lk} notes: “{self.idx.lines[v.version][lk].note}”"
                reasons.append(Reason(code="DUPLICATE", tone="warning", title=f"Duplicate of {duplicate_of} — counted once",
                                      detail=detail, refs=[duplicate_of, *note_lines]))
            elif doc.extraction.status == "not_extracted":
                status = "not_extracted"
                reasons.append(Reason(code="NOT_EXTRACTED", tone="neutral", title="Not extracted",
                                      detail=doc.extraction.reason or "The pipeline read no values from this document."))
            else:
                status = "support_only"
                reasons.append(Reason(
                    code="SUPPORT_ONLY", tone="neutral", title="Support only",
                    detail=f"Used by the engine in {v.version}, but no return line cites its "
                           f"{len(values)} extracted value{'s' if len(values) != 1 else ''}. "
                           "It may still matter for review (identity, reconciliation, basis).",
                ))

        if doc.extraction.status == "partial" and unread:
            printed = " ".join(
                f"Page {n} prints: “{_clip(doc.pages[n - 1].printed_content, 220)}”" for n in unread[:2]
            )
            reasons.append(Reason(
                code="PARTIAL", tone="warning",
                title=f"Partially extracted — page{'s' if len(unread) != 1 else ''} {', '.join(map(str, unread[:5]))} unread",
                detail=(doc.extraction.reason or "Some pages were not read.")
                + " Nothing printed on an unread page can reach the return. " + printed,
                refs=[f"doc:{doc_id}#page{n}" for n in unread[:5]],
            ))
        if status in ("lands", "lands_indirectly") and values and len(cited) < len(values):
            reasons.append(Reason(
                code="VALUES_NOT_CITED", tone="neutral", title=f"{len(values) - len(cited)} of {len(values)} values not cited",
                detail="Identity fields, dates and descriptive values often support a document without feeding a line.",
            ))

        headline = {
            "lands": f"Feeds {len(lines)} return line{'s' if len(lines) != 1 else ''} in {v.version}",
            "lands_indirectly": f"Feeds {len(lines)} line{'s' if len(lines) != 1 else ''} in {v.version} through other records",
            "superseded": f"Superseded in {v.version}" + (f" by {replaced_by}" if replaced_by else ""),
            "duplicate": f"Duplicate of {duplicate_of} — counted once",
            "not_extracted": "Not extracted",
            "support_only": "Support only — no return line cites it",
            "not_used": f"Not used in {v.version}",
        }[status]

        line_map = self.idx.lines[v.version]
        landed = [
            LandedLine(line=brief(line_map[k]), evidence=lands)
            for k, lands in sorted(lines.items(), key=lambda kv: list(line_map).index(kv[0]))
        ]
        mentions = [self.resolver.resolve(r, v.version) for r in self.mentions.get(doc_id, [])]
        by_version = [
            VersionUse(
                version=x.version,
                use="used" if doc_id in x.documents_used else "superseded" if doc_id in x.documents_superseded else "not_used",
                lines=len(self.doc_lines(doc_id, x.version)),
            )
            for x in self.idx.packet.return_versions
        ]
        out = DocumentLanding(
            document_id=doc_id, version=v.version, status=status, headline=headline, reasons=reasons,
            lines=landed, values_total=len(values), values_cited=len(cited), unread_pages=unread,
            pages_without_values=len(no_values),
            mentions=[m for m in mentions if m.found], by_version=by_version,
            replaced_by=replaced_by, duplicate_of=duplicate_of,
        )
        self._landing_cache[key] = out
        return out

    # ---- line trace ---------------------------------------------------------------
    def _closure(self, key: str, version: str) -> tuple[int, int]:
        lines = self.idx.lines[version]

        @lru_cache(maxsize=None)
        def walk(k: str) -> tuple[frozenset[str], int]:
            seen, depth = {k}, 0
            for i in lines[k].inputs:
                s, d = walk(i)
                seen |= s
                depth = max(depth, d + 1)
            return frozenset(seen), depth

        nodes, depth = walk(key)
        return len(nodes) - 1, depth

    def excerpt(self, ev_id: str, radius: int = 90) -> Optional[Excerpt]:
        e = self.idx.values[ev_id]
        m = self.idx.text_matches[ev_id]
        if m.start is None or m.end is None:
            return None
        text = self.idx.documents[e.document_id].pages[e.page - 1].printed_content
        a, b = max(0, m.start - radius), min(len(text), m.end + radius)
        while a > 0 and text[a - 1] not in " ;": a -= 1  # noqa: E701 - align to word
        while b < len(text) and text[b] not in " ;": b += 1  # noqa: E701
        return Excerpt(text=text[a:b], start=m.start - a, end=m.end - a, clipped_left=a > 0, clipped_right=b < len(text))

    def trace_source(self, ref: str, version: str) -> TraceSource:
        res = self.resolver.resolve(ref, version)
        src = TraceSource(ref=ref, resolution=res)
        if res.kind == "extracted_value":
            src.excerpt = self.excerpt(ref)
            src.document_status = self.landing(res.document_id, version).status  # type: ignore[arg-type]
        elif res.found:
            src.behind = [self.trace_source(ev, version) for ev in self.evs_behind(ref, version)]
        return src

    def line_trace(self, key: str, version: Optional[str] = None) -> Optional[LineTrace]:
        v = version or self.idx.current_version
        lines = self.idx.lines[v]
        ln = lines.get(key)
        if ln is None:
            return None
        by_version = []
        for x in self.idx.packet.return_versions:
            other = self.idx.lines[x.version].get(key)
            change = next((c.change for c in x.changes_from_previous if c.key == key), None)
            by_version.append(VersionValue(version=x.version, value=other.value if other else None,
                                           present=other is not None, change=change))
        p24 = self.idx.packet.prior_years.return_2024
        prior = None
        if key in p24.lines:
            prior = PriorYear(ref=f"py:/return_2024/lines/{key}", label=p24.line_labels.get(key), value=p24.lines[key])
        diags = [d.model_dump() for d in self.idx.versions[v].diagnostics if key in d.refs]
        closure, depth = self._closure(key, v)
        return LineTrace(
            version=v, line=ln, rule_text=self.idx.packet.engine_reference.rules.get(ln.rule),
            sources=[self.trace_source(s, v) for s in ln.sources],
            inputs=[brief(lines[i]) for i in ln.inputs],
            used_by=[brief(lines[p]) for p in self.used_by[v].get(key, [])],
            by_version=by_version, prior_year=prior, diagnostics=diags,
            closure_size=closure, depth=depth,
        )

    def graph(self, key: str, version: Optional[str] = None,
              direction: Literal["down", "up"] = "down") -> Optional[CalcGraph]:
        """Subgraph reachable from ``key``: down = how it was built (inputs),
        up = where it goes (the lines that consume it, up to the totals)."""
        v = version or self.idx.current_version
        lines = self.idx.lines[v]
        if key not in lines:
            return None
        rules = self.idx.packet.engine_reference.rules
        parents = self.used_by[v]
        nodes: dict[str, GraphNode] = {}
        stack = [key]
        while stack:
            k = stack.pop()
            if k in nodes:
                continue
            ln = lines[k]
            ups = parents.get(k, [])
            nodes[k] = GraphNode(
                key=k, label=ln.label, value=ln.value, form=ln.form, line=ln.line,
                jurisdiction=ln.jurisdiction, rule=ln.rule, rule_text=rules.get(ln.rule),
                inputs=ln.inputs, used_by=ups, sources=ln.sources, note=ln.note,
                used_by_count=len(ups),
            )
            stack.extend(ln.inputs if direction == "down" else ups)
        depth = self._closure(key, v)[1] if direction == "down" else self._height(key, v)
        return CalcGraph(version=v, root=key, direction=direction, nodes=nodes, depth=depth)

    def _height(self, key: str, version: str) -> int:
        parents = self.used_by[version]

        @lru_cache(maxsize=None)
        def up(k: str) -> int:
            return max((up(p) + 1 for p in parents.get(k, [])), default=0)

        return up(key)


def summary_line_keys(v: ReturnVersion) -> dict[str, dict[str, Optional[str]]]:
    """Map each summary figure to the main-form line that carries it (by exact value)."""
    forms = {"federal": "F1040", "california": "F540NR"}
    out: dict[str, dict[str, Optional[str]]] = {}
    for side, figures in v.summary.model_dump().items():
        out[side] = {}
        for name, value in figures.items():
            hit = next((ln.key for ln in v.lines
                        if ln.form == forms[side] and isinstance(ln.value, (int, float))
                        and not isinstance(ln.value, bool) and ln.value == value), None)
            out[side][name] = hit
    return out
