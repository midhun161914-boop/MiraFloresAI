// Filing-lifecycle types — generated, not hand-written. The backend declares each
// document as a strict Pydantic model (backend/app/api/lifecycle_schemas.py, extra
// keys forbidden), `npm run gen:api` turns the OpenAPI schema into schema.d.ts, and
// these are just short names for those generated types.
import type { components } from "./schema";

type S = components["schemas"];
export type Figures = S["Figures"];
export type Gate = S["Gate"];
export type GateItem = S["GateItem"];
export type DiligenceItem = S["DiligenceItem"];
export type Submission = S["Submission"];
export type TinCheck = S["TinCheck"];
export type Filing = S["Filing"];
export type ExtensionView = S["ExtensionView"];
export type FiledReturn = S["FiledReturn"];
export type AmendRow = S["AmendRow"];
export type Amendment = S["Amendment"];
export type EvidenceRec = S["EvidenceRec"];
export type LineRec = S["LineRec"];
export type NoticeItem = S["NoticeItem"];
export type NoticeResponse = S["NoticeResponse"];
export type Notice = S["Notice"];
export type CarryRow = S["CarryRow"];
export type CarryForward = S["CarryForward"];
export type ClientFiling = S["ClientFiling"];
export type DiligenceRecord = S["DiligenceRecord"];
// status + time
export type Status = S["Status"];
export type Budget = S["Budget"];
export type TimeEntry = S["TimeEntry"];
export type BucketRow = S["BucketRow"];
