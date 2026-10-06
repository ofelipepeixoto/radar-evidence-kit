# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
from dataclasses import replace
from hashlib import sha256
import unittest

from radar_evidence import (
    Citation, Evidence, Scope, make_citation, resolve_citation, split_evidence,
)


def page(text="α🙂 café. Contexto completo.", **overrides):
    record = dict(
        tenant_id="fixture", project_id="local", document_id="doc-1",
        revision=2, page=1, start=0, end=len(text), text=text,
        source_sha256=sha256(b"synthetic PDF").hexdigest(),
        text_sha256=sha256(text.encode()).hexdigest(),
        review_status="approved", reviewer="fixture", identity_verified=True,
    )
    return Evidence(**(record | overrides))


class CitationTests(unittest.TestCase):
    def setUp(self):
        self.parent = page()
        self.scope = Scope("fixture", "local", {"doc-1": 2})
        self.citation = make_citation(self.parent, 1, 7)

    def test_unicode_roundtrip_preserves_complete_context_and_identity(self):
        citation = Citation.from_dict(self.citation.to_dict())
        resolved = resolve_citation(citation, self.parent, self.scope)
        self.assertEqual(resolved.quote, "🙂 café")
        self.assertEqual(resolved.text, self.parent.text)
        self.assertEqual(resolved.text_sha256, self.parent.text_sha256)
        self.assertEqual(resolved.source_sha256, self.parent.source_sha256)
        self.assertNotEqual(resolved.evidence_id, self.parent.evidence_id)
        self.assertTrue(resolved.identity_verified)

    def test_changed_full_context_invalidates_reference_even_with_same_quote(self):
        changed = page(self.parent.text + " Outra cláusula.")
        with self.assertRaisesRegex(ValueError, "complete parent"):
            resolve_citation(self.citation, changed, self.scope)

    def test_changed_source_or_review_invalidates_reference(self):
        for fields in ({"source_sha256": "a" * 64}, {"reviewer": "different"},
                       {"identity_verified": False}, {"page": 2}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                resolve_citation(self.citation, replace(self.parent, **fields), self.scope)

    def test_forged_quote_hash_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_citation(replace(self.citation, quote_sha256="a" * 64), self.parent, self.scope)

    def test_stale_or_foreign_scope_never_resolves(self):
        for scope in (Scope("foreign", "local", {"doc-1": 2}),
                      Scope("fixture", "foreign", {"doc-1": 2}),
                      Scope("fixture", "local", {"doc-1": 3}),
                      Scope("fixture", "local", {})):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                resolve_citation(self.citation, self.parent, scope, require_verified_review=False)

    def test_local_preview_is_explicit_and_does_not_promote_identity(self):
        parent = page(identity_verified=False)
        citation = make_citation(parent, 1, 7)
        with self.assertRaisesRegex(ValueError, "identity_unverified"):
            resolve_citation(citation, parent, self.scope)
        resolved = resolve_citation(citation, parent, self.scope, require_verified_review=False)
        self.assertFalse(resolved.identity_verified)

    def test_review_is_required_even_for_local_preview(self):
        for status in ("pending", "rejected"):
            parent = page(review_status=status)
            with self.subTest(status=status), self.assertRaises(ValueError):
                resolve_citation(make_citation(parent, 1, 7), parent, self.scope,
                                 require_verified_review=False)

    def test_parent_span_cannot_be_extended(self):
        parent = replace(self.parent, start=3, end=7)
        for start, end in ((0, 4), (3, 8), (3, 3), (7, 3)):
            with self.subTest(span=(start, end)), self.assertRaises(ValueError):
                make_citation(parent, start, end)

    def test_integer_and_flag_coercion_rejected(self):
        for value in (True, False, 1.0, float("nan"), float("inf"), "1", None):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                make_citation(self.parent, value, 7)
        with self.assertRaises(TypeError):
            resolve_citation(self.citation, self.parent, self.scope, require_verified_review=0)

    def test_exact_serialized_contract(self):
        payload = self.citation.to_dict()
        for data in (payload | {"identity_verified": True},
                     {k: v for k, v in payload.items() if k != "end"},
                     payload | {"parent_evidence_id": "A" * 64},
                     payload | {"start": True}, payload | {"end": -1}):
            with self.subTest(data=data), self.assertRaises((TypeError, ValueError)):
                Citation.from_dict(data)

    def test_fixed_windows_cover_every_code_point_without_changing_text(self):
        parent = page("café🙂 xyz " * 100)
        spans = split_evidence(parent, max_chars=64, overlap=16)
        covered = set()
        for citation in spans:
            result = resolve_citation(citation, parent, self.scope)
            self.assertLessEqual(len(result.quote), 64)
            self.assertEqual(result.text, parent.text)
            covered.update(range(citation.start, citation.end))
        self.assertEqual(covered, set(range(len(parent.text))))
        self.assertEqual(spans, split_evidence(parent, max_chars=64, overlap=16))

    def test_windows_respect_parent_span_and_maximum_contract_size(self):
        parent = page("x" * 16384, start=100, end=16000)
        spans = split_evidence(parent, max_chars=64, overlap=32)
        self.assertLessEqual(len(spans), 512)
        self.assertEqual(spans[0].start, 100)
        self.assertEqual(spans[-1].end, 16000)

    def test_window_limits_fail_closed(self):
        for kwargs in ({"max_chars": 63}, {"max_chars": 4097}, {"max_chars": True},
                       {"overlap": -1}, {"max_chars": 64, "overlap": 33},
                       {"overlap": float("inf")}):
            with self.subTest(kwargs=kwargs), self.assertRaises((TypeError, ValueError)):
                split_evidence(self.parent, **kwargs)

    def test_mutated_frozen_objects_are_revalidated(self):
        object.__setattr__(self.citation, "start", True)
        with self.assertRaises(TypeError):
            resolve_citation(self.citation, self.parent, self.scope)


if __name__ == "__main__":
    unittest.main()
