from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.schemas import (
    PersonBrief, DocumentDetail, DocumentSummary, LineRow, LinesPage, Overview, ResolveBatchIn, TextMatchOut,
    ValueOut, ValuesPage, VersionSummary,
)
from app.models.packet import Document, ExtractedValue
from app.services.actors import Actor, current_actor, require_staff
from app.services.loader import PacketIndex
from app.services.redact import SENSITIVE_VALUE_TYPES, Redactor, mask_keep_last4
from app.services.refs import RefResolution, RefResolver
from app.services.search import SearchResults, search as run_search, search_workpaper
from app.services.trace import (
    CalcGraph, DocumentLanding, LineTrace, TraceIndex, TraceSource, summary_line_keys,
)

LOW_CONFIDENCE = 0.80

# Firm workpaper API: staff only. Client users get the client surface (review_routes.client_router).
router = APIRouter(prefix="/api", dependencies=[Depends(require_staff)])
# Identity endpoints every signed-in user (staff or client) needs.
public = APIRouter(prefix="/api")


def _idx(request: Request) -> PacketIndex:
    return request.app.state.index


def _resolver(request: Request) -> RefResolver:
    return request.app.state.resolver


def _trace(request: Request) -> TraceIndex:
    return request.app.state.trace


def _log_view(request: Request, actor: Actor, node: str, *, masked: bool, fields: int) -> None:
    """Sensitive data was served (masked or not): record it in the view log."""
    if fields:
        request.app.state.review.log_view(actor, node, masked=masked, endpoint=request.url.path, fields=fields)


def _sensitive_in_text(request: Request, text: str) -> int:
    red: Redactor = request.app.state.redactor
    return int(red.text(text) != text)


def _version(request: Request, version: Optional[str]) -> str:
    idx = _idx(request)
    v = version or idx.current_version
    if v not in idx.versions:
        raise HTTPException(404, f"No return version {v}")
    return v


def redactor_for(request: Request, actor: Actor = Depends(current_actor)) -> Optional[Redactor]:
    """None when the acting user is cleared to see sensitive identifiers."""
    return None if actor.sensitive_data_clearance else request.app.state.redactor


def _value_out(idx: PacketIndex, e: ExtractedValue, red: Optional[Redactor] = None,
               trace: Optional[TraceIndex] = None, review: Any = None) -> ValueOut:
    m = idx.text_matches[e.id]
    out = ValueOut(
        **e.model_dump(),
        document_title=idx.documents[e.document_id].title,
        match=TextMatchOut(**m.__dict__),
        lands_in=trace.lands_in(e.id) if trace else [],
    )
    if red is not None and e.value_type in SENSITIVE_VALUE_TYPES:
        out.value = mask_keep_last4(str(e.value)) if e.value is not None else None
        out.text_as_read = mask_keep_last4(e.text_as_read)
        if out.match.matched_text:
            out.match.matched_text = mask_keep_last4(out.match.matched_text)
        out.redacted = True
    corr = review.active_correction(e.id) if review is not None else None
    if corr is not None:
        masked = red is not None and e.value_type in SENSITIVE_VALUE_TYPES
        out.correction = {"to": "•••" if masked else corr["to"], "from": "•••" if masked else corr["from"],
                          "reason": corr["reason"], "by": review.name(corr["actor"]), "at": corr["at"]}
    return out


def _redact_resolution(res: RefResolution, red: Optional[Redactor]) -> RefResolution:
    if red is None:
        return res
    return res.model_copy(update={"label": red.text(res.label), "target": red.obj(res.target)})


def _redact_source(src: TraceSource, red: Optional[Redactor]) -> TraceSource:
    if red is None:
        return src
    return src.model_copy(update={
        "resolution": _redact_resolution(src.resolution, red),
        "excerpt": src.excerpt.model_copy(update={"text": red.text(src.excerpt.text)}) if src.excerpt else None,
        "behind": [_redact_source(b, red) for b in src.behind],
    })


