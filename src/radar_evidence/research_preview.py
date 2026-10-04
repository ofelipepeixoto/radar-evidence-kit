# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Offline JSON consumer. No model, network, shell tool or external action.

Scope comes from an operator-owned local file, separately from the snapshot.
The file and review issuer must be trusted by the application. This CLI does
not authenticate their issuer; its output explicitly retains that limitation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .modelos import Evidence, Scope
from .occurrences import group_occurrences, MAX_RECORDS

MAX_INPUT_BYTES = 256 * 1024


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def parse_json(raw: bytes) -> object:
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("input limit")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")))


def preview(snapshot: dict, scope: Scope) -> dict:
    if type(snapshot) is not dict or set(snapshot) != {"schema", "evidence"}:
        raise ValueError("invalid snapshot")
    if snapshot["schema"] != "radar-evidence-snapshot-v1":
        raise ValueError("invalid schema")
    raw = snapshot["evidence"]
    if type(raw) is not list or len(raw) > MAX_RECORDS:
        raise ValueError("invalid evidence count")
    records = [Evidence.from_dict(item) for item in raw]
    groups = group_occurrences(records, scope)
    included = sum(len(group.evidence) for group in groups)
    # Distinguish policy exclusion from idempotent repetitions.
    eligible_ids = {candidate.evidence_id for group in groups for candidate in group.evidence}
    eligible = sum(1 for item in records if item.evidence_id in eligible_ids)
    return {
        "schema": "radar-research-preview-v1", "tenantId": scope.tenant_id,
        "projectId": scope.project_id, "groups": [g.to_dict() for g in groups],
        "includedOccurrences": included, "excludedRecords": len(records) - eligible,
        "duplicateRecords": eligible - included,
        "decision": "needs_review" if groups else "abstained",
        "paidCallsEnabled": False, "externalActionsEnabled": False,
        "issuerVerified": False, "scope": "offline-evidence-preview",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prévia offline de evidências; sem IA ou ações externas")
    parser.add_argument("--scope", type=Path, required=True, help="Arquivo local de configuração confiável")
    args = parser.parse_args()
    try:
        with args.scope.open("rb") as stream:
            scope = Scope.from_dict(parse_json(stream.read(MAX_INPUT_BYTES + 1)))
        snapshot = parse_json(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1))
        result = preview(snapshot, scope)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        print('{"error":"EVIDENCE_PREVIEW_DENIED"}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
