# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Bounded offline study of citation-support withdrawal; not an authorization API.

Checks, windows and observation times must be issued by a trusted backend. This
module does not authenticate them, consult a clock/database, or schedule work.
Every citation in the bundle is required (AND); no semantic entailment is tested.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time

from . import semantica_adapter as adapter
from .modelos import _hash

MAX_OBSERVATIONS = 32
MAX_TIMESTAMP_MS = 2**53 - 1
RULESET_VERSION = "radar-support-lifecycle-v1"


def _timestamp(value: object) -> None:
    if type(value) is not int or not 0 <= value <= MAX_TIMESTAMP_MS:
        raise ValueError("invalid_timestamp")


@dataclass(frozen=True, slots=True)
class SupportWindow:
    """UTC epoch milliseconds, [valid_from, valid_until); withdrawal is final.

    None means no declared expiry/withdrawal, not a check of external revocation.
    A new document/review requires new Evidence and a fresh backend evaluation.
    """
    evidence_id: str
    valid_from_ms: int
    valid_until_ms: int | None = None
    withdrawn_at_ms: int | None = None

    def __post_init__(self) -> None:
        _hash(self.evidence_id, "evidence_id")
        _timestamp(self.valid_from_ms)
        for value in (self.valid_until_ms, self.withdrawn_at_ms):
            if value is not None:
                _timestamp(value)
                if value < self.valid_from_ms:
                    raise ValueError("invalid_window")
        if self.valid_until_ms == self.valid_from_ms:
            raise ValueError("invalid_window")


@dataclass(frozen=True, slots=True)
class SupportFrame:
    at_ms: int
    supported: bool
    active_evidence_ids: tuple[str, ...]
    excluded: tuple[tuple[str, tuple[str, ...]], ...]
    derived_claims: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"at_ms": self.at_ms, "supported": self.supported,
                "active_evidence_ids": list(self.active_evidence_ids),
                "excluded": [{"evidence_id": key, "reasons": list(reasons)}
                             for key, reasons in self.excluded],
                "derived_claims": list(self.derived_claims)}


@dataclass(frozen=True, slots=True)
class LifecycleEvaluation:
    evaluation_completed: bool = False
    reasons: tuple[str, ...] = ()
    engine: str = "radar"
    study_id: str | None = None
    frames: tuple[SupportFrame, ...] = ()

    def to_dict(self) -> dict:
        return {"evaluation_completed": self.evaluation_completed,
                "reasons": list(self.reasons), "engine": self.engine,
                "study_id": self.study_id, "frames": [f.to_dict() for f in self.frames],
                "claim_scope": "citation_contract_only", "status": "STUDY_ONLY",
                "ruleset_version": RULESET_VERSION}


def evaluate_timeline(checks: object, windows: object, observations_ms: object, *,
                      use_semantica: bool = False,
                      evaluation_budget_ms: int = 2000) -> LifecycleEvaluation:
    """Compare support over <=32 observations for 1–20 unique trusted checks.

    Default is dependency-free. Optional Semantica uses the existing verified
    source loader and one session with actual assertion/retraction batches.
    Every derived fact is compared against deterministic Radar rules. Failure
    discards ALL frames. Checkpoint budget is not a hard process timeout.
    No document text, arbitrary rules, callbacks, paths or queries are accepted.
    """
    engine = "semantica" if use_semantica is True else "radar"

    def deny(code: str) -> LifecycleEvaluation:
        return LifecycleEvaluation(reasons=(code,), engine=engine)

    if type(use_semantica) is not bool:
        return deny("invalid_mode")
    if type(evaluation_budget_ms) is not int or not 10 <= evaluation_budget_ms <= 5000:
        return deny("invalid_budget")
    try:
        items = adapter._checked_inputs(checks)
        if type(windows) not in (list, tuple) or len(windows) != len(items):
            return deny("invalid_windows")
        bindings = {}
        for window in windows:
            if type(window) is not SupportWindow:
                return deny("invalid_windows")
            window.__post_init__()
            if window.evidence_id in bindings:
                return deny("invalid_windows")
            bindings[window.evidence_id] = window
        if set(bindings) != {item.evidence_id for item in items}:
            return deny("invalid_windows")
        if (type(observations_ms) not in (tuple, list)
                or not 1 <= len(observations_ms) <= MAX_OBSERVATIONS):
            return deny("invalid_observations")
        observations = tuple(observations_ms)
        for at in observations:
            _timestamp(at)
        if any(a >= b for a, b in zip(observations, observations[1:])):
            return deny("invalid_observations")
    except (ValueError, TypeError, AttributeError):
        return deny("invalid_input")

    # Bind the identity to verdicts, policy windows and requested observations.
    payload = {"ruleset": RULESET_VERSION, "checks": [c.to_dict() for c in items],
               "windows": [[w.evidence_id, w.valid_from_ms, w.valid_until_ms, w.withdrawn_at_ms]
                           for w in sorted(bindings.values(), key=lambda w: w.evidence_id)],
               "observations_ms": observations}
    study_id = hashlib.sha256(json.dumps(payload, sort_keys=True,
        separators=(",", ":")).encode("ascii")).hexdigest()
    conclusion = f"BundleSupported({study_id})"
    started = time.monotonic()

    def expired() -> bool:
        return (time.monotonic() - started) * 1000 > evaluation_budget_ms

    try:
        if use_semantica:
            session_type, rule_type, support_type = adapter._load_engine()
            if expired():
                return deny("evaluation_budget_exceeded")
            session = session_type(rules=[rule_type(
                "radar_lifecycle_citation_v1", "active eligible citation",
                ["ActiveEligible(?e)"], "CitationSupported(?e)"), rule_type(
                "radar_lifecycle_bundle_v1", "all citations required",
                [f"CitationSupported({item.evidence_id})" for item in items], conclusion)])
        previous_active: set[str] = set()
        frames = []
        for at in observations:
            if expired():
                return deny("evaluation_budget_exceeded")
            active, excluded = [], []
            for item in items:
                window = bindings[item.evidence_id]
                reasons = list(item.reasons)
                if at < window.valid_from_ms:
                    reasons.append("support_not_yet_valid")
                if window.valid_until_ms is not None and at >= window.valid_until_ms:
                    reasons.append("support_expired")
                if window.withdrawn_at_ms is not None and at >= window.withdrawn_at_ms:
                    reasons.append("support_withdrawn")
                if reasons:
                    excluded.append((item.evidence_id, tuple(sorted(reasons))))
                else:
                    active.append(item.evidence_id)
            supported = not excluded
            expected = tuple(sorted([f"CitationSupported({key})" for key in active]
                                    + ([conclusion] if supported else [])))
            if use_semantica:
                current_active = set(active)
                session.apply(assertions=[support_type("active_" + key,
                    f"ActiveEligible({key})") for key in sorted(current_active - previous_active)],
                    retractions=["active_" + key for key in sorted(previous_active - current_active)])
                actual = tuple(sorted(fact for fact in session.facts
                    if fact.startswith(("CitationSupported(", "BundleSupported("))))
                explanation = session.explain(conclusion)
                if (actual != expected or type(explanation.active) is not bool
                        or explanation.active != supported):
                    return deny("engine_contract_mismatch")
                previous_active = current_active
            frames.append(SupportFrame(at, supported, tuple(active), tuple(excluded), expected))
        if expired():
            return deny("evaluation_budget_exceeded")
        return LifecycleEvaluation(True, (), engine, study_id, tuple(frames))
    except adapter._EngineUnavailable as error:
        return deny(error.code)
    except Exception:
        # No logger, traceback or upstream exception text in the result.
        return deny("engine_error")
