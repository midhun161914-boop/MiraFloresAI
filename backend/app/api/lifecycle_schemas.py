"""Response models for the filing-lifecycle endpoints.

The lifecycle service assembles these documents from the event log as dicts. Every
model here forbids extra keys, so a field added on the backend without being declared
fails response validation in the tests — and the frontend types are generated from
these models (``npm run gen:api``), so front and back cannot drift silently."""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from app.services.review import Note as RecNote, SignOff as RecSignoff, Verification as RecVerification

Num = Union[int, float]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Who(Strict):
    actor: str
    actor_name: str
    at: str
    seq: int


# ------------------------------------------------------------------ figures + extension
class JurisdictionFigures(Strict):
    agi: Num
    total_tax: Num
    payments: Num
    balance_due: Num


class Figures(Strict):
    federal: JurisdictionFigures
    california: JurisdictionFigures
    adjustments: list[str]
    basis: str


class ExtFederal(Strict):
    estimated_total_tax: Num
    payments: Num
    estimated_balance: Num
    paid_with_form_4868: Num
    rule: str
    recomputed_payment: Num


class ExtCalifornia(Strict):
    estimated_total_tax: Num
    payments: Num
    estimated_balance: Num
    paid_with_ftb_3519: Num
    rule: str
    recomputed_payment: Num


class ExtensionEstimate(Strict):
    source: str
    computed_at: str
    based_on_version: str
    federal: ExtFederal
    california: ExtCalifornia
    extended_due: Optional[str]
    note: str
    filed: None = None


class ExtensionRecord(Who):
    forms: list[str]
    federal_payment: Num
    california_payment: Num
    based_on_version: str
    estimate: ExtensionEstimate
    extended_due: Optional[str]
    note: str
    source: str


class ExtensionView(Strict):
    source: str
    computed_at: str
    based_on_version: str
    federal: ExtFederal
    california: ExtCalifornia
    extended_due: Optional[str]
    note: str
    filed: Optional[ExtensionRecord]


# ------------------------------------------------------------------ gate
class GateItem(Strict):
    kind: str
    title: str
    detail: str = ""
    node: Optional[str] = None
    ref_id: Optional[str] = None
    link: Optional[str] = None


class GateStep(Strict):
    step: str
    status: Literal["done", "open"]
    detail: str


class Gate(Strict):
    clear: bool
    blockers: list[GateItem]
    steps: list[GateStep]


# ------------------------------------------------------------------ filing
class Presented(Who):
    figures: Figures
    fingerprint: str
    note: str
    as_of_seq: int


class Approval(Who):
    form: str
    role: str
    fingerprint: Optional[str]
    figures: Optional[Figures]


class Signer(Strict):
    id: str
    name: str
    approval: Optional[Approval]


class EroSignature(Who):
    efin: str
    note: str
    fingerprint: str


class AgencyError(Strict):
    code: str
    message: str


class TinMatch(Strict):
    person: str
    match: bool


class AgencyResponse(Who):
    submission_id: str
    jurisdiction: Literal["federal", "california"]
    status: str
    errors: list[AgencyError]
    agency_date: str
    source: str
    tin_checks: list[TinMatch]


class Transmitted(Who):
    pass


class Submission(Strict):
    id: str
    jurisdiction: Literal["federal", "california"]
    attempt: int
    transmitted: Transmitted
    status: str
    response: Optional[AgencyResponse]
    fingerprint: Optional[str]


class TinEvidence(Strict):
    document_id: str
    ev: str
    ssn: Optional[str]


class TinCheck(Strict):
    person: str
    name: str
    on_return: Optional[str]
    ssa: Optional[str]
    evidence: Optional[TinEvidence]
    match: bool


class IdentityCorrection(Who):
    person: str
    field: str
    to: Optional[str]
    evidence: str
    document_id: str
    reason: str
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: Optional[str] = Field(None, alias="from")   # "from" is a Python keyword


class FiledSummary(Who):
    accepted_at: str
    submissions: dict[str, str]
    snapshot_hash: str


class Interest(Strict):
    balance_due: Num
    paid: Optional[str] = None
    days_late: Optional[int] = None
    interest: Num
    penalty: Num
    basis: Optional[str] = None
    note: Optional[str] = None


class DiligenceRecord(Who):
    item: str
    answers: dict[str, bool]
    note: str
    refs: list[str]
    form: str


class DiligenceItem(Strict):
    id: str
    label: str
    line: Optional[str]
    claimed: bool
    value: Union[Num, str, None]
    status: Literal["complete", "required", "not_applicable"]
    record: Optional[DiligenceRecord]


class Filing(Strict):
    stage: Literal["preparing", "presented", "authorized", "transmitted", "filed"]
    figures: Figures
    fingerprint: str
    presented: Optional[Presented]
    presented_current: bool
    signers: list[Signer]
    ero: Optional[EroSignature]
    ero_signer: str
    submissions: list[Submission]
    tin_checks: list[TinCheck]
    identity: dict[str, list[IdentityCorrection]]
    filed: Optional[FiledSummary]
    interest: Optional[Interest]
    diligence: list[DiligenceItem]
    diligence_questions: list[str]
    extension: Optional[ExtensionRecord]


class FiledLine(Strict):
    key: str
    label: str
    form: str
    value: Union[Num, str, None]
    engine_value: Union[Num, str, None]


