# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Synthetic-only contracts, query boundaries and real SQLite receipt bridge."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from radar_evidence import Checkpoint, IntegrityError, Journal, Scope, check_evidence
from radar_evidence.public_events import (
    EventSnapshot, PublicEvent, PublicEventCatalog, SourcePolicy,
)

NOW = 1_791_676_800_000


def event(**overrides):
    fields = dict(event_id="synthetic-1", kind="earthquake", observed_at_ms=NOW-1000,
                  latitude_e6=-22_900_000, longitude_e6=-43_200_000,
                  summary="Evento fictício — não é alerta real.")
    fields.update(overrides)
    return PublicEvent(**fields)


def snapshot(**overrides):
    fields = dict(tenant_id="tenant-fixture", project_id="radar-fixture",
                  snapshot_id="snapshot-fixture", revision=1,
                  source_id="synthetic-events", source_url="https://example.invalid/events",
                  license_ref="synthetic-only", source_sha256=hashlib.sha256(b"synthetic bytes").hexdigest(),
                  retrieved_at_ms=NOW, coverage="partial", records=(event(),))
    fields.update(overrides)
    return EventSnapshot(**fields)


def scope(**overrides):
    fields = dict(tenant_id="tenant-fixture", project_id="radar-fixture",
                  current_revisions={"snapshot-fixture": 1})
    fields.update(overrides)
    return Scope(**fields)


def catalog(data=None, **overrides):
    fields = dict(scope=scope(), snapshots=(data or snapshot(),),
                  sources=(SourcePolicy("synthetic-events", "https://example.invalid/events", "synthetic-only"),))
    fields.update(overrides)
    return PublicEventCatalog(**fields)


def query(**overrides):
    fields = dict(bbox_e6=[-44_000_000, -24_000_000, -42_000_000, -21_000_000],
                  start_ms=NOW-10_000, end_ms=NOW, limit=5)
    fields.update(overrides)
    return fields


