# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Standard-library boundary tests; optional real-engine tests require a flag."""
import hashlib
import importlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import sys
from unittest.mock import patch

from radar_evidence.checks import EvidenceCheck
from radar_evidence import semantica_adapter as adapter


def eligible(label="fixture"):
    return EvidenceCheck(True, (), hashlib.sha256(label.encode()).hexdigest())


class AdapterBoundaryTests(unittest.TestCase):
    def test_import_does_not_import_semantica(self):
        with patch("importlib.import_module", side_effect=AssertionError("unexpected import")):
            importlib.reload(adapter)

    def test_missing_dependency_denies_without_claims(self):
        with patch.object(adapter.importlib.util, "find_spec", return_value=None):
            result = adapter.evaluate_support([eligible()])
        self.assertFalse(result.supported)
        self.assertEqual(result.reasons, ("dependency_unavailable",))
        self.assertEqual(result.derived_claims, ())
        self.assertEqual(result.verified_modules, ())
        self.assertIsNone(result.engine_version)

    def test_unsupported_source_rejected_before_import(self):
        with TemporaryDirectory() as directory:
            package = Path(directory) / "semantica"
            package.mkdir()
            (package / "__init__.py").write_text("__version__ = '0.7.0'", encoding="utf-8")
            spec = SimpleNamespace(origin=str(package / "__init__.py"))
            with patch.object(adapter.importlib.util, "find_spec", return_value=spec), \
                 patch.object(adapter.importlib, "import_module", side_effect=AssertionError("import")):
                result = adapter.evaluate_support([eligible()])
        self.assertEqual(result.reasons, ("unsupported_source",))
        self.assertFalse(result.supported)

    def test_unsupported_version_denies(self):
        with patch.object(adapter, "_verified_package_root"), \
             patch.object(adapter.importlib, "import_module", return_value=SimpleNamespace(__version__="9.0.0")):
            result = adapter.evaluate_support([eligible()])
        self.assertEqual(result.reasons, ("unsupported_version",))

    def test_transitive_dependency_missing_denies(self):
        with patch.object(adapter, "_verified_package_root"), \
             patch.object(adapter.importlib, "import_module", side_effect=[
                 SimpleNamespace(__version__="0.7.0"), ImportError("private-path")]):
            result = adapter.evaluate_support([eligible()])
        self.assertEqual(result.reasons, ("dependency_unavailable",))
        self.assertNotIn("private-path", str(result.to_dict()))

    def test_unknown_metadata_and_unbounded_iterables_deny_without_loading(self):
        cases = [None, {}, {"supported": True}, "supported", (eligible() for _ in range(2)),
                 [], [eligible(str(index)) for index in range(21)],
                 [{"supported": True, "reasons": [], "evidence_id": "a" * 64}]]
        with patch.object(adapter, "_load_engine", side_effect=AssertionError("engine load")):
            for value in cases:
                with self.subTest(value_type=type(value).__name__):
                    self.assertEqual(adapter.evaluate_support(value).reasons, ("invalid_checks",))

    def test_duplicates_cannot_pad_a_bundle(self):
        with patch.object(adapter, "_load_engine", side_effect=AssertionError("engine load")):
            result = adapter.evaluate_support([eligible(), eligible()])
        self.assertEqual(result.reasons, ("invalid_checks",))

    def test_privileged_dataclass_mutation_revalidated(self):
        value = eligible()
        object.__setattr__(value, "supported", "true")
        with patch.object(adapter, "_load_engine", side_effect=AssertionError("engine load")):
            result = adapter.evaluate_support([value])
        self.assertEqual(result.reasons, ("invalid_checks",))

    def test_subclasses_not_accepted(self):
        class DerivedCheck(EvidenceCheck):
            pass
        value = DerivedCheck(True, (), "a" * 64)
        self.assertEqual(adapter.evaluate_support([value]).reasons, ("invalid_checks",))

    def test_budget_values_fail_closed(self):
        for value in [True, False, 9, 5001, "2000", None, 2.5]:
            with self.subTest(value=value):
                result = adapter.evaluate_support([eligible()], evaluation_budget_ms=value)
                self.assertFalse(result.supported)
                self.assertEqual(result.reasons, ("invalid_budget",))

    def test_late_engine_result_is_discarded_before_session_creation(self):
        session = unittest.mock.Mock(side_effect=AssertionError("session creation"))
        with patch.object(adapter, "_load_engine", return_value=(session, object, object)), \
             patch.object(adapter.time, "monotonic", side_effect=[0.0, 3.0]):
            result = adapter.evaluate_support([eligible()])
        self.assertFalse(result.supported)
        self.assertEqual(result.reasons, ("evaluation_budget_exceeded",))
        self.assertFalse(result.evaluation_completed)
        self.assertEqual(result.derived_claims, ())

    def test_engine_errors_are_generic_and_do_not_approve(self):
        with patch.object(adapter, "_load_engine", side_effect=RuntimeError("synthetic-secret")):
            result = adapter.evaluate_support([eligible()])
        self.assertEqual(result.reasons, ("engine_error",))
        self.assertNotIn("synthetic-secret", str(result.to_dict()))

    def test_bundle_identity_is_order_independent_even_when_dependency_missing(self):
        one, two = eligible("one"), eligible("two")
        with patch.object(adapter.importlib.util, "find_spec", return_value=None):
            forward = adapter.evaluate_support([one, two])
            reverse = adapter.evaluate_support([two, one])
        self.assertEqual(forward.to_dict(), reverse.to_dict())
        self.assertEqual(forward.evidence_ids, tuple(sorted((one.evidence_id, two.evidence_id))))


@unittest.skipUnless(os.getenv("RADAR_SEMANTICA_INTEGRATION") == "1",
                     "optional real Semantica engine; set flag and pinned PYTHONPATH")
class RealSemanticaTests(unittest.TestCase):
    def test_real_fixed_rules_derive_only_hash_atoms(self):
        checks = [eligible("PT-BR: cláusula com vírgula, ?x, aspas e acentos"), eligible("segundo")]
        result = adapter.evaluate_support(checks, evaluation_budget_ms=5000)
        self.assertTrue(result.supported, result.reasons)
        self.assertEqual(result.engine_version, "0.7.0")
        self.assertEqual(len(result.verified_modules), 10)
        self.assertEqual(len(result.derived_claims), 3)
        self.assertEqual(result.derived_claims, tuple(sorted(result.derived_claims)))
        self.assertNotIn("cláusula", str(result.to_dict()))

    def test_one_ineligible_check_blocks_whole_bundle(self):
        bad = EvidenceCheck(False, ("stale_revision",), hashlib.sha256(b"old").hexdigest())
        result = adapter.evaluate_support([eligible(), bad], evaluation_budget_ms=5000)
        self.assertFalse(result.supported)
        self.assertEqual(result.reasons, ("stale_revision",))
        self.assertTrue(result.evaluation_completed)
        self.assertFalse(any(fact.startswith("BundleSupported(") for fact in result.derived_claims))

    def test_twenty_check_limit_and_deterministic_results(self):
        checks = [eligible(str(index)) for index in range(20)]
        forward = adapter.evaluate_support(checks, evaluation_budget_ms=5000)
        reverse = adapter.evaluate_support(list(reversed(checks)), evaluation_budget_ms=5000)
        self.assertTrue(forward.supported, forward.reasons)
        self.assertEqual(forward.to_dict(), reverse.to_dict())
        self.assertEqual(len(forward.derived_claims), 21)


if __name__ == "__main__":
    unittest.main()
