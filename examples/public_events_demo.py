# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Synthetic local demo; no feeds, models, tokens or network requests."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from radar_evidence import Checkpoint, Journal, Scope, check_evidence
from radar_evidence.public_events import EventSnapshot, PublicEvent, PublicEventCatalog, SourcePolicy


def main():
    now = 1_791_676_800_000
    snapshot = EventSnapshot(
        tenant_id="tenant-fixture", project_id="radar-fixture",
        snapshot_id="snapshot-fixture", revision=1, source_id="synthetic-events",
        source_url="https://example.invalid/events", license_ref="synthetic-only",
        source_sha256=hashlib.sha256(b"original synthetic fixture").hexdigest(),
        retrieved_at_ms=now, coverage="partial",
        records=(PublicEvent("synthetic-1", "earthquake", now-1000,
                             -22_900_000, -43_200_000, "Evento fictício, sem alerta real."),
                 PublicEvent("synthetic-unknown", "other", None,
                             -22_900_000, -43_200_000, "Horário da observação desconhecido.")),
    )
    scope = Scope(snapshot.tenant_id, snapshot.project_id, {snapshot.snapshot_id: 1})
    tools = PublicEventCatalog(
        scope=scope, snapshots=(snapshot,),
        sources=(SourcePolicy(snapshot.source_id, snapshot.source_url, snapshot.license_ref),),
    )
    result = tools.call("events.query", {
        "bbox_e6": [-44_000_000, -24_000_000, -42_000_000, -21_000_000],
        "start_ms": now-10_000, "end_ms": now, "limit": 5,
    }, now_ms=now)
    evidence = snapshot.to_evidence()
    assessment = check_evidence(evidence, scope)
    with TemporaryDirectory(prefix="radar-public-event-fixture-") as directory:
        journal = Journal(Path(directory)/"receipts.sqlite3", scope)
        checkpoint = journal.append(
            evidence, assessment, event_id=snapshot.snapshot_sha256,
            occurred_at="2026-10-11T00:00:00Z", expected_checkpoint=Checkpoint.empty(scope),
        )
        journal.verify(checkpoint)
        receipt_count = len(journal.export_records(checkpoint))
    print(json.dumps({"mode": "synthetic-offline", "query": result,
                      "assessment": assessment.to_dict(), "receipt_count": receipt_count,
                      "checkpoint": checkpoint.to_dict()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
