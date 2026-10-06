# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Exact subspans of reviewed evidence; no retrieval, identity or authorization.

Offsets are Python/Unicode code points, never UTF-8 bytes or PDF coordinates.
The full parent record must come from the consumer's trusted current store.
"""

from dataclasses import dataclass, replace
from hashlib import sha256
from typing import ClassVar

from .checks import check_evidence
from .modelos import Evidence, Scope, _exact_fields, _hash, _integer


@dataclass(frozen=True, slots=True)
class Citation:
    parent_evidence_id: str
    start: int
    end: int
    quote_sha256: str

    FIELDS: ClassVar[frozenset[str]] = frozenset({
        "parent_evidence_id", "start", "end", "quote_sha256",
    })

    def __post_init__(self) -> None:
        _hash(self.parent_evidence_id, "parent_evidence_id")
        _hash(self.quote_sha256, "quote_sha256")
        _integer(self.start, "start", minimum=0)
        _integer(self.end, "end", minimum=1)
        if self.end <= self.start:
            raise ValueError("citation must be a non-empty forward span")

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "Citation":
        _exact_fields(payload, cls.FIELDS, "Citation")
        return cls(**payload)

    def to_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in sorted(self.FIELDS)}


def make_citation(parent: Evidence, start: int, end: int) -> Citation:
    """Bind a span without granting eligibility; use resolve_citation before use."""
    if type(parent) is not Evidence:
        raise TypeError("parent must be an Evidence instance")
    parent.__post_init__()
    _integer(start, "start", minimum=0)
    _integer(end, "end", minimum=1)
    if not parent.start <= start < end <= parent.end:
        raise ValueError("citation must be contained in the parent span")
    return Citation(parent.evidence_id, start, end,
                    sha256(parent.text[start:end].encode("utf-8")).hexdigest())


def resolve_citation(
    citation: Citation, parent: Evidence, scope: Scope, *,
    require_verified_review: bool = True,
) -> Evidence:
    """Revalidate a reference and current eligibility, preserving full context.

    Local research may explicitly disable the verified-identity requirement.
    This never upgrades the parent's identity flag, refreshes a stale revision,
    authenticates the issuer or authorizes an external action.
    """
    if type(citation) is not Citation:
        raise TypeError("citation must be a Citation instance")
    citation.__post_init__()
    expected = make_citation(parent, citation.start, citation.end)
    if citation != expected:
        raise ValueError("citation does not match its complete parent record")
    checked = check_evidence(parent, scope, require_verified_review)
    if not checked.supported:
        raise ValueError("citation parent is not eligible in the current scope: "
                         + ",".join(checked.reasons))
    return replace(parent, start=citation.start, end=citation.end)


def split_evidence(
    parent: Evidence, *, max_chars: int = 512, overlap: int = 64,
) -> tuple[Citation, ...]:
    """Deterministic fixed windows, at most 512 per parent; not semantic chunks.

    No text is rewritten, dropped, summarized or separately marked reviewed.
    Eligibility is deliberately checked at consumption, not cached here.
    """
    _integer(max_chars, "max_chars", minimum=64)
    _integer(overlap, "overlap", minimum=0)
    if max_chars > 4096 or overlap > max_chars // 2:
        raise ValueError("max_chars <= 4096 and overlap <= max_chars / 2 required")
    if type(parent) is not Evidence:
        raise TypeError("parent must be an Evidence instance")
    parent.__post_init__()
    result: list[Citation] = []
    start = parent.start
    while start < parent.end:
        if len(result) >= 512:
            raise ValueError("too many citation windows")
        end = min(start + max_chars, parent.end)
        result.append(make_citation(parent, start, end))
        if end == parent.end:
            break
        start = end - overlap
    return tuple(result)