def _doc_summary(idx: PacketIndex, d: Document, trace: Optional[TraceIndex] = None) -> DocumentSummary:
    values = idx.values_by_doc.get(d.id, [])
    used = [v.version for v in idx.packet.return_versions if d.id in v.documents_used]
    superseded = [v.version for v in idx.packet.return_versions if d.id in v.documents_superseded]
    cur = idx.current
    use = ("used" if d.id in cur.documents_used
           else "superseded" if d.id in cur.documents_superseded else "not_used")
    return DocumentSummary(
        **d.model_dump(exclude={"pages"}),
        value_count=len(values),
        low_confidence_count=sum(1 for e in values if e.confidence < LOW_CONFIDENCE),
        unlocated_count=sum(1 for e in values if idx.text_matches[e.id].status == "not_found"),
        used_in=used, superseded_in=superseded, current_use=use,
        **({"landing_status": (land := trace.landing(d.id)).status, "lines_fed": len(land.lines)} if trace else {}),
    )


@public.get("/health")
def health(request: Request) -> dict[str, str]:
    return {"status": "ok", "packet_sha256": _idx(request).sha256}


@router.get("/overview", response_model=Overview)
def overview(request: Request) -> Overview:
    idx = _idx(request)
    p = idx.packet
    return Overview(
        client_id=p.packet.client_id,
        household_name=p.packet.name,
        tax_year=p.household.tax_year,
        filing_status=p.household.filing_status,
        people=[PersonBrief(id=x.id, name=x.name, role=x.role) for x in p.household.people],
        current_version=idx.current_version,
        packet_sha256=idx.sha256,
        counts={
            "documents": len(p.documents),
            "extracted_values": len(p.extracted_values),
            "return_versions": len(p.return_versions),
            "rules": len(p.engine_reference.rules),
            "timeline_events": len(p.timeline),
        },
        versions=versions(request),
        low_confidence_threshold=LOW_CONFIDENCE,
    )


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(request: Request) -> list[DocumentSummary]:
    idx = _idx(request)
    return [_doc_summary(idx, d, _trace(request)) for d in idx.packet.documents]


@router.get("/documents/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: str, request: Request,
                 red: Optional[Redactor] = Depends(redactor_for),
                 actor: Actor = Depends(current_actor)) -> DocumentDetail:
    idx = _idx(request)
    d = idx.documents.get(doc_id)
    if d is None:
        raise HTTPException(404, f"No document {doc_id}")
    sensitive = sum(_sensitive_in_text(request, pg.printed_content) for pg in d.pages)
    _log_view(request, actor, doc_id, masked=red is not None, fields=sensitive)
    return DocumentDetail(
        **_doc_summary(idx, d, _trace(request)).model_dump(),
        pages=[pg.model_copy(update={"printed_content": red.text(pg.printed_content)}) for pg in d.pages]
        if red else d.pages,
        values=[_value_out(idx, e, red, _trace(request), request.app.state.review)
                for e in idx.values_by_doc.get(d.id, [])],
        redacted=red is not None,
    )


