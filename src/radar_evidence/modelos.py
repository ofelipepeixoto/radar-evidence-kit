# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Original, dependency-free evidence contracts for offline evaluation.

Hash validation checks the supplied record, not the truth of its text. The
source hash identifies a source artifact; this module does not read that
artifact. Reviewer labels and ``identity_verified`` must be issued by the
trusted application and do not authenticate a person themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import ClassVar, Mapping


MAX_TEXT_BYTES = 16 * 1024
MAX_IDENTIFIER_CHARS = 256
MAX_SCOPE_DOCUMENTS = 10_000
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _string(value: object, field: str, *, nonempty: bool = False) -> None:
    if type(value) is not str:
        raise TypeError(f"{field} must be a string")
    if nonempty and not value.strip():
        raise ValueError(f"{field} must not be blank")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{field} must contain valid UTF-8 text") from None


def _integer(value: object, field: str, *, minimum: int) -> None:
    # bool is a subclass of int; it must not represent a page or revision.
    if type(value) is not int:
        raise TypeError(f"{field} must be an integer")
    if value < minimum:
        raise ValueError(f"{field} must be at least {minimum}")


def _identifier(value: object, field: str) -> None:
    _string(value, field, nonempty=True)
    if len(value) > MAX_IDENTIFIER_CHARS:
        raise ValueError(f"{field} exceeds 256 Unicode code points")


def _hash(value: object, field: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field} must be a string")
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")


def _exact_fields(data: object, expected: frozenset[str], kind: str) -> None:
    if type(data) is not dict:
        raise TypeError(f"{kind} must be a plain dictionary")
    if any(type(key) is not str for key in data):
        raise TypeError(f"{kind} field names must be strings")
    actual = frozenset(data)
    if actual != expected:
        # Do not echo untrusted field values, labels, or document content.
        raise ValueError(f"{kind} must contain exactly its documented fields")


@dataclass(frozen=True, slots=True)
class Evidence:
    """One complete text snapshot and a Unicode code-point citation span.

    ``text_sha256`` covers the full text, including context outside the quote.
    ``evidence_id`` covers every serialized field, including review state,
    reviewer, identity flag, source hash, full text, and citation bounds.
    A caller can mint a valid hash for false text; issuer trust is external.
    """

    tenant_id: str
    project_id: str
    document_id: str
    revision: int
    page: int
    start: int
    end: int
    text: str
    source_sha256: str
    text_sha256: str
    review_status: str
    reviewer: str
    identity_verified: bool

    FIELDS: ClassVar[frozenset[str]] = frozenset({
        "tenant_id", "project_id", "document_id", "revision", "page", "start",
        "end", "text", "source_sha256", "text_sha256", "review_status",
        "reviewer", "identity_verified",
    })

    def __post_init__(self) -> None:
        for field in ("tenant_id", "project_id", "document_id"):
            _identifier(getattr(self, field), field)
        _integer(self.revision, "revision", minimum=1)
        _integer(self.page, "page", minimum=1)
        _integer(self.start, "start", minimum=0)
        _integer(self.end, "end", minimum=1)
        _string(self.text, "text")
        encoded = self.text.encode("utf-8")
        if len(encoded) > MAX_TEXT_BYTES:
            raise ValueError("text exceeds the 16 KiB UTF-8 limit")
        if not self.start < self.end <= len(self.text):
            raise ValueError("span must satisfy 0 <= start < end <= len(text)")
        _hash(self.source_sha256, "source_sha256")
        _hash(self.text_sha256, "text_sha256")
        if hashlib.sha256(encoded).hexdigest() != self.text_sha256:
            raise ValueError("text_sha256 does not match the complete text")
        _string(self.review_status, "review_status")
        if self.review_status not in {"approved", "pending", "rejected"}:
            raise ValueError("review_status must be approved, pending, or rejected")
        _string(self.reviewer, "reviewer")
        if len(self.reviewer) > 100:
            raise ValueError("reviewer exceeds 100 Unicode code points")
        if type(self.identity_verified) is not bool:
            raise TypeError("identity_verified must be a boolean")

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Evidence:
        _exact_fields(data, cls.FIELDS, "Evidence")
        return cls(**data)

    def to_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in sorted(self.FIELDS)}

    @property
    def quote(self) -> str:
        return self.text[self.start:self.end]

    @property
    def evidence_id(self) -> str:
        # This v1 Python contract has only strings, integers, and booleans;
        # it accepts no floats, NaN, arbitrary objects, or ambiguous concatenation.
        payload = json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class Scope:
    """Trusted operator/application configuration; never inferred from an LLM.

    Revision bindings are copied and exposed as a read-only mapping, so later
    mutation of the caller's dictionary cannot silently change a check.
    This object contains no credentials and grants no execution authority.
    """

    tenant_id: str
    project_id: str
    current_revisions: Mapping[str, int]

    FIELDS: ClassVar[frozenset[str]] = frozenset({
        "tenant_id", "project_id", "current_revisions",
    })

    def __post_init__(self) -> None:
        _identifier(self.tenant_id, "tenant_id")
        _identifier(self.project_id, "project_id")
        if type(self.current_revisions) is not dict:
            raise TypeError("current_revisions must be a plain dictionary")
        if len(self.current_revisions) > MAX_SCOPE_DOCUMENTS:
            raise ValueError("current_revisions exceeds 10000 documents")
        revisions = self.current_revisions.copy()
        for document_id, revision in revisions.items():
            _identifier(document_id, "document_id")
            _integer(revision, "current revision", minimum=1)
        object.__setattr__(self, "current_revisions", MappingProxyType(revisions))

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Scope:
        _exact_fields(data, cls.FIELDS, "Scope")
        return cls(**data)

    def to_dict(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "current_revisions": dict(self.current_revisions),
        }