class PublicEventTests(unittest.TestCase):
    def test_roundtrip_immutable_and_original_dictionary_detached(self):
        data = snapshot().to_dict()
        model = EventSnapshot.from_dict(data)
        data["records"][0]["summary"] = "tampered"
        self.assertEqual(model, snapshot())
        with self.assertRaises(FrozenInstanceError):
            model.coverage = "complete"
        self.assertEqual(EventSnapshot.from_dict(model.to_dict()), model)

    def test_hash_covers_scope_license_coverage_times_and_records(self):
        original = snapshot()
        for changes in ({"tenant_id": "other"}, {"license_ref": "other"},
                        {"coverage": "complete"}, {"retrieved_at_ms": NOW+1},
                        {"records": (event(summary="Changed fixture"),)}):
            with self.subTest(changes=changes):
                self.assertNotEqual(original.snapshot_sha256, replace(original, **changes).snapshot_sha256)

    def test_unknown_fields_cannot_inject_approval_or_credentials(self):
        for field in ("identity_verified", "approved", "token", "source_url_override"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    EventSnapshot.from_dict({**snapshot().to_dict(), field: True})
        with self.assertRaises(ValueError):
            PublicEvent.from_dict({**event().to_dict(), "approved": True})

    def test_numeric_types_and_coordinate_bounds(self):
        for value in (True, 1.2, float("nan"), "0", 90_000_001, -90_000_001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                event(latitude_e6=value)
        for value in (True, 0, -1, float("inf")):
            with self.subTest(time=value), self.assertRaises(ValueError):
                event(observed_at_ms=value)

    def test_utf8_byte_limit(self):
        event(summary="é" * 512)
        with self.assertRaises(ValueError):
            event(summary="é" * 513)

    def test_duplicates_future_observation_and_snapshot_byte_limit(self):
        for fields in ({"records": (event(), event())},
                       {"records": (event(observed_at_ms=NOW+1),)},
                       {"records": tuple(event(event_id=str(i), summary="x"*1024) for i in range(20))},
                       {"records": tuple(event(event_id=str(i)) for i in range(101))}):
            with self.subTest(fields=list(fields)), self.assertRaises(ValueError):
                snapshot(**fields)

    def test_source_url_metadata_refuses_credentials_and_non_https(self):
        for url in ("file:///etc/passwd", "http://example.invalid", "https://u:p@example.invalid/x",
                    "https://example.invalid/?token=x", "https://example.invalid/#x",
                    "https://example.invalid/\n", "https://example.invalid:bad/x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                snapshot(source_url=url)

    def test_scope_and_revision_are_trusted_constructor_inputs(self):
        for data in (snapshot(tenant_id="other"), snapshot(project_id="other"),
                     snapshot(revision=2), snapshot(snapshot_id="unknown")):
            with self.subTest(data=data.snapshot_id), self.assertRaises(ValueError):
                catalog(data)

    def test_source_policy_cannot_be_forged_by_snapshot(self):
        for data in (snapshot(source_id="other"), snapshot(license_ref="commercial-ok"),
                     snapshot(source_url="https://evil.invalid/events")):
            with self.subTest(source=data.source_id), self.assertRaises(ValueError):
                catalog(data)
        with self.assertRaises(ValueError):
            catalog(commercial=True)
        catalog(commercial=True, sources=(SourcePolicy("synthetic-events", "https://example.invalid/events", "synthetic-only", True),))

    def test_policy_and_snapshot_capacity_are_bounded(self):
        for changes in ({"snapshots": [snapshot()]}, {"sources": []},
                        {"sources": (SourcePolicy("synthetic-events", "https://example.invalid/events", "synthetic-only"),)*2},
                        {"snapshots": (snapshot(),)*17}, {"snapshots": (snapshot(),snapshot())}):
            with self.subTest(changes=list(changes)), self.assertRaises((ValueError, TypeError)):
                catalog(**changes)

    def test_query_filters_spatial_and_time_ranges_without_rewriting_unknown_time(self):
        data = snapshot(records=(event(), event(event_id="unknown", observed_at_ms=None),
                                 event(event_id="outside", longitude_e6=0),
                                 event(event_id="older", observed_at_ms=NOW-20_000)))
        result = catalog(data).call("events.query", query(), now_ms=NOW)
        self.assertEqual([row["event_id"] for row in result["records"]], ["synthetic-1"])
        self.assertEqual(result["unknown_time_records_in_area"], 1)
        self.assertEqual(result["matched_records"], 1)
        self.assertFalse(result["absence_supported"])
        got = catalog(data).call("events.get", {"snapshot_id":data.snapshot_id,"event_id":"unknown"}, now_ms=NOW)
        self.assertIsNone(got["record"]["observed_at_ms"])
        self.assertEqual(got["record"]["observation_freshness"], "unknown")

    def test_truncation_and_deterministic_order(self):
        data = snapshot(records=(event(event_id="b"),event(event_id="a")))
        result = catalog(data).call("events.query", query(limit=1), now_ms=NOW)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["matched_records"], 2)
        self.assertEqual(result["records"][0]["event_id"], "a")

    def test_fresh_collection_does_not_make_old_observation_fresh(self):
        data = snapshot(records=(event(observed_at_ms=NOW-400_000),))
        result = catalog(data).call("events.get", {"snapshot_id":data.snapshot_id,"event_id":"synthetic-1"}, now_ms=NOW)
        self.assertEqual(result["record"]["collection_freshness"], "fresh")
        self.assertEqual(result["record"]["observation_freshness"], "stale")
        future = catalog().call("events.query", query(), now_ms=NOW-2000)
        self.assertEqual(future["sources"][0]["collection_freshness"], "future")

    def test_freshness_inclusive_threshold_and_stale_collection(self):
        c = catalog(max_age_ms=1000)
        for now, expected in ((NOW+1000,"fresh"),(NOW+1001,"stale")):
            self.assertEqual(c.call("events.query", query(), now_ms=now)["sources"][0]["collection_freshness"], expected)

    def test_empty_or_missing_never_claims_no_event_in_the_world(self):
        for coverage in ("partial","complete","unknown"):
            result = catalog(snapshot(coverage=coverage,records=())).call("events.query",query(),now_ms=NOW)
            self.assertEqual(result["records"], [])
            self.assertFalse(result["absence_supported"])
        self.assertIsNone(catalog().call("events.get", {"snapshot_id":"missing","event_id":"missing"},now_ms=NOW)["record"])

    def test_unknown_tools_and_privileged_arguments_are_denied(self):
        c = catalog()
        for name in ("events.publish", "shell", "fetch", "__dict__"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                c.call(name, {}, now_ms=NOW)
        for field in ("tenant_id","source_url","path","now_ms","max_age_ms","commercial_allowed"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                c.call("events.query", {**query(),field:"forged"},now_ms=NOW)

    def test_bad_query_bounds_and_types(self):
        for changes in ({"limit":True}, {"limit":21}, {"start_ms":NOW+1},
                        {"bbox_e6":[0,0,-1,1]}, {"bbox_e6":[0,1,0,0]},
                        {"bbox_e6":[False,0,1,1]}, {"bbox_e6":[0,0,1,1.2]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                catalog().call("events.query",query(**changes),now_ms=NOW)

    def test_results_are_detached_from_internal_state(self):
        c = catalog()
        result = c.call("events.query",query(),now_ms=NOW)
        result["records"][0]["summary"] = "changed"
        result["sources"].clear()
        again = c.call("events.query",query(),now_ms=NOW)
        self.assertEqual(again["records"][0]["summary"],event().summary)
        self.assertEqual(len(again["sources"]),1)

    def test_queries_have_no_network_or_filesystem_effects(self):
        with patch("socket.socket", side_effect=AssertionError("no sockets")), patch("builtins.open", side_effect=AssertionError("no files")):
            c = catalog()
            c.call("events.query", query(), now_ms=NOW)
            c.call("events.get", {"snapshot_id":"snapshot-fixture","event_id":"synthetic-1"}, now_ms=NOW)

    def test_receipt_bridge_is_pending_and_idempotent_in_real_journal(self):
        data = snapshot()
        evidence = data.to_evidence()
        trusted = scope()
        assessment = check_evidence(evidence,trusted)
        self.assertFalse(assessment.supported)
        self.assertIn("review_pending",assessment.reasons)
        self.assertFalse(evidence.identity_verified)
        self.assertEqual(json.loads(evidence.text),data.to_dict())
        with TemporaryDirectory() as tmp:
            journal = Journal(Path(tmp)/"receipts.sqlite3",trusted)
            empty = Checkpoint.empty(trusted)
            kwargs = dict(event_id=data.snapshot_sha256,occurred_at="2026-10-11T00:00:00Z",expected_checkpoint=empty)
            committed = journal.append(evidence,assessment,**kwargs)
            with self.assertRaises(IntegrityError):
                journal.append(evidence,assessment,**kwargs)
            kwargs["expected_checkpoint"] = committed
            replayed = journal.append(evidence,assessment,**kwargs)
            self.assertEqual(replayed,committed)
            self.assertEqual(journal.verify(committed),committed)
            self.assertEqual(len(journal.export_records(committed)),1)


if __name__ == "__main__":
    unittest.main()
