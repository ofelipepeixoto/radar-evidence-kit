# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Receipt integrity and PROV boundary regressions using synthetic local data."""

from contextlib import closing
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from radar_evidence import Checkpoint, Evidence, EvidenceCheck, IntegrityError, Journal, Scope, check_evidence, export_prov
from radar_evidence.canonical import MAX_BYTES, canonical_bytes
from radar_evidence.ledger import FORMAT, MAX_RECORDS, ZERO


STAMP = "2026-10-03T12:00:00Z"


def evidence(**overrides):
    text = overrides.get("text", "FIXTURE-TEXT café🙂. Original context outside quote.")
    payload = {
        "tenant_id": "tenant-fixture", "project_id": "project-fixture",
        "document_id": "document-fixture", "revision": 2, "page": 1,
        "start": 13, "end": 17, "text": text,
        "source_sha256": hashlib.sha256(b"synthetic source bytes").hexdigest(),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "review_status": "approved", "reviewer": "FIXTURE-REVIEWER-LABEL",
        "identity_verified": True,
    }
    payload.update(overrides)
    return Evidence.from_dict(payload)


def trusted_scope(**overrides):
    data = {"tenant_id": "tenant-fixture", "project_id": "project-fixture",
            "current_revisions": {"document-fixture": 2}}
    data.update(overrides)
    return Scope(**data)


