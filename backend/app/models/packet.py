"""Pydantic v2 models for the Okafor-Lindqvist 2025 data packet.

Design notes
------------
* The packet is read-only pipeline output. Every model is frozen so nothing
  downstream can mutate it by accident.
* The parts the workpaper reasons about (documents, extracted values, return
  versions, lines, assets, diagnostics, firm, client, timeline) are modelled
  strictly with ``extra="forbid"``: if the pipeline adds or renames a field, load
  fails loudly instead of the UI silently showing stale data (schema-drift guard).
* Loosely structured reference material (readme prose, engine parameters,
  prior-year line dictionaries, planning text) is kept as typed dicts.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

# Whole dollars stay ints (no "212400.0" in the UI); cents/ratios stay floats.
Num = Union[int, float]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Loose(BaseModel):
    """For sections whose exact shape is reference material, not logic input."""

    model_config = ConfigDict(extra="allow", frozen=True)


# --------------------------------------------------------------------------- #
# packet / readme
# --------------------------------------------------------------------------- #
class PacketInfo(Strict):
    name: str
    version: str
    generated: str
    client_id: str


class Readme(Strict):
    what_this_is: str
    all_data_is_invented: str
    truth_and_mistakes: str
    no_page_images: str
    engine_and_recomputing: str
    where_now_is: str
    reference_formats: dict[str, str]
    sections: dict[str, str]
    form_codes: str


# --------------------------------------------------------------------------- #
# household
# --------------------------------------------------------------------------- #
class Person(Strict):
    id: str
    role: Literal["taxpayer", "spouse", "dependent"]
    name: str
    ssn: str
    dob: str
    occupation: Optional[str] = None
    ip_pin: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    relationship: Optional[str] = None
    months_lived_with_you: Optional[int] = None
    full_time_student: Optional[bool] = None
    note: Optional[str] = None
    own_income: Optional[str] = None


class Address(Strict):
    from_: str = Field(alias="from")
    to: Optional[str]
    address: str
    type: str


class Residency(Strict):
    state: str
    from_: str = Field(alias="from")
    to: str
    status: str


class BankAccount(Strict):
    routing: str
    account: str
    type: str
    bank: str


class RelatedReturn(Strict):
    who: str
    return_: str = Field(alias="return")
    prepared_by: str
    in_this_packet: Union[bool, str]


class Household(Strict):
    filing_status: str
    tax_year: int
    entered_by: str
    people: list[Person]
    addresses: list[Address]
    residency: list[Residency]
    bank_account_for_refund_or_payment: BankAccount
    prior_year_agi_for_esignature: int
    related_returns: list[RelatedReturn]


# --------------------------------------------------------------------------- #
# documents + extracted values
# --------------------------------------------------------------------------- #
class Page(Strict):
    page: int
    printed_content: str


class Extraction(Strict):
    status: Literal["extracted", "partial", "not_extracted"]
    values: int
    reason: Optional[str]


class Document(Strict):
    id: str
    title: str
    document_type: str
    issuer: str
    belongs_to: str  # taxpayer | spouse | joint | dependent:<id>
    tax_year: int
    received_at: str
    uploaded_by: Literal["client", "firm"]
    file_name: str
    page_count: int
    pages: list[Page]
    extraction: Extraction
    marked_corrected: bool = False


class Position(Strict):
    """Synthetic page fractions from the top-left. Only used to place highlights."""

    x0: float
    y0: float
    x1: float
    y1: float


ValueType = Literal[
    "money", "date", "text", "integer", "quantity", "percent",
    "boolean", "code", "ssn", "ein", "account_number",
]


class ExtractedValue(Strict):
    id: str
    document_id: str
    page: int
    field: str
    label: str
    value: Union[bool, int, float, str, None]
    value_type: ValueType
    text_as_read: str
    position: Position
    confidence: float = Field(ge=0, le=1)


# --------------------------------------------------------------------------- #
# client
# --------------------------------------------------------------------------- #
class QuestionnaireAnswer(Strict):
    id: str
    question: str
    answer: str
    answered_by: str
    answered_at: str


class ClientMessage(Strict):
    id: str
    sent_at: str
    from_: str = Field(alias="from")
    to: str
    text: str


class CallNote(Strict):
    id: str
    date: str
    participants: list[str]
    notes: list[str]


class Client(Strict):
    questionnaire: list[QuestionnaireAnswer]
    messages: list[ClientMessage]
    call_notes: list[CallNote]


# --------------------------------------------------------------------------- #
# firm
# --------------------------------------------------------------------------- #
class Staff(Strict):
    id: str
    name: str
    role: str
    credential: Optional[str]
    sensitive_data_clearance: bool
    active_from: str
    note: Optional[str] = None


class FirmIdentity(Strict):
    ein: str
    address: str
    phone: str
    efin: str
    ero_pin: str
    ptins: dict[str, str]
    paid_preparer_signing_returns: str


class ClientUser(Strict):
    id: str
    name: str
    role: str


class Assignment(Strict):
    preparer: str
    reviewer: str
    partner: str


class Deadline(Strict):
    what: str
    date: str


class VarianceReview(Strict):
    compare_to: str
    flag_if_change_over_percent: Num
    and_over_amount: Num


class StarterStandards(Strict):
    note: str
    verification_types: list[str]
    variance_review: VarianceReview
    review_levels: list[str]
    rules: list[str]
    required_steps: list[str]


class Firm(Strict):
    name: str
    staff: list[Staff]
    firm_identity: FirmIdentity
    client_users: list[ClientUser]
    assignment_at_start: Assignment
    deadlines: list[Deadline]
    budget_hours: dict[str, Num]
    starter_standards: StarterStandards


# --------------------------------------------------------------------------- #
# prior years
# --------------------------------------------------------------------------- #
class PriorDependent(Strict):
    name: str
    ssn: str


class Return2024(Loose):
    prepared_by: str
    filed: str
    residency: str
    dependents: list[PriorDependent]
    lines: dict[str, Union[int, float, str]]
    line_labels: dict[str, str]
    line_sources: dict[str, str]
    notes: dict[str, str]


class PriorPreparerWorkpaper(Strict):
    source_document: str
    summary_memo: str
    notes: list[str]
    open_items_left_by_prior_preparer: list[str]
    depreciation_schedule: str


class AssetRecord(Strict):
    asset_id: str
    description: str
    activity: str
    cost: Num
    placed_in_service: str
    method: str
    life_years: float
    disposed: Optional[str]
    land_value: Optional[Num] = None
    federal: dict[str, Num]
    california: dict[str, Num]
    amt_difference: dict[str, Num]
    sources: list[str]


class PriorYears(Loose):
    return_2024: Return2024
    prior_preparer_workpaper: PriorPreparerWorkpaper
    asset_records: list[AssetRecord]
    basis_records: dict[str, list[dict[str, Any]]]
    carryovers_into_2025: dict[str, Any]


# --------------------------------------------------------------------------- #
# tax agency records
# --------------------------------------------------------------------------- #
class TranscriptTxn(Strict):
    date: str
    code: str
    description: str
    amount: Union[int, float, str]


class TranscriptSnapshot(Strict):
    as_of: str
    transactions: list[TranscriptTxn]


class Notice(Strict):
    id: str
    agency: str
    type: str
    tax_year: int
    dated: str
    document: str
    summary: Optional[str] = None
    status: Optional[str] = None
    response_due: Optional[str] = None
    items_under_examination: Optional[list[str]] = None


class EfileError(Strict):
    code: str
    message: str


class EfileSubmission(Strict):
    date: str
    jurisdiction: str
    submission_id: str
    status: str
    errors: list[EfileError] = []


class TaxAgencyRecords(Strict):
    irs_account_transcript_2025: list[TranscriptSnapshot]
    ftb_account: dict[str, Any]
    notices: list[Notice]
    efile: list[EfileSubmission]


# --------------------------------------------------------------------------- #
# timeline + engine reference
# --------------------------------------------------------------------------- #
class TimelineEvent(Strict):
    id: str
    at: str
    event: str
    actor: Optional[str]
    detail: Optional[str]
    refs: list[str]


class EngineReference(Strict):
    parameters: dict[str, Any]
    rules: dict[str, str]


# --------------------------------------------------------------------------- #
# return versions
# --------------------------------------------------------------------------- #
class FederalSummary(Strict):
    agi: Num
    taxable_income: Num
    total_tax: Num
    payments: Num
    balance_due: Num
    penalty: Num


class CaliforniaSummary(Strict):
    total_agi: Num
    ca_agi: Num
    total_tax: Num
    payments: Num
    balance_due: Num
    penalty: Num


class ReturnSummary(Strict):
    federal: FederalSummary
    california: CaliforniaSummary


class TaxEffectRate(Strict):
    federal_per_dollar: float
    california_per_dollar: float


class AssetBookDepreciation(Strict):
    prior_accumulated: Num
    depreciation_2025: Num
    accumulated_end: Num


class AmtDepreciation(Strict):
    depreciation_2025: Num
    difference_from_regular: Num


class AssetDisposition(Loose):
    date: str


class ReturnAsset(Strict):
    asset_id: str
    description: str
    activity: str
    cost: Num
    land_value_not_depreciated: Optional[Num]
    placed_in_service: str
    method: str
    life_years: float
    federal: AssetBookDepreciation
    california: AssetBookDepreciation
    amt: AmtDepreciation
    disposed: Optional[str]
    sources: list[str]
    disposition: Optional[AssetDisposition] = None


class Diagnostic(Strict):
    code: str
    severity: Literal["info", "warning"]
    message: str
    refs: list[str]


class LineChange(Strict):
    key: str
    change: Literal["added", "changed", "removed"]
    old: Union[int, float, str, None] = None
    new: Union[int, float, str, None] = None


class ReturnLine(Strict):
    key: str
    jurisdiction: Literal["federal", "california"]
    form: str
    line: str
    label: str
    value: Union[int, float, str]
    rule: str
    inputs: list[str]
    sources: list[str]
    note: Optional[str] = None


class ReturnVersion(Strict):
    version: str
    computed_at: str
    trigger: str
    documents_used: list[str]
    documents_superseded: list[str]
    summary: ReturnSummary
    tax_effect_rates: dict[str, TaxEffectRate]
    carryovers_out: dict[str, Any]
    assets: list[ReturnAsset]
    diagnostics: list[Diagnostic]
    changes_from_previous: list[LineChange]
    lines: list[ReturnLine]


# --------------------------------------------------------------------------- #
# what-if + planning
# --------------------------------------------------------------------------- #
class WhatIfSide(Loose):
    base: dict[str, Num]
    alternative: dict[str, Num]
    total_tax_change: Num


class WhatIfAlternative(Strict):
    id: str
    description: str
    base_version: str
    choices: dict[str, Any]
    federal: WhatIfSide
    california: WhatIfSide
    changed_lines: list[LineChange]


class WhatIf(Strict):
    alternatives: list[WhatIfAlternative]
    extension: dict[str, Any]


# --------------------------------------------------------------------------- #
# root
# --------------------------------------------------------------------------- #
class Packet(Strict):
    packet: PacketInfo
    readme: Readme
    household: Household
    documents: list[Document]
    extracted_values: list[ExtractedValue]
    client: Client
    firm: Firm
    prior_years: PriorYears
    tax_agency_records: TaxAgencyRecords
    timeline: list[TimelineEvent]
    engine_reference: EngineReference
    return_versions: list[ReturnVersion]
    what_if: WhatIf
    planning_reference_2026: dict[str, Any]
    post_filing_rates: dict[str, Any]
    fx_rates: dict[str, dict[str, Num]]
