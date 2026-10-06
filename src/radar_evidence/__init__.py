# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Original evidence contracts; importing core never loads Semantica."""
from .modelos import Evidence, Scope
from .checks import EvidenceCheck, check_evidence
from .ledger import Checkpoint, IntegrityError, Journal
from .prov import export_prov
from .citations import Citation, make_citation, resolve_citation, split_evidence

__version__ = "0.2.0"
__all__ = ["Evidence", "Scope", "EvidenceCheck", "check_evidence", "Checkpoint",
           "IntegrityError", "Journal", "export_prov", "Citation", "make_citation",
           "resolve_citation", "split_evidence"]
