# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Contract boundaries and optional real assertion/retraction regressions."""
from dataclasses import replace
from hashlib import sha256
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from radar_evidence.checks import EvidenceCheck
from radar_evidence import semantica_adapter as adapter
from radar_evidence import support_lifecycle as study


def check(label="a", reasons=()):
    return EvidenceCheck(not reasons, reasons, sha256(label.encode()).hexdigest())


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.one, self.two = check(), check("b")
        self.windows = [study.SupportWindow(self.one.evidence_id, 100, 300),
                        study.SupportWindow(self.two.evidence_id, 100, withdrawn_at_ms=200)]

    def run_study(self, **kwargs):
        return study.evaluate_timeline([self.one, self.two], self.windows,
                                       [99, 100, 199, 200, 300], **kwargs)

    def test_exact_boundaries_and_explanations(self):
        result = self.run_study()
        self.assertTrue(result.evaluation_completed)
        self.assertEqual([f.supported for f in result.frames], [False, True, True, False, False])
        self.assertEqual(len(result.frames[3].active_evidence_ids), 1)
        self.assertIn((self.two.evidence_id, ("support_withdrawn",)), result.frames[3].excluded)
        self.assertIn((self.one.evidence_id, ("support_expired",)), result.frames[4].excluded)
        self.assertEqual(result.frames[-1].derived_claims, ())

    def test_permuting_inputs_and_replay_are_deterministic(self):
        first = self.run_study()
        second = study.evaluate_timeline([self.two, self.one], list(reversed(self.windows)),
                                         [99, 100, 199, 200, 300])
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.to_dict(), self.run_study().to_dict())

    def test_study_identity_binds_verdicts_windows_and_observations(self):
        original = self.run_study().study_id
        self.windows[0] = replace(self.windows[0], valid_until_ms=301)
        self.assertNotEqual(original, self.run_study().study_id)
        original = self.run_study().study_id
        self.one = replace(self.one, supported=False, reasons=("stale_revision",))
        self.assertNotEqual(original, self.run_study().study_id)

    def test_invalid_or_unreviewed_check_never_becomes_active(self):
        for reason in ("tenant_scope_mismatch", "project_scope_mismatch", "review_pending",
                       "review_rejected", "stale_revision", "reviewer_identity_unverified"):
            with self.subTest(reason=reason):
                self.one = replace(self.one, supported=False, reasons=(reason,))
                result = self.run_study()
                self.assertTrue(result.evaluation_completed)
                self.assertFalse(any(f.supported for f in result.frames))
                self.assertFalse(any(self.one.evidence_id in f.active_evidence_ids for f in result.frames))

    def test_default_mode_does_not_load_engine_or_use_network(self):
        with patch.object(adapter, "_load_engine", side_effect=AssertionError("load")), \
             patch("socket.socket", side_effect=AssertionError("socket")):
            self.assertTrue(self.run_study().evaluation_completed)

    def test_window_validation_strict_types_bounds_and_order(self):
        for value in (True, -1, 1.5, "100", 2**53):
            for field in ("valid_from_ms", "valid_until_ms", "withdrawn_at_ms"):
                with self.subTest(value=value, field=field), self.assertRaises(ValueError):
                    replace(self.windows[0], **{field: value})
        for kwargs in ({"valid_until_ms": 100}, {"valid_until_ms": 99}, {"withdrawn_at_ms": 99}):
            with self.assertRaises(ValueError):
                replace(self.windows[0], **kwargs)

    def test_window_bindings_must_be_complete_and_unique(self):
        cases = [[], [self.windows[0]] * 2, self.windows + [self.windows[0]],
                 [self.windows[0], study.SupportWindow("0" * 64, 100)],
                 [self.windows[0], {}], (w for w in self.windows)]
        with patch.object(adapter, "_load_engine", side_effect=AssertionError("load")):
            for windows in cases:
                result = study.evaluate_timeline([self.one, self.two], windows, [100], use_semantica=True)
                self.assertFalse(result.evaluation_completed)
                self.assertEqual(result.frames, ())

    def test_observations_are_bounded_and_strictly_increasing(self):
        for observations in ([], [100, 100], [101, 100], [True], [-1], [2**53],
                             list(range(33)), (x for x in range(2)), ["private"]):
            result = study.evaluate_timeline([self.one, self.two], self.windows, observations)
            self.assertFalse(result.evaluation_completed)
            self.assertEqual(result.frames, ())

    def test_check_limit_and_rejection_before_loading(self):
        for checks in ([], [self.one] * 2, [check(str(i)) for i in range(21)],
                       [self.one.to_dict()], (x for x in [self.one])):
            with patch.object(adapter, "_load_engine", side_effect=AssertionError("load")):
                self.assertFalse(study.evaluate_timeline(checks, self.windows, [100],
                                                        use_semantica=True).evaluation_completed)

    def test_tampered_frozen_window_is_revalidated(self):
        object.__setattr__(self.windows[0], "valid_until_ms", True)
        self.assertFalse(self.run_study().evaluation_completed)

    def test_mode_budget_and_subclass_rejected(self):
        self.assertEqual(self.run_study(use_semantica="true").reasons, ("invalid_mode",))
        for value in (True, 9, 5001, "2000"):
            self.assertEqual(self.run_study(evaluation_budget_ms=value).reasons, ("invalid_budget",))
        class CustomWindow(study.SupportWindow):
            pass
        self.windows[0] = CustomWindow(self.one.evidence_id, 100)
        self.assertFalse(self.run_study().evaluation_completed)

    def test_engine_absence_does_not_fall_back_to_positive_baseline(self):
        with patch.object(adapter, "_load_engine", side_effect=adapter._EngineUnavailable("dependency_unavailable")):
            result = self.run_study(use_semantica=True)
        self.assertEqual(result.reasons, ("dependency_unavailable",))
        self.assertEqual(result.frames, ())

    def test_private_exception_is_neither_returned_nor_logged_by_adapter(self):
        with patch.object(adapter, "_load_engine", side_effect=RuntimeError("private-document")), \
             self.assertNoLogs():
            result = self.run_study(use_semantica=True)
        self.assertEqual(result.reasons, ("engine_error",))
        self.assertNotIn("private-document", json.dumps(result.to_dict()))

    def test_late_result_discards_all_frames(self):
        with patch.object(study.time, "monotonic", side_effect=[0, 0, 0, 0, 0, 0, 10]):
            result = self.run_study()
        self.assertEqual(result.reasons, ("evaluation_budget_exceeded",))
        self.assertEqual(result.frames, ())

    def test_incorrect_engine_cannot_approve_or_return_partial_results(self):
        session = Mock(facts={"BundleSupported(unexpected)"})
        session.explain.return_value = SimpleNamespace(active=True)
        with patch.object(adapter, "_load_engine", return_value=(
                Mock(return_value=session), Mock(), Mock())):
            result = self.run_study(use_semantica=True)
        self.assertEqual(result.reasons, ("engine_contract_mismatch",))
        self.assertEqual(result.frames, ())

    def test_twenty_checks_and_thirty_two_observations(self):
        checks = [check(str(i)) for i in range(20)]
        windows = [study.SupportWindow(c.evidence_id, 0, 31) for c in checks]
        result = study.evaluate_timeline(checks, windows, list(range(32)))
        self.assertTrue(result.evaluation_completed)
        self.assertTrue(all(f.supported for f in result.frames[:-1]))
        self.assertFalse(result.frames[-1].supported)

    def test_withdrawal_at_start_never_supports_and_both_reasons_are_preserved(self):
        self.windows[0] = replace(self.windows[0], withdrawn_at_ms=100)
        result = self.run_study()
        self.assertFalse(any(f.supported for f in result.frames))
        self.assertIn((self.one.evidence_id, ("support_expired", "support_withdrawn")),
                      result.frames[-1].excluded)


