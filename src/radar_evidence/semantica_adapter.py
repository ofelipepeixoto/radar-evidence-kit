# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Optional, original bridge to a pinned Semantica truth-maintenance API.

Only eligibility verdicts from the trusted application's EvidenceCheck enter
the rule engine. No document text, query, action, callback or credential enters
an atom. A supported result means citation-contract eligibility, not semantic
entailment or legal truth. This module never authenticates or executes a tool.

The elapsed-time budget rejects late results at checkpoints; it is NOT a hard
process deadline. Input/rule counts are bounded and the fixed rules are acyclic.
An application requiring a hard deadline must isolate this call in its worker.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import time

from .checks import EvidenceCheck


SUPPORTED_VERSION = "0.7.0"
EXPECTED_SNAPSHOT = "a1a8404e20bc146b481dad65cbe5dcccddae84ab"
RULESET_VERSION = "radar-citation-support-v1"
CLAIM_SCOPE = "citation_contract_only"
MAX_CHECKS = 20

# These are hashes, not vendored upstream source. They pin only the listed
# sources, NOT every transitive dependency or the entire Semantica package.
_SOURCE_HASHES = {
    "__init__.py": "3aa34f2dba1de32146fb9c567caaf8acaab83d87bb66a625f6cd6190f9deecf0",
    "reasoning/truth_maintenance.py": "492802a36c6c0b9e7b0c4ded5235db3e71758a4d8e638d4066459332b9d2c2af",
    "reasoning/truth_maintenance_types.py": "c998e5d54a8fba4670c8d6050cab3e76a99f7ab676306e125eab0de4eb951b25",
    "reasoning/_truth_maintenance_validation.py": "ef516243cec1da96aa5e9a22223648d94f082cdf0bc1f0c5edcca993a51dd1b0",
    "reasoning/_truth_maintenance_checkpoint.py": "6cd997d09da8982ac9796732b44509162f8d60ee54a3656a525501634be016e4",
    "reasoning/_rule_matching.py": "dd01fc1dc3c7b3695faa935b4d5a7972a8fee0928aa115e9d6da3e98efbab49f",
    "reasoning/reasoner.py": "a5fad94a00bfd065f49b59d6fe8fc59a5aba872de1fc0a4c982ac85e24ed7e4c",
    "utils/exceptions.py": "70245f76609346d62678ecf5bfebea96362dc855a183723ce2732fcc378d3562",
    "utils/logging.py": "e56a9fd21f88f7ce17e32b97fc4f248f5588d3d36ec498ebb6387e33d5c78185",
    "utils/progress_tracker.py": "b58189e3f4b4720c55212d4cabb6ef1cb59b3bcc2f4f106281c8b5abfc5af3e5",
}


@dataclass(frozen=True, slots=True)
class SupportEvaluation:
    supported: bool
    reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    bundle_id: str | None = None
    derived_claims: tuple[str, ...] = ()
    engine_version: str | None = None
    verified_modules: tuple[str, ...] = ()
    ruleset_version: str = RULESET_VERSION
    expected_snapshot: str = EXPECTED_SNAPSHOT
    claim_scope: str = CLAIM_SCOPE
    evaluation_completed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "supported": self.supported, "reasons": list(self.reasons),
            "evidence_ids": list(self.evidence_ids), "bundle_id": self.bundle_id,
            "derived_claims": list(self.derived_claims),
            "engine_version": self.engine_version,
            "verified_modules": list(self.verified_modules),
            "ruleset_version": self.ruleset_version,
            "expected_snapshot": self.expected_snapshot,
            "claim_scope": self.claim_scope,
            "evaluation_completed": self.evaluation_completed,
        }


class _EngineUnavailable(Exception):
    def __init__(self, code: str):
        self.code = code


def _verified_package_root() -> Path:
    try:
        spec = importlib.util.find_spec("semantica")
    except (ImportError, ValueError):
        raise _EngineUnavailable("dependency_unavailable") from None
    if spec is None or type(spec.origin) is not str:
        raise _EngineUnavailable("dependency_unavailable")
    root = Path(spec.origin).parent
    try:
        for relative, expected in _SOURCE_HASHES.items():
            source = root / relative
            if not source.is_file() or source.stat().st_size > 2 * 1024 * 1024:
                raise _EngineUnavailable("unsupported_source")
            if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                raise _EngineUnavailable("unsupported_source")
    except OSError:
        raise _EngineUnavailable("unsupported_source") from None
    return root


