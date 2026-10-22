"""API I/O models. The frontend's TypeScript types are generated from these
(via the OpenAPI schema), so the contract has one source of truth."""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel

from app.models.packet import (
    Extraction, Page, Position, ReturnLine, ReturnSummary, ValueType,
)

DocUse = Literal["used", "superseded", "not_used"]


class TextMatchOut(BaseModel):
    status: Literal["exact", "ambiguous", "not_found", "empty"]
    start: Optional[int] = None
    end: Optional[int] = None
    candidates: int = 0
    matched_text: Optional[str] = None
    normalized: bool = False


class ValueOut(BaseModel):
    id: str
    document_id: str
    document_title: str
    page: int
    field: str
    label: str
    value: Union[bool, int, float, str, None]
    value_type: ValueType
    text_as_read: str
    position: Position
    confidence: float
    match: TextMatchOut
    redacted: bool = False
    lands_in: list[str] = []  # current-version return lines this value feeds
    correction: Optional[dict[str, Any]] = None  # active correction: to, from, reason, by, at


class ValuesPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[ValueOut]


class DocumentSummary(BaseModel):
    id: str
    title: str
    document_type: str
    issuer: str
    belongs_to: str
    tax_year: int
    received_at: str
    uploaded_by: str
    file_name: str
    page_count: int
    marked_corrected: bool
    extraction: Extraction
    value_count: int
    low_confidence_count: int
    unlocated_count: int
    used_in: list[str]
    superseded_in: list[str]
    current_use: DocUse
    landing_status: str = "lands"
    lines_fed: int = 0


class DocumentDetail(DocumentSummary):
    pages: list[Page]
    values: list[ValueOut]
    redacted: bool = False


class VersionSummary(BaseModel):
    version: str
    computed_at: str
    trigger: str
    is_current: bool
    line_count: int
    asset_count: int
    diagnostic_count: int
    documents_used: list[str]
    documents_superseded: list[str]
    summary: ReturnSummary
    # summary field -> the return line that carries it, e.g. federal.total_tax -> F1040.24
    summary_lines: dict[str, dict[str, Optional[str]]] = {}


class PersonBrief(BaseModel):
    id: str
    name: str
    role: str


class Overview(BaseModel):
    client_id: str
    household_name: str
    tax_year: int
    filing_status: str
    people: list[PersonBrief]
    current_version: str
    packet_sha256: str
    counts: dict[str, int]
    versions: list[VersionSummary]
    low_confidence_threshold: float


class LineRow(ReturnLine):
    change: Optional[Literal["added", "changed", "removed"]] = None
    previous_value: Union[int, float, str, None] = None
    used_by_count: int = 0
    adjusted_value: Optional[float] = None   # value after active workpaper adjustments
    adjustments: list[str] = []


class LinesPage(BaseModel):
    version: str
    total: int
    forms: list[str]
    items: list[LineRow]


class ResolveBatchIn(BaseModel):
    refs: list[str]
    version: Optional[str] = None