@unittest.skipUnless(os.getenv("RADAR_SEMANTICA_INTEGRATION") == "1", "optional real engine")
class RealLifecycleTests(unittest.TestCase):
    def test_real_session_retracts_support_at_exact_boundaries(self):
        checks = [check("a"), check("b")]
        windows = [study.SupportWindow(checks[0].evidence_id, 100, 300),
                   study.SupportWindow(checks[1].evidence_id, 100, withdrawn_at_ms=200)]
        core = study.evaluate_timeline(checks, windows, [99, 100, 199, 200, 299, 300])
        real = study.evaluate_timeline(checks, windows, [99, 100, 199, 200, 299, 300],
                                       use_semantica=True, evaluation_budget_ms=5000)
        self.assertTrue(real.evaluation_completed, real.reasons)
        self.assertEqual(core.frames, real.frames)
        self.assertEqual(real.frames[-1].derived_claims, ())

    def test_real_limits_with_many_simultaneous_retractions(self):
        checks = [check(str(i)) for i in range(20)]
        windows = [study.SupportWindow(c.evidence_id, i, 30) for i, c in enumerate(checks)]
        real = study.evaluate_timeline(checks, windows, list(range(32)),
                                       use_semantica=True, evaluation_budget_ms=5000)
        core = study.evaluate_timeline(checks, windows, list(range(32)))
        self.assertTrue(real.evaluation_completed, real.reasons)
        self.assertEqual(real.frames, core.frames)


if __name__ == "__main__":
    unittest.main()