@router.get("/values", response_model=ValuesPage)
def list_values(
    request: Request,
    document_id: Optional[str] = None,
    value_type: Optional[str] = Query(None, description="Comma-separated value types"),
    q: Optional[str] = Query(None, description="Search id, field, label, text read"),
    max_confidence: Optional[float] = Query(None, ge=0, le=1),
    match: Optional[str] = Query(None, description="Comma-separated text-match statuses"),
    sort: str = Query("id", pattern="^(id|confidence|document)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=5000),
    red: Optional[Redactor] = Depends(redactor_for),
    actor: Actor = Depends(current_actor),
) -> ValuesPage:
    idx = _idx(request)
    items = idx.packet.extracted_values
    if document_id:
        items = idx.values_by_doc.get(document_id, [])
    if value_type:
        types = set(value_type.split(","))
        items = [e for e in items if e.value_type in types]
    if max_confidence is not None:
        items = [e for e in items if e.confidence <= max_confidence]
    if match:
        statuses = set(match.split(","))
        items = [e for e in items if idx.text_matches[e.id].status in statuses]
    if q:
        needle = q.lower()
        # Without clearance, sensitive values are not searchable by their content.
        def hay(e: ExtractedValue) -> str:
            read = "" if red is not None and e.value_type in SENSITIVE_VALUE_TYPES else e.text_as_read
            return f"{e.id} {e.document_id} {e.field} {e.label} {read}".lower()

        items = [e for e in items if needle in hay(e)]
    if sort == "confidence":
        items = sorted(items, key=lambda e: (e.confidence, e.id))
    elif sort == "document":
        items = sorted(items, key=lambda e: (e.document_id, e.page, e.id))
    total = len(items)
    page = items[offset: offset + limit]
    _log_view(request, actor, "values", masked=red is not None,
              fields=sum(1 for e in page if e.value_type in SENSITIVE_VALUE_TYPES))
    return ValuesPage(total=total, offset=offset, limit=limit,
                      items=[_value_out(idx, e, red, _trace(request), request.app.state.review) for e in page])


@router.get("/values/{ev_id}", response_model=ValueOut)
def get_value(ev_id: str, request: Request,
              red: Optional[Redactor] = Depends(redactor_for),
              actor: Actor = Depends(current_actor)) -> ValueOut:
    idx = _idx(request)
    e = idx.values.get(ev_id)
    if e is None:
        raise HTTPException(404, f"No extracted value {ev_id}")
    _log_view(request, actor, ev_id, masked=red is not None, fields=int(e.value_type in SENSITIVE_VALUE_TYPES))
    return _value_out(idx, e, red, _trace(request), request.app.state.review)


@router.get("/versions", response_model=list[VersionSummary])
def versions(request: Request) -> list[VersionSummary]:
    idx = _idx(request)
    return [
        VersionSummary(
            version=v.version, computed_at=v.computed_at, trigger=v.trigger,
            is_current=v.version == idx.current_version, line_count=len(v.lines),
            asset_count=len(v.assets), diagnostic_count=len(v.diagnostics),
            documents_used=v.documents_used, documents_superseded=v.documents_superseded,
            summary=v.summary, summary_lines=summary_line_keys(v),
        )
        for v in idx.packet.return_versions
    ]


@router.get("/versions/{version}/lines", response_model=LinesPage)
def version_lines(
    version: str, request: Request,
    form: Optional[str] = None, q: Optional[str] = None,
    jurisdiction: Optional[str] = Query(None, pattern="^(federal|california)$"),
    changed: bool = False,
) -> LinesPage:
    idx = _idx(request)
    v = idx.versions.get(version)
    if v is None:
        raise HTTPException(404, f"No return version {version}")
    changes = {c.key: c for c in v.changes_from_previous}
    used_by = _trace(request).used_by[version]
    lines = v.lines
    forms = list(dict.fromkeys(ln.form for ln in lines))
    if form:
        lines = [ln for ln in lines if ln.form == form]
    if jurisdiction:
        lines = [ln for ln in lines if ln.jurisdiction == jurisdiction]
    if changed:
        lines = [ln for ln in lines if ln.key in changes]
    if q:
        tokens = q.lower().split()
        lines = [ln for ln in lines if all(t in f"{ln.key} {ln.label}".lower() for t in tokens)]
    adjusted = request.app.state.review.adjusted_values(version)
    rows = [
        LineRow(**ln.model_dump(), change=changes[ln.key].change if ln.key in changes else None,
                previous_value=changes[ln.key].old if ln.key in changes else None,
                used_by_count=len(used_by.get(ln.key, [])),
                adjusted_value=adjusted[ln.key]["value"] if ln.key in adjusted else None,
                adjustments=adjusted[ln.key]["adjustments"] if ln.key in adjusted else [])
        for ln in lines
    ]
    # Lines that exist only because an adjustment added them (e.g. a missing 8949 lot).
    for key, adj in adjusted.items():
        if adj["new_line"] and (not form or key.startswith(form + ".")) and (not q or q.lower() in f"{key} {adj['label']}".lower()):
            rows.append(LineRow(key=key, jurisdiction="federal" if not key.startswith(("F540NR", "SchCA540NR")) else "california",
                                form=key.split(".")[0], line=key.split(".", 1)[1], label=adj["label"], value=0, rule="ADJUSTMENT",
                                inputs=[], sources=[], note="Added by a workpaper adjustment", adjusted_value=adj["value"],
                                adjustments=adj["adjustments"]))
    return LinesPage(version=version, total=len(rows), forms=forms, items=rows)


@router.get("/lines/{key}", response_model=LineTrace)
def line_trace(key: str, request: Request, version: Optional[str] = None,
               red: Optional[Redactor] = Depends(redactor_for)) -> LineTrace:
    """Number -> evidence and number -> math for one return line."""
    out = _trace(request).line_trace(key, _version(request, version))
    if out is None:
        raise HTTPException(404, f"No line {key} in {version or _idx(request).current_version}")
    if red is not None:
        out = out.model_copy(update={"sources": [_redact_source(s, red) for s in out.sources]})
    return out


@router.get("/lines/{key}/graph", response_model=CalcGraph)
def line_graph(key: str, request: Request, version: Optional[str] = None,
               direction: str = Query("down", pattern="^(down|up)$")) -> CalcGraph:
    """Calculation subgraph: down = inputs closure (how it was built), up = consumers (where it goes)."""
    out = _trace(request).graph(key, _version(request, version), direction)  # type: ignore[arg-type]
    if out is None:
        raise HTTPException(404, f"No line {key}")
    return out


@router.get("/documents/{doc_id}/landing", response_model=DocumentLanding)
def document_landing(doc_id: str, request: Request, version: Optional[str] = None,
                     red: Optional[Redactor] = Depends(redactor_for)) -> DocumentLanding:
    """Reverse trace: every return line this document feeds, or why it feeds none."""
    if doc_id not in _idx(request).documents:
        raise HTTPException(404, f"No document {doc_id}")
    out = _trace(request).landing(doc_id, _version(request, version))
    if red is not None:
        out = out.model_copy(update={"mentions": [_redact_resolution(m, red) for m in out.mentions]})
    return out


@router.get("/resolve", response_model=RefResolution)
def resolve(request: Request, ref: str, version: Optional[str] = None,
            red: Optional[Redactor] = Depends(redactor_for),
            actor: Actor = Depends(current_actor)) -> RefResolution:
    res = _resolver(request).resolve(ref, version)
    if not res.found:
        raise HTTPException(404, res.label)
    masked = _redact_resolution(res, request.app.state.redactor)
    _log_view(request, actor, ref, masked=red is not None, fields=int(masked != res))
    return _redact_resolution(res, red)


@router.post("/resolve/batch", response_model=list[RefResolution])
def resolve_batch(body: ResolveBatchIn, request: Request,
                  red: Optional[Redactor] = Depends(redactor_for)) -> list[RefResolution]:
    r = _resolver(request)
    return [_redact_resolution(r.resolve(ref, body.version), red) for ref in body.refs[:1000]]


@public.get("/actors", response_model=list[Actor])
def actors(request: Request) -> list[Actor]:
    return list(request.app.state.actors.values())


@public.get("/me", response_model=Actor)
def me(actor: Actor = Depends(current_actor)) -> Actor:
    return actor


@router.get("/search", response_model=SearchResults)
def search(request: Request, q: str = Query(..., min_length=1, max_length=200),
           limit: int = Query(6, ge=1, le=25),
           red: Optional[Redactor] = Depends(redactor_for), actor: Actor = Depends(current_actor)) -> SearchResults:
    res = run_search(_idx(request), _resolver(request), q, limit, red)
    res.groups += search_workpaper(request.app.state, actor, q, limit)
    if res.exact is not None:
        res.exact = _redact_resolution(res.exact, red)
    return res
