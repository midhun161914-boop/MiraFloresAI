// Typed API client. All types come from schema.d.ts, which is generated from the
// FastAPI/Pydantic OpenAPI schema (`npm run gen:api`) — one source of truth.
import type { components } from "./schema";
import type * as L from "./lifecycle";

type S = components["schemas"];
export type Overview = S["Overview"];
export type DocumentSummary = S["DocumentSummary"];
export type DocumentDetail = S["DocumentDetail"];
export type ValueOut = S["ValueOut"];
export type ValuesPage = S["ValuesPage"];
export type RefResolution = S["RefResolution"];
export type VersionSummary = S["VersionSummary"];
export type ReturnLine = S["ReturnLine"];
export type Position = S["Position"];
export type MatchStatus = S["TextMatchOut"]["status"];
export type Actor = S["Actor"];
export type SearchResults = S["SearchResults"];
export type SearchHit = S["SearchHit"];
export type LineTrace = S["LineTrace"];
export type TraceSource = S["TraceSource"];
export type LineBrief = S["LineBrief"];
export type CalcGraph = S["CalcGraph"];
export type GraphNode = S["GraphNode"];
export type DocumentLanding = S["DocumentLanding"];
export type LandingStatus = DocumentLanding["status"];
export type LinesPage = S["LinesPage"];
export type LineRow = S["LineRow"];
export type NodeReview = S["NodeReview"];
export type Verification = S["Verification"];
export type Note = S["Note"];
export type SignOff = S["SignOff"];
export type Correction = S["Correction"];
export type NodeSummary = S["NodeSummary"];
export type Readiness = S["Readiness"];
export type Queue = S["Queue"];
export type EventOut = S["EventOut"];
export type EventsPage = S["EventsPage"];
export type ClientHome = S["ClientHome"];
export type Level = "preparer" | "reviewer" | "partner";
export type Health = S["Health"];
export type AreaSummary = S["AreaSummary"];
export type CheckRun = S["CheckRun"];
export type CheckResult = S["CheckResult"];
export type Finding = S["Finding"];
export type TaxEffect = S["TaxEffect"];
export type VarianceReport = S["VarianceReport"];
export type VarianceFlag = S["VarianceFlag"];
export type OutsideFiling = S["OutsideFiling"];
export type Adjustment = S["Adjustment"];
export type StateRef = S["StateRef"];
export type Compare = S["Compare"];
export type LineDiff = S["LineDiff"];
export type Estimate = S["Estimate"];
export type EstimateItem = S["EstimateItem"];
export type Digest = S["Digest"];
export type BulkResult = S["BulkResult"];
export type BulkSummary = S["BulkSummary"];
export type Fix = S["Fix"];

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

