# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Fresh-process probe: deny external imports outside the focused dependency set.

This verifies the tested API can execute without SDK/LLM/HTTP extras. It is not
a network sandbox or a substitute for a clean virtual environment and pins.
Run with the core source and pinned upstream checkout on PYTHONPATH.
"""
import importlib.abc
import sys

_ALLOWED = frozenset({
    "radar_evidence", "semantica", "networkx", "numpy", "scipy",
    "_csparsetools", "_cyutility", "pydantic", "pydantic_core",
    "annotated_types", "typing_extensions", "typing_inspection", "dateutil", "six",
})


class FocusedImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split(".", 1)[0]
        if root not in sys.stdlib_module_names and root not in _ALLOWED:
            raise ModuleNotFoundError("External dependency blocked by focused import probe")
        return None


def main():
    guard = FocusedImports()
    sys.meta_path.insert(0, guard)
    try:
        from radar_evidence.checks import EvidenceCheck
        from radar_evidence.semantica_adapter import evaluate_support
        result = evaluate_support([EvidenceCheck(True, (), "a" * 64)], evaluation_budget_ms=5000)
        if not result.supported or result.engine_version != "0.7.0":
            print("Focused dependency probe failed:", ",".join(result.reasons))
            return 1
        print("Focused dependency probe passed: real pinned engine, no additional external imports required.")
        return 0
    finally:
        sys.meta_path.remove(guard)


if __name__ == "__main__":
    raise SystemExit(main())