class CanonicalBoundaryTests(unittest.TestCase):
    def test_field_boundary_and_metadata_changes_do_not_collide(self):
        one = {"tenant": "ab", "project": "c", "metadata": {"approved": True}}
        two = {"tenant": "a", "project": "bc", "metadata": {"approved": True}}
        three = {"tenant": "ab", "project": "c", "metadata": {"approved": False}}
        self.assertNotEqual(canonical_bytes(one), canonical_bytes(two))
        self.assertNotEqual(canonical_bytes(one), canonical_bytes(three))

    def test_canonical_order_is_stable_but_array_order_is_protected(self):
        self.assertEqual(canonical_bytes({"b": "é", "a": [True, None, 1]}),
                         canonical_bytes({"a": [True, None, 1], "b": "é"}))
        self.assertNotEqual(canonical_bytes(["a", "b"]), canonical_bytes(["b", "a"]))
        self.assertEqual(canonical_bytes("é"), '"é"'.encode("utf-8"))

    def test_only_plain_json_without_floats_is_accepted(self):
        class DictSubclass(dict):
            pass
        class StringSubclass(str):
            pass
        for value in (1.0, float("nan"), float("inf"), float("-inf"), (), {1: "value"},
                      {"x": object()}, DictSubclass(x=1), StringSubclass("x")):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises((TypeError, ValueError)):
                    canonical_bytes(value)
        self.assertEqual(canonical_bytes([True, False, None, 0]), b"[true,false,null,0]")

    def test_integer_byte_collection_and_depth_limits(self):
        self.assertEqual(canonical_bytes(2**63 - 1), str(2**63 - 1).encode())
        self.assertEqual(canonical_bytes(-(2**63)), str(-(2**63)).encode())
        for value in (2**63, -(2**63) - 1):
            with self.assertRaises(ValueError):
                canonical_bytes(value)
        self.assertEqual(len(canonical_bytes("x" * (MAX_BYTES - 2))), MAX_BYTES)
        with self.assertRaises(ValueError):
            canonical_bytes("x" * (MAX_BYTES - 1))
        self.assertEqual(len(canonical_bytes("é" * ((MAX_BYTES - 2) // 2))), MAX_BYTES)
        with self.assertRaises(ValueError):
            canonical_bytes("é" * (MAX_BYTES // 2))
        self.assertTrue(canonical_bytes([None] * 10000))
        with self.assertRaises(ValueError):
            canonical_bytes([None] * 10001)
        with self.assertRaises(ValueError):
            canonical_bytes({str(index): None for index in range(10001)})
        nested = None
        for _ in range(8):
            nested = [nested]
        self.assertTrue(canonical_bytes(nested))
        with self.assertRaises(ValueError):
            canonical_bytes([nested])

    def test_invalid_unicode_and_cyclic_values_fail(self):
        with self.assertRaises(UnicodeError):
            canonical_bytes("bad\ud800text")
        cyclic = []
        cyclic.append(cyclic)
        with self.assertRaises(ValueError):
            canonical_bytes(cyclic)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="radar-journal-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "receipts.sqlite"
        self.scope = trusted_scope()
        self.journal = Journal(self.path, self.scope)
        self.empty = Checkpoint.empty(self.scope)
        self.item = evidence()

    def append(self, item=None, event_id="fixture-event", checkpoint=None, stamp=STAMP):
        item = item or self.item
        return self.journal.append(item, check_evidence(item, self.scope), event_id=event_id,
                                   occurred_at=stamp, expected_checkpoint=checkpoint or self.empty)

    def rows(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute("SELECT seq, event_id, body, checksum FROM receipts ORDER BY seq").fetchall()

    def set_row(self, row):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("UPDATE receipts SET event_id=?, body=?, checksum=? WHERE seq=?",
                               (row[1], row[2], row[3], row[0]))
            connection.commit()

    def altered(self, mutator, *, rehash=False):
        row = self.rows()[0]
        record = json.loads(row[2])
        mutator(record)
        body = canonical_bytes(record).decode("utf-8")
        checksum = hashlib.sha256(body.encode("utf-8")).hexdigest() if rehash else row[3]
        changed = (row[0], row[1], body, checksum)
        self.set_row(changed)
        return changed

    def test_empty_append_verify_roundtrip_and_restart(self):
        self.assertEqual(self.journal.verify(self.empty), self.empty)
        self.assertEqual(self.journal.export_records(self.empty), [])
        checkpoint = self.append()
        self.assertEqual(checkpoint.count, 1)
        self.assertNotEqual(checkpoint.head, ZERO)
        self.assertEqual(Checkpoint.from_dict(checkpoint.to_dict()), checkpoint)
        restarted = Journal(self.path, self.scope)
        self.assertEqual(restarted.verify(checkpoint), checkpoint)
        record = restarted.export_records(checkpoint)[0]
        self.assertEqual(record["event"]["evidence"], self.item.to_dict())
        self.assertEqual(record["event"]["scope"], self.scope.to_dict())

    def test_full_text_quote_context_review_and_scope_are_protected(self):
        checkpoint = self.append()
        original = self.rows()[0]
        mutations = {
            "quote": lambda r: r["event"]["evidence"].__setitem__("start", 14),
            "text": lambda r: r["event"]["evidence"].__setitem__("text", self.item.text.replace("café", "cafe")),
            "context": lambda r: r["event"]["evidence"].__setitem__("text", self.item.text + " changed context"),
            "review": lambda r: r["event"]["evidence"].__setitem__("review_status", "rejected"),
            "reviewer": lambda r: r["event"]["evidence"].__setitem__("reviewer", "other fixture label"),
            "identity": lambda r: r["event"]["evidence"].__setitem__("identity_verified", False),
            "source": lambda r: r["event"]["evidence"].__setitem__("source_sha256", "a" * 64),
            "revision": lambda r: r["event"]["scope"]["current_revisions"].__setitem__("document-fixture", 3),
            "scope": lambda r: r["event"]["scope"].__setitem__("tenant_id", "different tenant"),
            # Metadata has no accepted event schema; injection is also covered.
            "metadata": lambda r: r["event"].__setitem__("metadata", {"approval": "forged"}),
        }
        for label, mutate in mutations.items():
            with self.subTest(field=label):
                self.set_row(original)
                self.altered(mutate)
                with self.assertRaises(IntegrityError):
                    self.journal.verify(checkpoint)

    def test_rehashed_valid_change_still_fails_retained_external_checkpoint(self):
        checkpoint = self.append()
        changed_evidence = evidence(reviewer="another fixture reviewer")
        changed_check = check_evidence(changed_evidence, self.scope)
        def mutate(record):
            record["event"]["evidence"] = changed_evidence.to_dict()
            record["event"]["check"] = changed_check.to_dict()
        changed = self.altered(mutate, rehash=True)
        self.assertNotEqual(checkpoint.head, changed[3])
        with self.assertRaisesRegex(IntegrityError, "checkpoint"):
            self.journal.verify(checkpoint)

    def test_tail_deletion_is_detected_by_external_checkpoint(self):
        one = self.append()
        two = self.append(event_id="second-event", checkpoint=one)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DELETE FROM receipts WHERE seq=2")
            connection.commit()
        with self.assertRaisesRegex(IntegrityError, "checkpoint"):
            self.journal.verify(two)
        # An earlier checkpoint only proves the earlier prefix. This is why the
        # newest checkpoint must be retained outside the writable database.
        self.assertEqual(self.journal.verify(one), one)

    def test_delete_all_is_detected_against_nonempty_checkpoint(self):
        checkpoint = self.append()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DELETE FROM receipts")
            connection.commit()
        with self.assertRaises(IntegrityError):
            self.journal.verify(checkpoint)

    def test_middle_deletion_reordering_and_previous_link_fail(self):
        one = self.append()
        two = self.append(event_id="second-event", checkpoint=one)
        originals = self.rows()
        # Swap contents between stable sequence numbers, avoiding unique-ID
        # collision while retaining the original bodies/checksums.
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DELETE FROM receipts")
            connection.executemany("INSERT INTO receipts VALUES (?, ?, ?, ?)",
                                   [(1, *originals[1][1:]), (2, *originals[0][1:])])
            connection.commit()
        with self.assertRaisesRegex(IntegrityError, "chain"):
            self.journal.verify(two)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DELETE FROM receipts")
            connection.executemany("INSERT INTO receipts VALUES (?, ?, ?, ?)", originals)
            connection.execute("DELETE FROM receipts WHERE seq=1")
            connection.commit()
        with self.assertRaisesRegex(IntegrityError, "sequence"):
            self.journal.verify(two)

    def test_previous_link_sequence_bool_checksum_and_event_index_tampering_fail(self):
        checkpoint = self.append()
        original = self.rows()[0]
        mutations = [lambda r: r.__setitem__("previous", "f" * 64),
                     lambda r: r.__setitem__("sequence", True)]
        for mutate in mutations:
            self.set_row(original)
            self.altered(mutate, rehash=True)
            with self.assertRaises(IntegrityError):
                self.journal.verify(checkpoint)
        self.set_row((original[0], original[1], original[2], "f" * 64))
        with self.assertRaises(IntegrityError):
            self.journal.verify(checkpoint)
        self.set_row((original[0], "different-event-id", original[2], original[3]))
        with self.assertRaisesRegex(IntegrityError, "scope"):
            self.journal.verify(checkpoint)

    def test_identical_replay_is_idempotent_across_restart(self):
        checkpoint = self.append()
        self.journal = Journal(self.path, self.scope)
        again = self.append(checkpoint=checkpoint)
        self.assertEqual(again, checkpoint)
        self.assertEqual(len(self.rows()), 1)

    def test_stale_checkpoint_replay_does_not_advance_authority(self):
        checkpoint = self.append()
        with self.assertRaisesRegex(IntegrityError, "checkpoint"):
            self.append(checkpoint=self.empty)
        self.assertEqual(self.journal.verify(checkpoint), checkpoint)

    def test_event_id_collision_rejects_new_content_and_keeps_original(self):
        checkpoint = self.append()
        with self.assertRaisesRegex(IntegrityError, "event ID"):
            self.append(evidence(review_status="rejected"), checkpoint=checkpoint)
        with self.assertRaisesRegex(IntegrityError, "event ID"):
            self.append(checkpoint=checkpoint, stamp="2026-10-03T12:00:01Z")
        self.assertEqual(self.journal.verify(checkpoint), checkpoint)
        self.assertEqual(len(self.rows()), 1)

    def test_real_sqlite_insert_failure_rolls_back_and_can_retry(self):
        checkpoint = self.append()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TRIGGER block_second BEFORE INSERT ON receipts WHEN NEW.seq=2 BEGIN SELECT RAISE(ABORT, 'fixture insertion blocked'); END")
            connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.append(event_id="second-event", checkpoint=checkpoint)
        self.assertEqual(self.journal.verify(checkpoint), checkpoint)
        self.assertEqual(len(self.rows()), 1)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DROP TRIGGER block_second")
            connection.commit()
        updated = self.append(event_id="second-event", checkpoint=checkpoint)
        self.assertEqual(updated.count, 2)

    def test_two_operators_cannot_append_from_same_stale_head(self):
        other = Journal(self.path, self.scope)
        checkpoint = self.append()
        with self.assertRaisesRegex(IntegrityError, "checkpoint"):
            other.append(self.item, check_evidence(self.item, self.scope), event_id="other operator",
                         occurred_at=STAMP, expected_checkpoint=self.empty)
        self.assertEqual(self.journal.verify(checkpoint), checkpoint)

    def test_cross_tenant_and_project_rejected_even_as_unsupported_attempt(self):
        for overrides in ({"tenant_id": "tenant-other"}, {"project_id": "project-other"}):
            with self.subTest(overrides=overrides):
                item = evidence(**overrides)
                self.assertFalse(check_evidence(item, self.scope).supported)
                with self.assertRaisesRegex(ValueError, "cross-scope"):
                    self.append(item)
                self.assertEqual(self.journal.verify(self.empty), self.empty)
                self.assertEqual(self.rows(), [])

    def test_foreign_checkpoint_or_database_scope_cannot_be_reused(self):
        checkpoint = self.append()
        other_scope = trusted_scope(tenant_id="tenant-other")
        with self.assertRaises(IntegrityError):
            self.journal.verify(Checkpoint.empty(other_scope))
        other = Journal(self.path, other_scope)
        with self.assertRaises(IntegrityError):
            other.verify(Checkpoint(other_scope.tenant_id, other_scope.project_id, 1, checkpoint.head))

    def test_check_must_equal_strict_assessment_not_relaxed_or_forged(self):
        item = evidence(identity_verified=False)
        relaxed = check_evidence(item, self.scope, require_verified_review=False)
        self.assertTrue(relaxed.supported)
        with self.assertRaises(ValueError):
            self.journal.append(item, relaxed, event_id="relaxed", occurred_at=STAMP,
                                expected_checkpoint=self.empty)
        forged = EvidenceCheck(True, (), "a" * 64)
        with self.assertRaises(ValueError):
            self.journal.append(self.item, forged, event_id="forged", occurred_at=STAMP,
                                expected_checkpoint=self.empty)
        self.assertEqual(self.rows(), [])

    def test_ineligible_same_scope_is_recorded_as_ineligible(self):
        item = evidence(review_status="pending", reviewer="", identity_verified=False)
        checkpoint = self.append(item)
        event = self.journal.export_records(checkpoint)[0]["event"]
        self.assertFalse(event["check"]["supported"])
        self.assertEqual(event["check"]["reasons"], ["review_pending", "reviewer_identity_unverified"])

    def test_stored_schema_and_scope_revalidated_even_with_new_matching_hash(self):
        checkpoint = self.append()
        original = self.rows()[0]
        def wrong_scope(record):
            item = evidence(tenant_id="tenant-other")
            record["event"]["evidence"] = item.to_dict()
            record["event"]["check"] = check_evidence(item, self.scope).to_dict()
        changes = [lambda r: r["event"].__setitem__("metadata", {"untrusted": True}),
                   lambda r: r["event"]["evidence"].__setitem__("quote", "injected"),
                   lambda r: r["event"]["check"].__setitem__("supported", 1),
                   lambda r: r["event"].__setitem__("occurred_at", "2026-02-29T00:00:00Z"),
                   wrong_scope]
        for index, mutate in enumerate(changes):
            with self.subTest(case=index):
                self.set_row(original)
                changed = self.altered(mutate, rehash=True)
                replacement_head = replace(checkpoint, head=changed[3])
                with self.assertRaises(IntegrityError):
                    self.journal.verify(replacement_head)

    def test_noncanonical_duplicate_keys_and_invalid_json_are_rejected(self):
        checkpoint = self.append()
        original = self.rows()[0]
        bodies = ["{invalid-json}", original[2].replace('"sequence":1', '"sequence":1,"sequence":1'),
                  json.dumps(json.loads(original[2]), indent=2), "[]", "x" * (MAX_BYTES + 1)]
        for body in bodies:
            with self.subTest(bytes=len(body.encode("utf-8"))):
                checksum = hashlib.sha256(body.encode("utf-8")).hexdigest()
                self.set_row((original[0], original[1], body, checksum))
                with self.assertRaises(IntegrityError):
                    self.journal.verify(replace(checkpoint, head=checksum))

    def test_strict_timestamp_event_id_and_argument_types_fail_without_write(self):
        bad_stamps = ["2026-02-29T00:00:00Z", "2026-10-03T24:00:00Z", "2026-10-03T12:00:60Z",
                      "2026-10-03T12:00:00+00:00", "2026-10-03T12:00:00.000Z",
                      "2026-10-03 12:00:00Z", "2026-10-03T12:00:00z", 0, True, None]
        for stamp in bad_stamps:
            with self.subTest(stamp=stamp):
                with self.assertRaises(ValueError):
                    self.append(stamp=stamp)
        for event_id in ("", " \t", "é" * 513, True, 1, None):
            with self.subTest(event_id=event_id):
                with self.assertRaises(ValueError):
                    self.append(event_id=event_id)
        for checkpoint in (None, self.empty.to_dict(), True):
            with self.subTest(checkpoint_type=type(checkpoint).__name__):
                with self.assertRaises(TypeError):
                    self.journal.append(self.item, check_evidence(self.item, self.scope), event_id="bad checkpoint",
                                        occurred_at=STAMP, expected_checkpoint=checkpoint)
        self.assertEqual(self.rows(), [])
        accepted = self.append(stamp="2024-02-29T00:00:00Z", event_id="é" * 512)
        self.assertEqual(accepted.count, 1)

    def test_capacity_failure_preserves_previous_checkpoint(self):
        # Lower the policy limit for a real SQLite test without quadratic work
        # over 1,000 receipts. MAX_RECORDS remains a production constant.
        with patch("radar_evidence.ledger.MAX_RECORDS", 2):
            one = self.append()
            two = self.append(event_id="second-event", checkpoint=one)
            with self.assertRaisesRegex(IntegrityError, "capacity"):
                self.append(event_id="third-event", checkpoint=two)
            self.assertEqual(self.journal.verify(two), two)
            self.assertEqual(len(self.rows()), 2)

    def test_record_byte_limit_failure_does_not_write(self):
        many_revisions = {f"doc-{index:04d}-" + "x" * 80: 1 for index in range(1000)}
        many_revisions["document-fixture"] = 2
        large_scope = trusted_scope(current_revisions=many_revisions)
        large = Journal(self.path, large_scope)
        with self.assertRaisesRegex(ValueError, "64 KiB"):
            large.append(self.item, check_evidence(self.item, large_scope), event_id="large scope",
                         occurred_at=STAMP, expected_checkpoint=Checkpoint.empty(large_scope))
        self.assertEqual(self.rows(), [])

    def test_exported_records_are_detached_from_persisted_receipts(self):
        checkpoint = self.append()
        records = self.journal.export_records(checkpoint)
        records[0]["event"]["evidence"]["review_status"] = "rejected"
        self.assertEqual(self.journal.verify(checkpoint), checkpoint)
        self.assertEqual(self.journal.export_records(checkpoint)[0]["event"]["evidence"]["review_status"], "approved")


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_strict_types_shape_and_empty_state(self):
        data = Checkpoint.empty(trusted_scope()).to_dict()
        for override in ({"count": True}, {"count": 1.0}, {"count": -1}, {"count": MAX_RECORDS + 1},
                         {"head": "A" * 64}, {"head": "g" * 64}, {"head": "a" * 64},
                         {"format": "unknown"}, {"tenant_id": ""}, {"project_id": False},
                         {"unexpected": "fixture"}):
            with self.subTest(override=override):
                with self.assertRaises((TypeError, ValueError)):
                    Checkpoint.from_dict(data | override)
        with self.assertRaises(ValueError):
            Checkpoint.from_dict({key: value for key, value in data.items() if key != "format"})
        with self.assertRaises(TypeError):
            Checkpoint.empty(trusted_scope().to_dict())
        with self.assertRaises(ValueError):
            Checkpoint("tenant-fixture", "project-fixture", 1, ZERO)


class ProvMappingTests(unittest.TestCase):
    setUp = JournalTests.setUp
    append = JournalTests.append
    rows = JournalTests.rows
    set_row = JournalTests.set_row

    def test_association_belongs_to_activity_and_uses_correct_agent(self):
        checkpoint = self.append()
        exported = export_prov(self.journal, checkpoint)
        activities = [node for node in exported["@graph"] if node["@type"] == "prov:Activity"]
        entities = [node for node in exported["@graph"] if node["@type"] == "prov:Entity"]
        agents = [node for node in exported["@graph"] if node["@type"] == "prov:Agent"]
        self.assertEqual((len(activities), len(entities), len(agents)), (1, 1, 1))
        association = activities[0]["prov:qualifiedAssociation"]
        self.assertEqual(association["@type"], "prov:Association")
        self.assertEqual(association["prov:agent"], {"@id": agents[0]["@id"]})
        self.assertIs(association["radar:identityVerified"], True)
        self.assertNotIn("prov:qualifiedAssociation", entities[0])
        self.assertEqual(activities[0]["prov:used"], {"@id": entities[0]["@id"]})
        self.assertEqual(activities[0]["prov:endedAtTime"], {"@value": STAMP, "@type": "xsd:dateTime"})

    def test_export_omits_text_quote_reviewer_and_raw_scope_labels(self):
        checkpoint = self.append()
        serialized = json.dumps(export_prov(self.journal, checkpoint), ensure_ascii=False)
        for value in (self.item.text, self.item.quote, self.item.reviewer, self.item.tenant_id,
                      self.item.project_id, self.item.document_id):
            with self.subTest(value=value):
                self.assertNotIn(value, serialized)
        self.assertNotIn('"text"', serialized)
        self.assertNotIn('"reviewer"', serialized)

    def test_inline_context_has_no_remote_context_or_io(self):
        checkpoint = self.append()
        with patch("socket.socket", side_effect=AssertionError("network socket")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("HTTP request")), \
             patch("subprocess.run", side_effect=AssertionError("process execution")):
            exported = export_prov(self.journal, checkpoint)
        self.assertIs(type(exported["@context"]), dict)
        self.assertEqual(exported["@context"], {"prov": "http://www.w3.org/ns/prov#",
                         "xsd": "http://www.w3.org/2001/XMLSchema#", "radar": "urn:radar:terms:"})
        self.assertFalse(any("@context" in node for node in exported["@graph"]))

    def test_unverified_flag_does_not_become_true_in_export(self):
        checkpoint = self.append(evidence(identity_verified=False))
        activity = next(node for node in export_prov(self.journal, checkpoint)["@graph"]
                        if node["@type"] == "prov:Activity")
        self.assertIs(activity["radar:supported"], False)
        self.assertIs(activity["prov:qualifiedAssociation"]["radar:identityVerified"], False)

    def test_blank_reviewer_pending_has_no_invented_agent_or_association(self):
        checkpoint = self.append(evidence(review_status="pending", reviewer="", identity_verified=False))
        graph = export_prov(self.journal, checkpoint)["@graph"]
        self.assertFalse(any(node["@type"] == "prov:Agent" for node in graph))
        activity = next(node for node in graph if node["@type"] == "prov:Activity")
        self.assertNotIn("prov:qualifiedAssociation", activity)
        self.assertIs(activity["radar:supported"], False)

    def test_entities_deduplicate_but_receipt_activities_remain_distinct(self):
        one = self.append()
        two = self.append(event_id="second-event", checkpoint=one)
        exported = export_prov(self.journal, two)
        kinds = [node["@type"] for node in exported["@graph"]]
        self.assertEqual(kinds.count("prov:Entity"), 1)
        self.assertEqual(kinds.count("prov:Agent"), 1)
        self.assertEqual(kinds.count("prov:Activity"), 2)
        self.assertEqual(exported, export_prov(self.journal, two))
        ids = [node["@id"] for node in exported["@graph"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_tampered_receipt_cannot_be_exported_and_wrong_types_rejected(self):
        checkpoint = self.append()
        original = self.rows()[0]
        self.set_row((original[0], original[1], original[2], "f" * 64))
        with self.assertRaises(IntegrityError):
            export_prov(self.journal, checkpoint)
        with self.assertRaises(TypeError):
            export_prov({}, checkpoint)


@unittest.skipUnless(os.name == "posix", "POSIX ownership and mode contract")
class JournalFileModeTests(unittest.TestCase):
    def test_new_journal_is_private_even_with_default_umask(self):
        with TemporaryDirectory(prefix="radar-filemode-test-") as directory:
            path = Path(directory) / "private.sqlite"
            original = os.umask(0o022)
            try:
                journal = Journal(path, trusted_scope())
            finally:
                os.umask(original)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(journal.verify(Checkpoint.empty(trusted_scope())).count, 0)

    def test_existing_readable_file_rejected_without_chmod_or_truncation(self):
        with TemporaryDirectory(prefix="radar-filemode-test-") as directory:
            path = Path(directory) / "public.sqlite"
            path.write_bytes(b"fixture sentinel bytes")
            path.chmod(0o644)
            with self.assertRaises((ValueError, PermissionError)):
                Journal(path, trusted_scope())
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            self.assertEqual(path.read_bytes(), b"fixture sentinel bytes")

    def test_symlink_rejected_without_touching_target(self):
        with TemporaryDirectory(prefix="radar-filemode-test-") as directory:
            target = Path(directory) / "target.sqlite"
            target.write_bytes(b"fixture target untouched")
            target.chmod(0o600)
            link = Path(directory) / "link.sqlite"
            link.symlink_to(target)
            with self.assertRaises((ValueError, PermissionError)):
                Journal(link, trusted_scope())
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), b"fixture target untouched")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