class FiledReturn(Strict):
    accepted_at: str
    submissions: dict[str, str]
    snapshot_hash: str
    figures: Figures
    adjustments: list[str]
    as_of_seq: int
    version: str
    lines: list[FiledLine]
    intact: bool


class ClientFiling(Strict):
    presented: bool
    current: bool
    figures: Optional[Figures]
    presented_at: Optional[str]
    you_signed: bool
    signed_at: Optional[str]
    others_signed: list[str]
    filed: bool
    accepted_at: Optional[str]


# ------------------------------------------------------------------ amendments
class LineTaxEffect(Strict):
    category: str
    change: Num
    federal_tax: Num
    california_tax: Num
    federal_balance_due: Num
    california_balance_due: Num
    basis: str
    bound: str


class AmendRow(Strict):
    key: str
    label: str
    as_filed: Union[Num, str, None]
    net_change: Num
    corrected: Num
    reason: str
    refs: list[str]
    finding_id: Optional[str]
    actor_name: str
    at: str
    tax_effect: LineTaxEffect


class AmendHistory(Who):
    kind: str
    note: str


class AmendEffect(Strict):
    federal_balance_due: Num
    california_balance_due: Num
    basis: str


class Amendment(Strict):
    id: str
    status: Literal["draft", "approved", "filed"]
    reason: str
    actor_name: str
    at: str
    base_snapshot: str
    intact_base: bool
    rows: list[AmendRow]
    history: list[AmendHistory]
    effect: AmendEffect
    as_filed: Optional[Figures]
    requires_partner: bool


# ------------------------------------------------------------------ notices
class EvidencePosition(Strict):
    x0: float
    y0: float
    x1: float
    y1: float


class EvidenceRec(Strict):
    ev: str
    document_id: str
    document: str
    issuer: str
    page: int
    position: EvidencePosition
    field: str
    label: str
    value: Union[Num, str, bool, None]
    text_as_read: str
    effective: Union[Num, str, bool, None]
    correction: Optional[dict[str, object]]
    confidence: float
    direct: bool
    verifications: list[RecVerification]


class RecAdjustment(Strict):
    id: str
    title: str
    reason: str
    approved_by: Optional[str]


class LineRec(Strict):
    key: str
    label: str
    as_filed: Union[Num, str, None]
    engine_value: Union[Num, str, None]
    rule: Optional[str]
    inputs: list[str]
    evidence: list[EvidenceRec]
    verifications: list[RecVerification]
    signoffs: list[RecSignoff]
    notes: list[RecNote]
    adjustments: list[RecAdjustment]


class BridgeRow(Strict):
    label: str
    amount: Num


class Reconciliation(Strict):
    reported: Num
    irs_1099_nec: Num
    irs_1099_k: Num
    books_revenue: Num
    file_1099_nec: Num
    file_1099_k: Num
    by_document: dict[str, Num]
    bridge: list[BridgeRow]
    bridge_total: Num
    file_agrees_with_irs: bool
    engine_rule: Optional[str]
    observation: Optional[str]


class NoticeDoc(Strict):
    id: str
    title: str
    issuer: str
    pages: int


class NoticeItem(Strict):
    index: int
    question: str
    lines: list[LineRec]
    reconciliation: Optional[Reconciliation] = None
    documents: list[NoticeDoc]
    gaps: list[str]


class NoticeBase(Strict):
    id: str
    agency: str
    type: str
    tax_year: int
    dated: str
    response_due: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    document: str
    items_under_examination: Optional[list[str]] = None


class RecordFiled(Strict):
    accepted_at: str
    submissions: dict[str, str]
    snapshot_hash: str


class Firm(Strict):
    name: str
    address: str


class ResponseRecord(Strict):
    notice: NoticeBase
    household: str
    tax_year: int
    filed: RecordFiled
    items: list[NoticeItem]
    firm: Firm
    assembled_by: str


class SentRecord(Who):
    notice_id: str
    note: str


class NoticeResponse(Who):
    notice_id: str
    record: ResponseRecord
    record_hash: str
    as_of_seq: int
    sent: Optional[SentRecord]


class Notice(NoticeBase):
    index: int
    response: Optional[NoticeResponse]


# ------------------------------------------------------------------ carry forward
class HistoryPoint(Strict):
    version: str
    value: Optional[Num]


class CarryRow(Strict):
    key: str
    label: str
    into_2025: Optional[Num]
    out_2026: Optional[Num]
    jurisdiction: Literal["federal", "california"]
    used_2025: Optional[Num] = None
    history: Optional[list[HistoryPoint]] = None
    changes: Optional[list[str]] = None


class Installment(Strict):
    due: str
    amount: Num


class EstimatePlan(Strict):
    rule: str
    basis_2025_tax: Num
    safe_harbor_total: Num
    installments: list[Installment]
    caveat: Optional[str] = None


class Planning(Strict):
    known_changes: list[str]
    estimates: dict[Literal["federal", "california"], EstimatePlan]
    basis: str


class AmendRef(Strict):
    id: str
    status: str


class Rolled(Who):
    tax_year: int
    from_snapshot: Optional[str]
    carryovers: dict[str, Optional[Num]]
    history: dict[str, Optional[list[HistoryPoint]]]
    planning: Planning
    note: str


class CarrySources(Strict):
    into_2025: Optional[str]
    out: str


class CarryForward(Strict):
    filed_version: str
    filed: bool
    federal: list[CarryRow]
    california: list[CarryRow]
    sources: CarrySources
    amendments: list[AmendRef]
    planning: Planning
    rolled: Optional[Rolled]