def _load_engine():
    _verified_package_root()
    try:
        package = importlib.import_module("semantica")
        if package.__version__ != SUPPORTED_VERSION:
            raise _EngineUnavailable("unsupported_version")
        # Package imports may load additional modules. No reasoning facade,
        # SPARQL, policies, provenance store or actions are instantiated/called.
        session_type = importlib.import_module(
            "semantica.reasoning.truth_maintenance").TruthMaintenanceSession
        rule_type = importlib.import_module("semantica.reasoning.reasoner").Rule
        support_type = importlib.import_module(
            "semantica.reasoning.truth_maintenance_types").FactSupport
    except _EngineUnavailable:
        raise
    except (ImportError, AttributeError, OSError):
        raise _EngineUnavailable("dependency_unavailable") from None
    return session_type, rule_type, support_type


def _checked_inputs(checks: object) -> tuple[EvidenceCheck, ...]:
    # No general iterable: consuming a malicious/unbounded generator could hang.
    if type(checks) not in (list, tuple) or not 1 <= len(checks) <= MAX_CHECKS:
        raise ValueError("invalid_checks")
    for check in checks:
        if type(check) is not EvidenceCheck:
            raise ValueError("invalid_checks")
        check.__post_init__()  # Revalidate even after privileged dataclass bypass.
    items = tuple(sorted(checks, key=lambda item: item.evidence_id))
    if len({check.evidence_id for check in items}) != len(items):
        raise ValueError("duplicate_evidence")
    return items


def evaluate_support(checks: object, *, evaluation_budget_ms: int = 2000) -> SupportEvaluation:
    """Derive bundle eligibility from 1–20 trusted, unique EvidenceChecks.

    Unknown metadata/dicts, inconsistent checks, unavailable dependencies,
    unsupported version/source, late results and engine errors all deny support.
    Call check_evidence() first with scope/review flags issued by the application.
    This function cannot distinguish a forged but well-shaped verdict issued by
    trusted Python code; hashes and frozen records are not authentication.
    """
    if type(evaluation_budget_ms) is not int or not 10 <= evaluation_budget_ms <= 5000:
        return SupportEvaluation(False, ("invalid_budget",))
    try:
        items = _checked_inputs(checks)
    except (TypeError, ValueError, AttributeError):
        return SupportEvaluation(False, ("invalid_checks",))

    evidence_ids = tuple(item.evidence_id for item in items)
    bundle_payload = json.dumps({"ruleset": RULESET_VERSION, "evidence_ids": evidence_ids},
        sort_keys=True, separators=(",", ":")).encode("ascii")
    bundle_id = hashlib.sha256(bundle_payload).hexdigest()
    started = time.monotonic()

    def deny(code: str, *, verified: bool = False) -> SupportEvaluation:
        return SupportEvaluation(False, (code,), evidence_ids, bundle_id,
            engine_version=SUPPORTED_VERSION if verified else None,
            verified_modules=tuple(sorted(_SOURCE_HASHES)) if verified else ())

    def expired() -> bool:
        return (time.monotonic() - started) * 1000 > evaluation_budget_ms

    try:
        session_type, rule_type, support_type = _load_engine()
        if expired():
            return deny("evaluation_budget_exceeded", verified=True)
        rules = [rule_type(
            "radar_citation_support_v1", "citation contract eligibility v1",
            ["ContractChecked(?e)", "Eligible(?e)"], "CitationSupported(?e)",
        ), rule_type(
            "radar_bundle_support_v1", "all citation checks eligible v1",
            [f"CitationSupported({identifier})" for identifier in evidence_ids],
            f"BundleSupported({bundle_id})",
        )]
        session = session_type(rules=rules)
        assertions = []
        for item in items:
            assertions.append(support_type("check_" + item.evidence_id,
                f"ContractChecked({item.evidence_id})"))
            predicate = "Eligible" if item.supported else "Rejected"
            assertions.append(support_type("status_" + item.evidence_id,
                f"{predicate}({item.evidence_id})"))
        session.apply(assertions=assertions)
        conclusion = f"BundleSupported({bundle_id})"
        explanation = session.explain(conclusion)
        derived = tuple(sorted(fact for fact in session.facts
            if fact.startswith(("CitationSupported(", "BundleSupported("))))
        if expired():
            return deny("evaluation_budget_exceeded", verified=True)
        expected_support = all(item.supported for item in items)
        actual_support = explanation.active is True and conclusion in session.facts
        expected_derived = tuple(sorted(
            [f"CitationSupported({item.evidence_id})" for item in items if item.supported]
            + ([conclusion] if expected_support else [])))
        # A malformed/unexpected engine verdict never overrides the core checks.
        if actual_support != expected_support or derived != expected_derived:
            return deny("engine_contract_mismatch", verified=True)
        reasons = tuple(sorted({reason for item in items for reason in item.reasons}))
        return SupportEvaluation(actual_support, reasons, evidence_ids, bundle_id,
            derived, SUPPORTED_VERSION, tuple(sorted(_SOURCE_HASHES)), evaluation_completed=True)
    except _EngineUnavailable as error:
        return deny(error.code)
    except Exception:
        # Never echo exceptions containing source paths/text or provider data.
        return deny("engine_error")
