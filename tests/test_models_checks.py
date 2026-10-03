# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Contract regression tests; no network, files, models, or external services."""

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import unittest

from radar_evidence.checks import EvidenceCheck, check_evidence
from radar_evidence.modelos import (
    Evidence, MAX_IDENTIFIER_CHARS, MAX_SCOPE_DOCUMENTS, MAX_TEXT_BYTES, Scope,
)


def fixture(**overrides):
    text = overrides.get("text", "α🙂 café. Contexto completo.")
    payload = {
        "tenant_id": "tenant-alpha", "project_id": "project-eval",
        "document_id": "document-fixture", "revision": 3, "page": 2,
        "start": 3, "end": 7, "text": text,
        "source_sha256": hashlib.sha256(b"fixture source bytes").hexdigest(),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "review_status": "approved", "reviewer": "trusted operator label",
        "identity_verified": True,
    }
    payload.update(overrides)
    return payload


def scope(**overrides):
    kwargs = {
        "tenant_id": "tenant-alpha", "project_id": "project-eval",
        "current_revisions": {"document-fixture": 3},
    }
    kwargs.update(overrides)
    return Scope(**kwargs)


class EvidenceContractTests(unittest.TestCase):
    def test_complete_record_roundtrip_and_unicode_span(self):
        evidence = Evidence.from_dict(fixture())
        self.assertEqual(evidence.quote, "café")
        self.assertEqual(Evidence.from_dict(evidence.to_dict()), evidence)
        self.assertEqual(len(evidence.evidence_id), 64)
        # Emoji occupies one code point but four UTF-8 bytes.
        emoji = Evidence.from_dict(fixture(start=1, end=2))
        self.assertEqual(emoji.quote, "🙂")

    def test_evidence_id_uses_entire_canonical_record(self):
        evidence = Evidence.from_dict(fixture())
        encoded = json.dumps(evidence.to_dict(), sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.assertEqual(evidence.evidence_id, hashlib.sha256(encoded).hexdigest())
        reverse_order = dict(reversed(list(fixture().items())))
        self.assertEqual(Evidence.from_dict(reverse_order).evidence_id, evidence.evidence_id)

    def test_every_serialized_field_changes_identity(self):
        base = Evidence.from_dict(fixture())
        changes = {
            "tenant_id": "tenant-beta", "project_id": "project-other",
            "document_id": "document-other", "revision": 4, "page": 3,
            "start": 4, "end": 8, "source_sha256": "a" * 64,
            "review_status": "pending", "reviewer": "other operator",
            "identity_verified": False,
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                changed = Evidence.from_dict(fixture(**{field: value}))
                self.assertNotEqual(changed.evidence_id, base.evidence_id)
        # text and its digest change together because mismatched digests fail.
        changed = Evidence.from_dict(fixture(text=base.text + " Contexto extra."))
        self.assertEqual(changed.quote, base.quote)
        self.assertNotEqual(changed.text_sha256, base.text_sha256)
        self.assertNotEqual(changed.evidence_id, base.evidence_id)

    def test_review_fields_are_not_excluded_from_identity(self):
        base = Evidence.from_dict(fixture())
        for overrides in ({"review_status": "rejected"}, {"reviewer": "different label"},
                          {"identity_verified": False}):
            with self.subTest(overrides=overrides):
                changed = Evidence.from_dict(fixture(**overrides))
                self.assertEqual(changed.quote, base.quote)
                self.assertNotEqual(changed.evidence_id, base.evidence_id)

    def test_ambiguous_prefix_concatenation_does_not_collide(self):
        first = Evidence.from_dict(fixture(tenant_id="ab", project_id="c"))
        second = Evidence.from_dict(fixture(tenant_id="a", project_id="bc"))
        self.assertNotEqual(first.evidence_id, second.evidence_id)

    def test_full_context_hash_rejects_changed_outside_quote(self):
        original = fixture()
        original["text"] += " changed outside citation"
        with self.assertRaisesRegex(ValueError, "complete text"):
            Evidence.from_dict(original)

    def test_hash_of_quote_instead_of_full_text_is_rejected(self):
        original = fixture()
        quote = original["text"][original["start"]:original["end"]]
        original["text_sha256"] = hashlib.sha256(quote.encode("utf-8")).hexdigest()
        with self.assertRaises(ValueError):
            Evidence.from_dict(original)

    def test_shortened_context_changes_identity_even_when_quote_survives(self):
        base = Evidence.from_dict(fixture())
        truncated = Evidence.from_dict(fixture(text=base.text[:-1]))
        self.assertEqual(truncated.quote, base.quote)
        self.assertNotEqual(truncated.evidence_id, base.evidence_id)

    def test_unknown_or_missing_fields_fail_closed(self):
        for field in Evidence.FIELDS:
            with self.subTest(missing=field):
                payload = fixture()
                del payload[field]
                with self.assertRaises(ValueError):
                    Evidence.from_dict(payload)
        for unknown in ("quote", "evidence_id", "tenant", "approval_token", "__class__"):
            with self.subTest(unknown=unknown):
                payload = fixture() | {unknown: "fixture"}
                with self.assertRaises(ValueError):
                    Evidence.from_dict(payload)

    def test_plain_dictionary_and_string_field_names_required(self):
        class DictSubclass(dict):
            pass
        for payload in (list(fixture().items()), DictSubclass(fixture()), fixture() | {1: "x"}):
            with self.subTest(kind=type(payload).__name__):
                with self.assertRaises(TypeError):
                    Evidence.from_dict(payload)

    def test_integer_types_are_strict(self):
        for field in ("revision", "page", "start", "end"):
            for value in (True, False, 1.0, float("nan"), float("inf"), "1", None):
                with self.subTest(field=field, kind=type(value).__name__, value=value):
                    with self.assertRaises(TypeError):
                        Evidence.from_dict(fixture(**{field: value}))

    def test_numeric_ranges_and_truncated_span_rejected(self):
        cases = ({"revision": 0}, {"revision": -1}, {"page": 0}, {"page": -1},
                 {"start": -1}, {"end": 0}, {"start": 7, "end": 7},
                 {"start": 8, "end": 7}, {"end": 999}, {"text": "c", "end": 7})
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    Evidence.from_dict(fixture(**overrides))

    def test_utf8_byte_limit_includes_multibyte_characters(self):
        for text in ("a" * MAX_TEXT_BYTES, "🙂" * (MAX_TEXT_BYTES // 4)):
            with self.subTest(bytes=len(text.encode("utf-8"))):
                self.assertEqual(Evidence.from_dict(fixture(text=text, start=0, end=len(text))).text, text)
        for text in ("a" * (MAX_TEXT_BYTES + 1), "🙂" * (MAX_TEXT_BYTES // 4 + 1)):
            with self.subTest(bytes=len(text.encode("utf-8"))):
                with self.assertRaisesRegex(ValueError, "16 KiB"):
                    Evidence.from_dict(fixture(text=text, start=0, end=1))

    def test_invalid_unicode_is_rejected_without_echoing_text(self):
        payload = fixture()
        payload["text"] = "bad\ud800text"
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            Evidence.from_dict(payload)
        for field in ("tenant_id", "project_id", "document_id", "reviewer"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "UTF-8"):
                    Evidence.from_dict(fixture(**{field: "\udfff"}))

    def test_hash_format_and_mismatched_digest_fail(self):
        for field in ("source_sha256", "text_sha256"):
            for value in ("A" * 64, "g" * 64, "a" * 63, "a" * 65, "a" * 64 + "\n", 123, None):
                with self.subTest(field=field, value=value):
                    with self.assertRaises((TypeError, ValueError)):
                        Evidence.from_dict(fixture(**{field: value}))
        with self.assertRaisesRegex(ValueError, "complete text"):
            Evidence.from_dict(fixture(text_sha256="0" * 64))

    def test_string_fields_and_identity_flag_are_strict(self):
        for field in ("tenant_id", "project_id", "document_id", "text", "review_status", "reviewer"):
            for value in (None, 1, True, [], {}):
                with self.subTest(field=field, kind=type(value).__name__):
                    payload = fixture()
                    payload[field] = value
                    with self.assertRaises(TypeError):
                        Evidence.from_dict(payload)
        for value in (0, 1, "true", "false", None, float("nan")):
            with self.subTest(identity=value):
                with self.assertRaises(TypeError):
                    Evidence.from_dict(fixture(identity_verified=value))

    def test_blank_scope_identifiers_and_review_limits(self):
        for field in ("tenant_id", "project_id", "document_id"):
            for value in ("", " \t\n"):
                with self.subTest(field=field):
                    with self.assertRaises(ValueError):
                        Evidence.from_dict(fixture(**{field: value}))
        for value in ("Approved", "approve", "", "approved "):
            with self.subTest(status=value):
                with self.assertRaises(ValueError):
                    Evidence.from_dict(fixture(review_status=value))
        Evidence.from_dict(fixture(reviewer="é" * 100))
        with self.assertRaises(ValueError):
            Evidence.from_dict(fixture(reviewer="é" * 101))

    def test_identifier_limits_count_unicode_code_points(self):
        for field in ("tenant_id", "project_id", "document_id"):
            with self.subTest(field=field):
                Evidence.from_dict(fixture(**{field: "é" * MAX_IDENTIFIER_CHARS}))
                with self.assertRaises(ValueError):
                    Evidence.from_dict(fixture(**{field: "é" * (MAX_IDENTIFIER_CHARS + 1)}))

    def test_direct_constructor_has_same_guards(self):
        with self.assertRaises(TypeError):
            Evidence(**fixture(page=True))
        with self.assertRaises(ValueError):
            Evidence(**fixture(text_sha256="0" * 64))

    def test_evidence_is_frozen_and_serialization_detached(self):
        evidence = Evidence.from_dict(fixture())
        with self.assertRaises(FrozenInstanceError):
            evidence.review_status = "rejected"
        payload = evidence.to_dict()
        payload["review_status"] = "rejected"
        self.assertEqual(evidence.review_status, "approved")


class ScopeContractTests(unittest.TestCase):
    def test_bindings_are_copied_and_read_only(self):
        revisions = {"document-fixture": 3}
        trusted = scope(current_revisions=revisions)
        revisions["document-fixture"] = 4
        self.assertEqual(trusted.current_revisions["document-fixture"], 3)
        with self.assertRaises(TypeError):
            trusted.current_revisions["document-fixture"] = 5
        with self.assertRaises(FrozenInstanceError):
            trusted.tenant_id = "tenant-other"
        serialized = trusted.to_dict()
        serialized["current_revisions"]["document-fixture"] = 10
        self.assertEqual(trusted.current_revisions["document-fixture"], 3)
        self.assertEqual(Scope.from_dict(trusted.to_dict()), trusted)
        json.dumps(trusted.to_dict())

    def test_revision_bindings_are_strict(self):
        for revisions in ([], None, {"": 1}, {"   ": 1}, {1: 1}, {"d": True},
                          {"d": 0}, {"d": -1}, {"d": 1.0}, {"d": float("nan")}):
            with self.subTest(revisions=revisions):
                with self.assertRaises((TypeError, ValueError)):
                    scope(current_revisions=revisions)

    def test_scope_serialization_rejects_authority_extras(self):
        payload = scope().to_dict()
        with self.assertRaises(ValueError):
            Scope.from_dict(payload | {"allow_all": True})
        with self.assertRaises(ValueError):
            Scope.from_dict({"tenant_id": "t", "project_id": "p"})
        with self.assertRaises(TypeError):
            Scope.from_dict(payload | {1: "unexpected"})

    def test_scope_identifier_and_document_count_limits(self):
        revisions = {f"doc-{index}": 1 for index in range(MAX_SCOPE_DOCUMENTS)}
        self.assertEqual(len(scope(current_revisions=revisions).current_revisions), MAX_SCOPE_DOCUMENTS)
        revisions["one-extra-document"] = 1
        with self.assertRaises(ValueError):
            scope(current_revisions=revisions)
        for kwargs in ({"tenant_id": "x" * 257}, {"project_id": "x" * 257},
                       {"current_revisions": {"x" * 257: 1}}):
            with self.subTest(fields=list(kwargs)):
                with self.assertRaises(ValueError):
                    scope(**kwargs)


class EvidenceCheckTests(unittest.TestCase):
    def test_approved_current_verified_record_supported(self):
        evidence = Evidence.from_dict(fixture())
        result = check_evidence(evidence, scope())
        self.assertTrue(result.supported)
        self.assertEqual(result.reasons, ())
        self.assertEqual(result.evidence_id, evidence.evidence_id)
        self.assertEqual(result.to_dict()["reasons"], [])

    def test_wrong_tenant_and_project_rejected_without_authority_from_record(self):
        evidence = Evidence.from_dict(fixture(tenant_id="tenant-forged", project_id="project-forged"))
        result = check_evidence(evidence, scope())
        self.assertFalse(result.supported)
        self.assertEqual(result.reasons, ("tenant_scope_mismatch", "project_scope_mismatch"))

    def test_missing_stale_and_future_revision_rejected(self):
        for revision in (2, 4):
            with self.subTest(revision=revision):
                result = check_evidence(Evidence.from_dict(fixture(revision=revision)), scope())
                self.assertEqual(result.reasons, ("stale_revision",))
        result = check_evidence(Evidence.from_dict(fixture(document_id="unknown")), scope())
        self.assertEqual(result.reasons, ("unknown_document",))

    def test_pending_and_rejected_cannot_bypass_with_verified_flag(self):
        for review_status in ("pending", "rejected"):
            with self.subTest(status=review_status):
                evidence = Evidence.from_dict(fixture(review_status=review_status, reviewer="", identity_verified=True))
                result = check_evidence(evidence, scope(), require_verified_review=False)
                self.assertFalse(result.supported)
                self.assertEqual(result.reasons, (f"review_{review_status}",))

    def test_unverified_review_cannot_be_promoted_by_truthiness(self):
        evidence = Evidence.from_dict(fixture(identity_verified=False))
        result = check_evidence(evidence, scope())
        self.assertFalse(result.supported)
        self.assertEqual(result.reasons, ("reviewer_identity_unverified",))
        self.assertTrue(check_evidence(evidence, scope(), require_verified_review=False).supported)

    def test_approved_requires_reviewer_label_even_when_identity_check_disabled(self):
        for reviewer in ("", " \t"):
            for verified_check in (True, False):
                with self.subTest(reviewer=reviewer, verified_check=verified_check):
                    result = check_evidence(Evidence.from_dict(fixture(reviewer=reviewer)), scope(), verified_check)
                    self.assertEqual(result.reasons, ("missing_reviewer",))
                    self.assertFalse(result.supported)

    def test_multiple_reasons_are_stable_and_no_input_content_is_echoed(self):
        evidence = Evidence.from_dict(fixture(tenant_id="wrong", project_id="wrong", revision=1,
                                              review_status="pending", identity_verified=False))
        result = check_evidence(evidence, scope())
        self.assertEqual(result.reasons, ("tenant_scope_mismatch", "project_scope_mismatch",
                                         "stale_revision", "review_pending", "reviewer_identity_unverified"))
        self.assertNotIn(evidence.text, json.dumps(result.to_dict()))

    def test_invalid_arguments_and_boolean_switch_rejected(self):
        evidence = Evidence.from_dict(fixture())
        with self.assertRaises(TypeError):
            check_evidence(evidence.to_dict(), scope())
        with self.assertRaises(TypeError):
            check_evidence(evidence, scope().to_dict())
        for value in (0, 1, "false", None):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    check_evidence(evidence, scope(), value)

    def test_check_revalidates_record_if_frozen_guard_was_bypassed(self):
        evidence = Evidence.from_dict(fixture())
        object.__setattr__(evidence, "text", evidence.text + " modified")
        with self.assertRaisesRegex(ValueError, "complete text"):
            check_evidence(evidence, scope())

    def test_result_contract_prevents_contradictions_and_unknown_reason_codes(self):
        valid_id = Evidence.from_dict(fixture()).evidence_id
        for supported, reasons, evidence_id in ((1, (), valid_id), (True, [], valid_id),
                (True, ("stale_revision",), valid_id), (False, (), valid_id),
                (False, ("unknown_code",), valid_id),
                (False, ("stale_revision", "stale_revision"), valid_id),
                (False, (1,), valid_id), (True, (), "A" * 64)):
            with self.subTest(supported=supported, reasons=reasons):
                with self.assertRaises((TypeError, ValueError)):
                    EvidenceCheck(supported, reasons, evidence_id)
        result = EvidenceCheck(False, ("stale_revision",), valid_id)
        with self.assertRaises(FrozenInstanceError):
            result.supported = True

    def test_constructor_replace_revalidates_contract(self):
        evidence = Evidence.from_dict(fixture())
        with self.assertRaises(ValueError):
            replace(evidence, end=len(evidence.text) + 1)
        with self.assertRaises(TypeError):
            replace(evidence, identity_verified=1)


if __name__ == "__main__":
    unittest.main()
