"""Global search behind the top bar.

One query returns: an exact reference hit (anything ``resolve_ref`` accepts),
then grouped matches across documents, return lines (current version),
extracted values and client answers/messages. Every token must match (AND),
and identifier-prefix matches rank first, so "D3" lists D30-D39 before titles
that merely contain "d3".
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional, TypeVar

from pydantic import BaseModel

from app.services.loader import PacketIndex
from app.services.redact import SENSITIVE_VALUE_TYPES, Redactor
from app.services.refs import RefResolution, RefResolver

T = TypeVar("T")


class SearchHit(BaseModel):
    kind: str
    id: str
    label: str
    sublabel: Optional[str] = None
    link: str


class SearchGroup(BaseModel):
    kind: str
    label: str
    total: int
    items: list[SearchHit]


class SearchResults(BaseModel):
    query: str
    exact: Optional[RefResolution] = None
    groups: list[SearchGroup]


def _rank(items: Iterable[T], tokens: list[str], ident: Callable[[T], str],
          haystack: Callable[[T], str]) -> list[T]:
    scored = []
    for it in items:
        hay = haystack(it).lower()
        if all(t in hay for t in tokens):
            ident_l = ident(it).lower()
            score = 0 if ident_l == tokens[0] else 1 if ident_l.startswith(tokens[0]) else 2
            scored.append((score, ident_l, it))
    scored.sort(key=lambda s: (s[0], s[1]))
    return [s[2] for s in scored]


def search(idx: PacketIndex, resolver: RefResolver, q: str, limit: int = 6,
           redactor: Optional[Redactor] = None) -> SearchResults:
    q = q.strip()
    tokens = [t for t in q.lower().split() if t]
    if not tokens:
        return SearchResults(query=q, groups=[])

    exact = resolver.resolve(q)
    groups: list[SearchGroup] = []
    show = (lambda s: redactor.text(s)) if redactor else (lambda s: s)

    docs = _rank(
        idx.packet.documents, tokens, lambda d: d.id,
        lambda d: f"{d.id} {d.title} {d.issuer} {d.document_type} {d.file_name}",
    )
    groups.append(SearchGroup(kind="document", label="Documents", total=len(docs), items=[
        SearchHit(kind="document", id=d.id, label=d.title, sublabel=f"{d.id} · {d.issuer}",
                  link=f"/documents/{d.id}")
        for d in docs[:limit]
    ]))

    cur = idx.current
    lines = _rank(cur.lines, tokens, lambda ln: ln.key, lambda ln: f"{ln.key} {ln.label}")
    groups.append(SearchGroup(kind="return_line", label=f"Return lines ({cur.version})", total=len(lines), items=[
        SearchHit(kind="return_line", id=ln.key, label=f"{ln.key} · {ln.label}",
                  sublabel=f"{ln.value:,}" if isinstance(ln.value, (int, float)) else str(ln.value),
                  link=f"/lines/{ln.key}")
        for ln in lines[:limit]
    ]))

    values = [e for e in idx.packet.extracted_values
              if not (redactor and e.value_type in SENSITIVE_VALUE_TYPES)]
    vals = _rank(values, tokens, lambda e: e.id,
                 lambda e: f"{e.id} {e.document_id} {e.field} {e.label} {e.text_as_read}")
    groups.append(SearchGroup(kind="extracted_value", label="Extracted values", total=len(vals), items=[
        SearchHit(kind="extracted_value", id=e.id, label=f"{e.label}: {show(e.text_as_read) or '(blank)'}",
                  sublabel=f"{e.id} · {e.document_id} p.{e.page}",
                  link=f"/documents/{e.document_id}?page={e.page}&ev={e.id}")
        for e in vals[:limit]
    ]))

    client = idx.packet.client
    answers = [(q_.id, q_.question, q_.answer) for q_ in client.questionnaire] + \
              [(m.id, f"Message from {m.from_}", m.text) for m in client.messages]
    hits = _rank(answers, tokens, lambda a: a[0], lambda a: f"{a[0]} {a[1]} {a[2]}")
    groups.append(SearchGroup(kind="client", label="Client answers & messages", total=len(hits), items=[
        SearchHit(kind="client", id=a[0], label=f"{a[0]} · {a[1]}", sublabel=show(a[2])[:120],
                  link=f"/ref?r={a[0]}")
        for a in hits[:limit]
    ]))

    return SearchResults(query=q, exact=exact if exact.found else None,
                         groups=[g for g in groups if g.total])


# ------------------------------------------------------------------ workpaper search
SCREENS = [
    ("/status", "Return status", "status stage blockers owners outstanding overview"),
    ("/", "Return health", "home health areas"),
    ("/return", "Return lines", "return lines form 1040 540nr"),
    ("/documents", "Documents", "documents source pdf"),
    ("/values", "Extracted values", "values extraction fields"),
    ("/findings", "Checks & findings", "checks findings errors warnings diagnostics"),
    ("/variance", "Variance vs 2024", "variance prior year"),
    ("/adjustments", "Adjustments", "adjustments partner"),
    ("/compare", "Compare versions", "compare diff versions v1 v2 v3"),
    ("/whatif", "What-ifs", "what if scenario estimate"),
    ("/filing", "Filing", "filing gate 8879 efile extension reject transmit sign approve"),
    ("/amend", "Amendments", "amend amendment 1040-x"),
    ("/notices", "Agency notices", "notice letter 566 irs ftb exam"),
    ("/carryforward", "Carry forward & 2026", "carryover carry forward 2026 estimates planning"),
    ("/budget", "Time & budget", "time budget hours log"),
    ("/review", "Review queue", "review notes sign-offs queue"),
    ("/activity", "Activity & view log", "activity audit events log"),
    ("/whats-new", "What's new", "digest new since"),
]


def _event_link(node: Optional[str], type_: str) -> str:
    if node and (node.startswith("ev-") or (len(node) == 3 and node[0] == "D" and node[1:].isdigit())):
        return f"/ref?r={node}"
    if node and "." in node and not node.startswith("household:"):
        return f"/lines/{node}"
    return f"/activity?type={type_.split('.')[0]}."


def search_workpaper(state: Any, actor: Any, q: str, limit: int = 6) -> list[SearchGroup]:
    """Findings, adjustments, notices, people, events and screens — the workpaper's own
    objects, on top of the packet search above. People never expose identifiers."""
    tokens = [t for t in q.lower().split() if t]
    if not tokens:
        return []
    groups: list[SearchGroup] = []

    def group(kind: str, label: str, ranked: list[Any], hit: Callable[[Any], SearchHit]) -> None:
        if ranked:
            groups.append(SearchGroup(kind=kind, label=label, total=len(ranked), items=[hit(x) for x in ranked[:limit]]))

    findings = state.health.checks().findings
    group("finding", "Findings", _rank(findings, tokens, lambda f: f.code,
                                       lambda f: f"{f.code} {f.title} {f.summary} {' '.join(f.lines)} {f.check_id} {f.area}"),
          lambda f: SearchHit(kind="finding", id=f.id, label=f.title, sublabel=f"{f.severity} · {f.status.replace('_', ' ')} · {f.code}",
                              link=f"/findings?status=all&q={f.id}"))
    adjs = list(state.review.adjustments.values())
    group("adjustment", "Adjustments", _rank(adjs, tokens, lambda a: a["id"],
                                             lambda a: f"{a['id']} {a['title']} {a['reason']} {' '.join(c['key'] for c in a['changes'])}"),
          lambda a: SearchHit(kind="adjustment", id=a["id"], label=f"{a['id']} · {a['title']}",
                              sublabel=a["status"].replace("_", " "), link="/adjustments"))
    notices = state.lifecycle.notices()
    group("notice", "Agency notices", _rank(notices, tokens, lambda n: n["id"],
                                            lambda n: f"{n['id']} {n['agency']} {n['type']} {n.get('summary', '')} {' '.join(n.get('items_under_examination') or [])}"),
          lambda n: SearchHit(kind="notice", id=n["id"], label=f"{n['agency']} {n['type']}", sublabel=f"tax year {n['tax_year']} · {n['dated']}",
                              link="/notices"))
    p = state.index.packet
    people = [(x["id"], x["name"], x.get("role", ""), x.get("relationship") or x.get("occupation") or "", "household")
              for x in state.index.raw["household"]["people"]]
    people += [(s.id, s.name, s.role, s.credential or "", "staff") for s in p.firm.staff]
    people += [(c.id, c.name, "client user", "", "client") for c in p.firm.client_users]
    group("person", "People", _rank(people, tokens, lambda x: x[1], lambda x: f"{x[0]} {x[1]} {x[2]} {x[3]}"),
          lambda x: SearchHit(kind="person", id=x[0], label=x[1], sublabel=f"{x[2].replace('_', ' ')}{' · ' + x[3] if x[3] else ''}",
                              link=f"/activity?actor={x[0]}" if x[4] != "household" else f"/documents?q={x[1].split()[0]}"))
    events = state.events.query(limit=3000)
    names = state.review.name
    skip = {"view.logged", "user.seen"}
    evs = [e for e in events if e.type not in skip]
    group("event", "Activity", _rank(evs, tokens, lambda e: e.type,
                                     lambda e: f"{e.type} {e.node or ''} {names(e.actor)} {' '.join(str(v) for k, v in e.payload.items() if isinstance(v, (str, int, float)) and k not in ('pin_hash', 'from', 'to', 'record'))}"),
          lambda e: SearchHit(kind="event", id=str(e.seq), label=f"#{e.seq} {e.type} · {names(e.actor)}",
                              sublabel=(e.node or "") + (f" · {e.at[:16].replace('T', ' ')}"), link=_event_link(e.node, e.type)))
    group("screen", "Screens", _rank(SCREENS, tokens, lambda s: s[1], lambda s: f"{s[1]} {s[2]}"),
          lambda s: SearchHit(kind="screen", id=s[0], label=s[1], sublabel="Go to screen", link=s[0]))
    return groups