// The acting user (role switcher). Sent on every request; the server decides
// what this actor may see. Set by SessionProvider.
let actorId: string | null = null;
export function setActorHeader(id: string | null) {
  actorId = id;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(actorId ? { "X-Actor-Id": actorId } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    let code: string | undefined;
    try {
      const body = await res.json();
      // Rule refusals come back as {code, message}: show the firm rule verbatim.
      if (body.detail && typeof body.detail === "object" && "message" in body.detail) {
        detail = body.detail.message;
        code = body.detail.code;
      } else {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail, code);
  }
  return res.json() as Promise<T>;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export interface ValuesQuery {
  document_id?: string;
  value_type?: string;
  q?: string;
  max_confidence?: number;
  match?: string;
  sort?: "id" | "confidence" | "document";
  offset?: number;
  limit?: number;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}

export const api = {
  overview: () => request<Overview>("/api/overview"),
  actors: () => request<Actor[]>("/api/actors"),
  documents: () => request<DocumentSummary[]>("/api/documents"),
  document: (id: string) => request<DocumentDetail>(`/api/documents/${encodeURIComponent(id)}`),
  values: (q: ValuesQuery) => request<ValuesPage>(`/api/values${qs({ ...q })}`),
  search: (q: string, limit = 6) => request<SearchResults>(`/api/search${qs({ q, limit })}`),
  lines: (version: string, q: { form?: string; q?: string; jurisdiction?: string; changed?: boolean } = {}) =>
    request<LinesPage>(`/api/versions/${encodeURIComponent(version)}/lines${qs({ ...q, changed: q.changed ? "true" : undefined })}`),
  lineTrace: (key: string, version?: string) =>
    request<LineTrace>(`/api/lines/${encodeURIComponent(key)}${qs({ version })}`),
  lineGraph: (key: string, direction: "down" | "up", version?: string) =>
    request<CalcGraph>(`/api/lines/${encodeURIComponent(key)}/graph${qs({ version, direction })}`),
  // ---- review layer: every write is an event; refusals come back as ApiError(403/409)
  review: (node: string, version?: string) => request<NodeReview>(`/api/review/node${qs({ node, version })}`),
  methods: () => request<string[]>("/api/review/methods"),
  reviewSummary: (version?: string) => request<Record<string, NodeSummary>>(`/api/review/summary${qs({ version })}`),
  queue: () => request<Queue>("/api/review/queue"),
  readiness: () => request<Readiness>("/api/review/readiness"),
  events: (q: { since?: number; node?: string; type?: string; limit?: number; actor_id?: string } = {}) =>
    request<EventsPage>(`/api/events${qs(q)}`),
  verify: (node: string, method: string, note: string, version?: string) =>
    post<Verification>("/api/review/verify", { node, method, note, version }),
  withdrawVerification: (id: string) => post<Verification>(`/api/review/verifications/${id}/withdraw`, {}),
  openNote: (node: string, text: string, blocking: boolean, version?: string) =>
    post<Note>("/api/review/notes", { node, text, blocking, version }),
  noteAction: (id: string, action: "reply" | "resolve" | "reopen", text: string, expected_seq?: number) =>
    post<Note>(`/api/review/notes/${id}/${action}`, { text, expected_seq }),
  signoff: (node: string, level: Level, expected_fingerprint?: string, version?: string) =>
    post<SignOff>("/api/review/signoffs", { node, level, expected_fingerprint, version }),
  withdrawSignoff: (id: string) => post<SignOff>(`/api/review/signoffs/${id}/withdraw`, {}),
  correct: (ev: string, to: unknown, reason: string) => post<Correction>("/api/review/corrections", { ev, to, reason }),
  revertCorrection: (ev: string, reason: string) => post<Correction>(`/api/review/corrections/${ev}/revert`, { reason }),
  // ---- return health
  returnHealth: () => request<Health>("/api/return-health"),
  checks: () => request<CheckRun>("/api/checks"),
  variance: () => request<VarianceReport>("/api/variance"),
  disposition: (id: string, disposition: "resolved" | "accepted" | "not_an_issue" | "reopened", note: string) =>
    post<Record<string, unknown>>(`/api/findings/${encodeURIComponent(id)}/disposition`, { disposition, note }),
  explainVariance: (line: string, text: string) =>
    post<Record<string, unknown>>(`/api/variance/${encodeURIComponent(line)}/explain`, { text }),
  // ---- change & versions
  adjustments: () => request<Adjustment[]>("/api/adjustments"),
  proposeAdjustment: (body: { title?: string; reason: string; changes: { key: string; to_value: number; label?: string }[]; finding_id?: string }) =>
    post<Adjustment>("/api/adjustments", body),
  adjustFromFinding: (findingId: string, reason: string) =>
    post<Adjustment>(`/api/adjustments/from-finding/${encodeURIComponent(findingId)}`, { reason }),
  decideAdjustment: (id: string, kind: "approve" | "reject" | "reverse", note: string) =>
    post<Adjustment>(`/api/adjustments/${id}/${kind}`, { note }),
  states: () => request<StateRef[]>("/api/states"),
  saveState: (name: string) => post<Record<string, unknown>>("/api/states", { name }),
  compare: (a: string, b: string) => request<Compare>(`/api/compare${qs({ a, b })}`),
  whatif: () => request<{ alternatives: Record<string, unknown>[]; extension: Record<string, unknown> }>("/api/whatif"),
  estimate: (items: EstimateItem[]) => post<Estimate>("/api/whatif/estimate", { items }),
  digest: () => request<Digest>("/api/digest"),
  markSeen: (seq?: number) => post<{ last_seen_seq: number }>("/api/digest/seen", { seq }),
  bulkVerify: (nodes: string[], method: string, note: string) => post<BulkResult>("/api/bulk/verify", { nodes, method, note }),
  bulkDisposition: (finding_ids: string[], disposition: "resolved" | "accepted" | "not_an_issue", note: string) =>
    post<BulkResult>("/api/bulk/disposition", { finding_ids, disposition, note }),
  bulks: () => request<BulkSummary[]>("/api/bulk"),
  undoBulk: (id: string) => post<BulkResult>(`/api/bulk/${id}/undo`, {}),
  // ---- filing & after
  filing: () => request<L.Filing>("/api/filing"),
  gate: () => request<L.Gate>("/api/filing/gate"),
  extension: () => request<L.ExtensionView>("/api/filing/extension"),
  fileExtension: (note: string) => post<L.ExtensionView>("/api/filing/extension", { note }),
  diligence: (item: string, answers: Record<string, boolean>, note: string) => post<unknown>(`/api/filing/diligence/${item}`, { answers, note }),
  present: (note: string) => post<L.Filing>("/api/filing/present", { note }),
  eroSign: (note: string) => post<L.Filing>("/api/filing/ero-sign", { note }),
  transmit: () => post<L.Filing>("/api/filing/transmit", {}),
  correctIdentity: (person: string, evidence: string, reason: string) => post<L.Filing>("/api/filing/identity", { person, evidence, reason }),
  filedReturn: () => request<L.FiledReturn>("/api/filing/filed"),
  amendments: () => request<L.Amendment[]>("/api/amendments"),
  openAmendment: (reason: string) => post<L.Amendment>("/api/amendments", { reason }),
  amendLine: (id: string, key: string, to_value: number, reason: string) => post<L.Amendment>(`/api/amendments/${id}/lines`, { key, to_value, reason }),
  removeAmendLine: (id: string, key: string) => request<L.Amendment>(`/api/amendments/${id}/lines/${encodeURIComponent(key)}`, { method: "DELETE" }),
  amendFromFinding: (id: string, finding: string, reason: string) => post<L.Amendment>(`/api/amendments/${id}/from-finding/${encodeURIComponent(finding)}`, { reason }),
  approveAmendment: (id: string, note: string) => post<L.Amendment>(`/api/amendments/${id}/approve`, { note }),
  notices: () => request<L.Notice[]>("/api/notices"),
  assembleResponse: (id: string) => post<L.NoticeResponse>(`/api/notices/${id}/assemble`, {}),
  responseSent: (id: string, note: string) => post<L.NoticeResponse>(`/api/notices/${id}/sent`, { note }),
  carryforward: () => request<L.CarryForward>("/api/carryforward"),
  rollForward: (note: string) => post<L.CarryForward>("/api/carryforward/roll", { note }),
  status: () => request<L.Status>("/api/status"),
  budget: () => request<L.Budget>("/api/budget"),
  logTime: (bucket: string, hours: number, date: string, note: string) => post<L.TimeEntry>("/api/time", { bucket, hours, date, note }),
  voidTime: (id: string) => post<L.TimeEntry>(`/api/time/${id}/void`, {}),
  clientFiling: () => request<L.ClientFiling>("/api/client/filing"),
  clientApprove: (pin: string, agree: boolean) => post<L.ClientFiling>("/api/client/filing/approve", { pin, agree }),
  clientHome: () => request<ClientHome>("/api/client/home"),
  landing: (docId: string, version?: string) =>
    request<DocumentLanding>(`/api/documents/${encodeURIComponent(docId)}/landing${qs({ version })}`),
  resolve: (ref: string, version?: string) =>
    request<RefResolution>(`/api/resolve${qs({ ref, version })}`),
  resolveBatch: (refs: string[], version?: string) =>
    request<RefResolution[]>("/api/resolve/batch", {
      method: "POST",
      body: JSON.stringify({ refs, version }),
    }),
};
