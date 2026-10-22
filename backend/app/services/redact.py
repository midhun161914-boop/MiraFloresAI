"""Sensitive-data masking for actors without ``sensitive_data_clearance``.

Masking is length-preserving ("666-41-2287" -> "•••-••-2287"), so the
character spans the text locator computed on printed_content stay valid and
highlights still land on the right words for every role.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.loader import PacketIndex

MASK = "•"
SENSITIVE_VALUE_TYPES = {"ssn", "account_number"}
SENSITIVE_KEYS = {"ssn", "ip_pin", "account", "routing"}
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-(\d{4})(?!\d)")


def mask_keep_last4(s: str) -> str:
    """Mask every digit except the last four; keep separators and length."""
    digits = sum(c.isdigit() for c in s)
    out, seen = [], 0
    for c in s:
        if c.isdigit():
            seen += 1
            out.append(c if seen > digits - 4 else MASK)
        else:
            out.append(c)
    return "".join(out)


class Redactor:
    def __init__(self, idx: PacketIndex):
        secrets: set[str] = set()
        self._full: set[str] = set()  # masked entirely (IP PINs), not last-4
        for e in idx.packet.extracted_values:
            if e.value_type in SENSITIVE_VALUE_TYPES:
                secrets.update(x for x in (str(e.value or ""), e.text_as_read) if len(x) >= 6)
        hh = idx.packet.household
        for p in hh.people:
            secrets.add(p.ssn)
            if p.ip_pin:
                secrets.add(p.ip_pin)
                self._full.add(p.ip_pin)
        bank = hh.bank_account_for_refund_or_payment
        secrets.update({bank.account, bank.routing})
        for dep in idx.packet.prior_years.return_2024.dependents:
            secrets.add(dep.ssn)
        # Longest first so a full account number wins over any substring.
        self._secrets = sorted((s for s in secrets if s), key=len, reverse=True)
        self._pattern = re.compile(
            r"(?<![0-9A-Za-z])(" + "|".join(re.escape(s) for s in self._secrets) + r")(?![0-9A-Za-z])"
        ) if self._secrets else None

    def text(self, s: str) -> str:
        if not s:
            return s
        s = _SSN.sub(lambda m: mask_keep_last4(m.group(0)), s)
        if self._pattern is not None:
            s = self._pattern.sub(self._mask_match, s)
        return s

    def _mask_match(self, m: re.Match[str]) -> str:
        hit = m.group(0)
        return MASK * len(hit) if hit in self._full else mask_keep_last4(hit)

    def obj(self, value: Any, key: str | None = None) -> Any:
        """Recursively mask a JSON-like structure (ref targets, records)."""
        if isinstance(value, dict):
            return {k: self.obj(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.obj(v, key) for v in value]
        if isinstance(value, str):
            if key == "ip_pin" or (key in SENSITIVE_KEYS and len(value) <= 6):
                return MASK * len(value)
            if key in SENSITIVE_KEYS:
                return mask_keep_last4(value)
            return self.text(value)
        return value
