# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Bounded offline grouping: equal content retains each distinct source.

Review flags/Scope are application-issued inputs, not authentication. Neither
hashing nor this grouping reads the original artifact or verifies its truth.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .checks import check_evidence
from .modelos import Evidence, Scope

MAX_RECORDS = 1000


def _digest(values: list) -> str:
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class OccurrenceGroup:
    content_id: str
    text_sha256: str
    text: str
    evidence: tuple[Evidence, ...]

    def to_dict(self) -> dict:
        return {
            "contentId": self.content_id, "textSha256": self.text_sha256,
            "text": self.text,
            "occurrences": [{
                "occurrenceId": occurrence_id(item), "evidenceId": item.evidence_id,
                "documentId": item.document_id, "revision": item.revision,
                "page": item.page, "start": item.start, "end": item.end,
                "sourceSha256": item.source_sha256, "quote": item.quote,
            } for item in self.evidence],
        }


def occurrence_id(evidence: Evidence) -> str:
    if type(evidence) is not Evidence:
        raise TypeError("Evidence required")
    evidence.__post_init__()
    return _digest([
        "radar-occurrence-v1", evidence.tenant_id, evidence.project_id,
        evidence.document_id, evidence.revision, evidence.page, evidence.start,
        evidence.end, evidence.source_sha256, evidence.text_sha256,
    ])


def group_occurrences(records: list[Evidence], scope: Scope) -> tuple[OccurrenceGroup, ...]:
    """Only current, approved, identity-flagged records enter the groups.

    Bounded plain list, deterministic order, exact replay deduplication.
    Conflicting review receipts for one occurrence fail rather than selecting
    the first silently. Output has no excluded tenant/document metadata.
    """
    if type(records) is not list or len(records) > MAX_RECORDS:
        raise ValueError("records must be a list of at most 1000 items")
    if type(scope) is not Scope:
        raise TypeError("Scope required")
    grouped: dict[str, dict[str, Evidence]] = {}
    texts: dict[str, Evidence] = {}
    for item in records:
        if not check_evidence(item, scope).supported:
            continue
        content = _digest(["radar-content-v1", scope.tenant_id, scope.project_id,
                           item.text_sha256])
        occurrence = occurrence_id(item)
        bucket = grouped.setdefault(content, {})
        existing = bucket.get(occurrence)
        if existing is not None and existing.evidence_id != item.evidence_id:
            raise ValueError("conflicting occurrence review")
        bucket[occurrence] = item
        texts[content] = item
    return tuple(OccurrenceGroup(content, texts[content].text_sha256,
                                 texts[content].text,
                                 tuple(bucket[key] for key in sorted(bucket)))
                 for content, bucket in sorted(grouped.items()))
