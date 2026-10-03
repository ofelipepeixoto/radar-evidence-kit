# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Pure evidence eligibility checks, independent of authentication or tools.

``supported`` means the supplied record matches this contract, current trusted
scope, and review policy. It does not verify legal truth, authentic authorship,
reviewer credentials, or the bytes behind ``source_sha256``. The application
must issue review flags and Scope from trusted configuration, not LLM output.
"""

from __future__ import annotations

from dataclasses import dataclass

from .modelos import Evidence, Scope, _hash


REASON_CODES = frozenset({
    "tenant_scope_mismatch", "project_scope_mismatch", "unknown_document",
    "stale_revision", "review_pending", "review_rejected", "missing_reviewer",
    "reviewer_identity_unverified",
})


@dataclass(frozen=True, slots=True)
class EvidenceCheck:
    supported: bool
    reasons: tuple[str, ...]
    evidence_id: str

    def __post_init__(self) -> None:
        if type(self.supported) is not bool:
            raise TypeError("supported must be a boolean")
        if type(self.reasons) is not tuple:
            raise TypeError("reasons must be a tuple")
        if len(self.reasons) > len(REASON_CODES):
            raise ValueError("too many evidence reason codes")
        if any(type(reason) is not str for reason in self.reasons):
            raise TypeError("reason codes must be strings")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("reason codes must not repeat")
        if any(reason not in REASON_CODES for reason in self.reasons):
            raise ValueError("unknown evidence reason code")
        if self.supported != (not self.reasons):
            raise ValueError("supported must match whether reasons are empty")
        _hash(self.evidence_id, "evidence_id")

    def to_dict(self) -> dict[str, object]:
        return {
            "supported": self.supported,
            "reasons": list(self.reasons),
            "evidence_id": self.evidence_id,
        }


def check_evidence(
    evidence: Evidence,
    scope: Scope,
    require_verified_review: bool = True,
) -> EvidenceCheck:
    """Validate an existing Evidence against a trusted Scope, with no effects.

    Invalid argument types raise TypeError; invalid Evidence contract values
    raise ValueError. Well-formed but ineligible records return ``supported=False``
    and stable reason codes. Disabling the identity flag check still requires
    approved review status; it does not bypass tenant/revision restrictions.
    """
    if type(evidence) is not Evidence:
        raise TypeError("evidence must be an Evidence instance")
    if type(scope) is not Scope:
        raise TypeError("scope must be a Scope instance")
    if type(require_verified_review) is not bool:
        raise TypeError("require_verified_review must be a boolean")

    # Revalidate before use even if privileged Python code circumvented the
    # frozen dataclass guard. Frozen records do not replace issuer trust.
    evidence.__post_init__()
    reasons: list[str] = []
    if evidence.tenant_id != scope.tenant_id:
        reasons.append("tenant_scope_mismatch")
    if evidence.project_id != scope.project_id:
        reasons.append("project_scope_mismatch")
    revision = scope.current_revisions.get(evidence.document_id)
    if revision is None:
        reasons.append("unknown_document")
    elif evidence.revision != revision:
        reasons.append("stale_revision")
    if evidence.review_status != "approved":
        reasons.append(f"review_{evidence.review_status}")
    elif not evidence.reviewer.strip():
        reasons.append("missing_reviewer")
    if require_verified_review and not evidence.identity_verified:
        reasons.append("reviewer_identity_unverified")
    return EvidenceCheck(
        supported=not reasons,
        reasons=tuple(reasons),
        evidence_id=evidence.evidence_id,
    )
