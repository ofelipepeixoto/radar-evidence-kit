# Copyright (c) 2026 Carlos Felipe. SPDX-License-Identifier: MIT
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from radar_evidence import Evidence, Scope
from radar_evidence.occurrences import group_occurrences, occurrence_id
from radar_evidence.research_preview import preview, parse_json


def evidence(**changes):
    text = "Prazo sintético: 30 dias. α🙂"
    return replace(Evidence("tenant-a", "project-a", "doc-a", 1, 1, 0,
                            len(text), text, "a" * 64,
                            hashlib.sha256(text.encode()).hexdigest(),
                            "approved", "synthetic-reviewer", True), **changes)


def scope(**changes):
    return Scope(**({"tenant_id": "tenant-a", "project_id": "project-a",
                    "current_revisions": {"doc-a": 1, "doc-b": 1}} | changes))


class OccurrenceTests(unittest.TestCase):
    def test_same_text_two_sources_survive_one_content_group(self):
        a, b = evidence(), evidence(document_id="doc-b", source_sha256="b" * 64)
        groups = group_occurrences([a, b, a], scope())
        self.assertEqual(len(groups), 1)
        self.assertEqual({item.document_id for item in groups[0].evidence}, {"doc-a", "doc-b"})
        self.assertEqual(len(groups[0].evidence), 2)
        self.assertNotEqual(occurrence_id(a), occurrence_id(b))
        self.assertEqual(groups, group_occurrences([b, a], scope()))

    def test_location_revision_and_source_change_identity(self):
        a = evidence()
        for change in ({"page": 2}, {"start": 1}, {"revision": 2},
                       {"source_sha256": "c" * 64}, {"project_id": "other"},
                       {"tenant_id": "other"}):
            self.assertNotEqual(occurrence_id(a), occurrence_id(replace(a, **change)))

    def test_scope_review_and_revision_exclusion_without_receipt_conflicts(self):
        a = evidence()
        out_of_scope = [replace(a, tenant_id="other"), replace(a, project_id="other"),
                        replace(a, revision=2), replace(a, document_id="unknown")]
        denied_reviews = [replace(a, review_status="pending"), replace(a, review_status="rejected"),
                          replace(a, identity_verified=False), replace(a, reviewer="")]
        for record in [*out_of_scope, *denied_reviews]:
            self.assertEqual(group_occurrences([record], scope()), ())
        self.assertEqual(group_occurrences([a, *out_of_scope], scope())[0].evidence, (a,))

    def test_ineligible_receipt_conflicts_fail_closed_in_both_orders(self):
        a = evidence()
        for change in ({"review_status": "pending"}, {"review_status": "rejected"},
                       {"identity_verified": False}, {"reviewer": ""}):
            b = replace(a, **change)
            self.assertEqual(occurrence_id(a), occurrence_id(b))
            for records in ([a, b], [b, a], [a, b, a]):
                with self.subTest(change=change, receipts=[r.evidence_id for r in records]):
                    with self.assertRaisesRegex(ValueError, "^conflicting occurrence review$"):
                        group_occurrences(records, scope())
                    snapshot = {"schema": "radar-evidence-snapshot-v1",
                                "evidence": [r.to_dict() for r in records]}
                    with self.assertRaisesRegex(ValueError, "^conflicting occurrence review$"):
                        preview(snapshot, scope())

    def test_conflicts_without_an_eligible_occurrence_do_not_poison_other_sources(self):
        a = evidence()
        for change in ({"tenant_id": "other"}, {"project_id": "other"},
                       {"revision": 2}, {"document_id": "unknown"}):
            other = replace(a, **change)
            self.assertEqual(group_occurrences([a, other, replace(other, review_status="rejected")],
                                               scope())[0].evidence, (a,))
        denied = replace(a, review_status="pending")
        rejected = replace(a, review_status="rejected")
        self.assertEqual(group_occurrences([denied, rejected], scope()), ())
        b = evidence(document_id="doc-b", source_sha256="b" * 64)
        self.assertEqual(group_occurrences([b, denied, rejected], scope())[0].evidence, (b,))

    def test_distinct_occurrences_and_exact_replay_remain_independent(self):
        a = evidence()
        for change in ({"page": 2}, {"start": 1}, {"source_sha256": "c" * 64}):
            denied = replace(a, review_status="rejected", **change)
            snapshot = {"schema": "radar-evidence-snapshot-v1",
                        "evidence": [denied.to_dict(), a.to_dict(), a.to_dict()]}
            result = preview(snapshot, scope())
            self.assertEqual((result["includedOccurrences"], result["excludedRecords"],
                              result["duplicateRecords"]), (1, 1, 1))

    def test_content_hash_is_scoped_and_receipt_changes_fail_closed(self):
        a = evidence()
        other = replace(a, tenant_id="other")
        self.assertNotEqual(group_occurrences([a], scope())[0].content_id,
                            group_occurrences([other], scope(tenant_id="other"))[0].content_id)
        with self.assertRaisesRegex(ValueError, "conflicting occurrence review"):
            group_occurrences([a, replace(a, reviewer="different")], scope())

    def test_bounds_and_invalid_records_fail_without_partial_output(self):
        with self.assertRaises(ValueError):
            group_occurrences([evidence()] * 1001, scope())
        with self.assertRaises(TypeError):
            group_occurrences([evidence(), {}], scope())
        with self.assertRaises(ValueError):
            parse_json(b'{"x":1,"x":2}')
        with self.assertRaises(ValueError):
            parse_json(b'{"x":NaN}')
        with self.assertRaises(ValueError):
            parse_json(b" " * (256 * 1024 + 1))

    def test_preview_counts_dedup_and_exclusion_without_generating_claims(self):
        a, b = evidence(), evidence(document_id="doc-b", source_sha256="b" * 64)
        data = {"schema": "radar-evidence-snapshot-v1", "evidence":
                [a.to_dict(), b.to_dict(), a.to_dict(), replace(a, tenant_id="other").to_dict()]}
        result = preview(data, scope())
        self.assertEqual((result["includedOccurrences"], result["excludedRecords"], result["duplicateRecords"]), (2, 1, 1))
        self.assertEqual(result["decision"], "needs_review")
        self.assertFalse(result["paidCallsEnabled"])
        self.assertFalse(result["externalActionsEnabled"])
        self.assertFalse(result["issuerVerified"])
        self.assertEqual(preview({"schema": data["schema"], "evidence": []}, scope())["decision"], "abstained")
        with self.assertRaises(ValueError):
            preview(data | {"action": "shell"}, scope())

    def test_real_cli_unicode_and_sanitized_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "scope.json"
            config.write_text(json.dumps(scope().to_dict()))
            command = [sys.executable, "-m", "radar_evidence.research_preview", "--scope", str(config)]
            data = {"schema": "radar-evidence-snapshot-v1", "evidence": [evidence().to_dict()]}
            run = subprocess.run(command, input=json.dumps(data).encode(), capture_output=True, timeout=5)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)["groups"][0]["occurrences"][0]["quote"], evidence().text)
            run = subprocess.run(command, input=b'{"PRIVATE_BAD_PAYLOAD":1}', capture_output=True, timeout=5)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(run.stdout, b"")
            self.assertEqual(json.loads(run.stderr), {"error": "EVIDENCE_PREVIEW_DENIED"})

    def test_real_cli_conflicting_receipts_emit_no_partial_preview(self):
        a = evidence()
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "scope.json"
            config.write_text(json.dumps(scope().to_dict()))
            command = [sys.executable, "-m", "radar_evidence.research_preview", "--scope", str(config)]
            for change in ({"review_status": "rejected"}, {"review_status": "pending"},
                           {"identity_verified": False}, {"reviewer": ""}):
                b = replace(a, **change)
                for records in ([a, b], [b, a]):
                    data = {"schema": "radar-evidence-snapshot-v1",
                            "evidence": [r.to_dict() for r in records]}
                    run = subprocess.run(command, input=json.dumps(data).encode(),
                                         capture_output=True, timeout=5)
                    self.assertEqual(run.returncode, 2)
                    self.assertEqual(run.stdout, b"")
                    self.assertEqual(run.stderr, b'{"error":"EVIDENCE_PREVIEW_DENIED"}\n')


if __name__ == "__main__":
    unittest.main()
