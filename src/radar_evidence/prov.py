# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Small PROV-O JSON-LD mapping; no remote context or RDF execution."""
from .ledger import Journal
from .canonical import canonical_bytes
import hashlib


def export_prov(journal, checkpoint):
    """Export verified receipts without source text or reviewer labels.

    An Agent node represents a recorded reviewer label, not a verified identity.
    Only explicitly modelled relationships are claimed, not full PROV validity.
    """
    if type(journal) is not Journal:
        raise TypeError("expected Journal")
    graph = []
    entities, agents = set(), set()
    for record in journal.export_records(checkpoint):
        event = record["event"]
        evidence, check = event["evidence"], event["check"]
        entity_id = "urn:radar:evidence:" + check["evidence_id"]
        activity_id = "urn:radar:receipt:" + hashlib.sha256(canonical_bytes(record)).hexdigest()
        if entity_id not in entities:
            graph.append({"@id": entity_id, "@type": "prov:Entity",
                          "radar:sourceSha256": evidence["source_sha256"],
                          "radar:textSha256": evidence["text_sha256"],
                          "radar:page": evidence["page"], "radar:start": evidence["start"],
                          "radar:end": evidence["end"], "radar:revision": evidence["revision"]})
            entities.add(entity_id)
        activity = {"@id": activity_id, "@type": "prov:Activity",
                    "prov:used": {"@id": entity_id},
                    "prov:endedAtTime": {"@value": event["occurred_at"], "@type": "xsd:dateTime"},
                    "radar:supported": check["supported"], "radar:reasons": check["reasons"]}
        if evidence["reviewer"].strip():
            agent_hash = hashlib.sha256(canonical_bytes({"tenant": evidence["tenant_id"],
                "project": evidence["project_id"], "label": evidence["reviewer"]})).hexdigest()
            agent_id = "urn:radar:reviewer-label:" + agent_hash
            if agent_id not in agents:
                graph.append({"@id": agent_id, "@type": "prov:Agent"})
                agents.add(agent_id)
            # Association belongs to Activity, not Entity. Identity flag remains
            # on the association because a label may have different attestations.
            activity["prov:qualifiedAssociation"] = {"@type": "prov:Association",
                "prov:agent": {"@id": agent_id},
                "radar:identityVerified": evidence["identity_verified"]}
        graph.append(activity)
    return {"@context": {"prov": "http://www.w3.org/ns/prov#",
            "xsd": "http://www.w3.org/2001/XMLSchema#", "radar": "urn:radar:terms:"},
            "@graph": graph}
