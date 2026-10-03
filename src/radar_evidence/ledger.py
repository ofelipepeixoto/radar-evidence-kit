# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Local receipts with external checkpoints, not signatures or authorization."""
from dataclasses import dataclass
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from .canonical import canonical_bytes, MAX_BYTES
from .checks import EvidenceCheck, check_evidence
from .modelos import Evidence, Scope, _hash

FORMAT = "radar-evidence-journal-v1"
ZERO = "0" * 64
MAX_RECORDS = 1000


class IntegrityError(ValueError):
    """A record, chain or external checkpoint does not match."""


def _id(value, name):
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 1024:
        raise ValueError(f"invalid {name}")


@dataclass(frozen=True, slots=True)
class Checkpoint:
    tenant_id: str
    project_id: str
    count: int
    head: str

    def __post_init__(self):
        _id(self.tenant_id, "tenant_id")
        _id(self.project_id, "project_id")
        if type(self.count) is not int or not 0 <= self.count <= MAX_RECORDS:
            raise ValueError("invalid count")
        _hash(self.head, "head")
        if (self.count == 0) != (self.head == ZERO):
            raise ValueError("empty checkpoint mismatch")

    def to_dict(self):
        return {"format": FORMAT, "tenant_id": self.tenant_id,
                "project_id": self.project_id, "count": self.count, "head": self.head}

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != {"format", "tenant_id", "project_id", "count", "head"} or value["format"] != FORMAT:
            raise ValueError("invalid checkpoint")
        return cls(value["tenant_id"], value["project_id"], value["count"], value["head"])

    @classmethod
    def empty(cls, scope):
        if type(scope) is not Scope:
            raise TypeError("expected Scope")
        return cls(scope.tenant_id, scope.project_id, 0, ZERO)


def _event(evidence, check, scope, event_id, occurred_at):
    if type(evidence) is not Evidence or type(check) is not EvidenceCheck or type(scope) is not Scope:
        raise TypeError("expected Evidence, EvidenceCheck and Scope")
    if (evidence.tenant_id, evidence.project_id) != (scope.tenant_id, scope.project_id):
        raise ValueError("cross-scope evidence cannot enter this journal")
    _id(event_id, "event_id")
    if type(occurred_at) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", occurred_at):
        raise ValueError("occurred_at requires UTC YYYY-MM-DDTHH:MM:SSZ")
    datetime.strptime(occurred_at, "%Y-%m-%dT%H:%M:%SZ")
    if check != check_evidence(evidence, scope):
        raise ValueError("check must match the default strict assessment")
    return {"format": FORMAT, "kind": "evidence.assessed", "event_id": event_id,
            "occurred_at": occurred_at, "evidence": evidence.to_dict(),
            "scope": scope.to_dict(), "check": check.to_dict()}


def _validate_event(event):
    if type(event) is not dict or set(event) != {"format", "kind", "event_id", "occurred_at", "evidence", "scope", "check"}:
        raise IntegrityError("invalid event shape")
    if event["format"] != FORMAT or event["kind"] != "evidence.assessed":
        raise IntegrityError("unsupported event format")
    scope = Scope.from_dict(event["scope"])
    evidence = Evidence.from_dict(event["evidence"])
    raw = event["check"]
    if type(raw) is not dict or set(raw) != {"supported", "reasons", "evidence_id"} or type(raw["reasons"]) is not list:
        raise IntegrityError("invalid check shape")
    check = EvidenceCheck(raw["supported"], tuple(raw["reasons"]), raw["evidence_id"])
    if _event(evidence, check, scope, event["event_id"], event["occurred_at"]) != event:
        raise IntegrityError("event mismatch")
    return scope


class Journal:
    """Operator-local SQLite file; keep returned checkpoints outside this file.

    Every write compares the caller's previously retained checkpoint inside the
    write transaction. Replayed identical event IDs are idempotent. Checkpoints
    kept beside a writable database do not prevent an attacker rewriting both.
    Text is stored in full: use access controls and synthetic fixtures in CI.
    """
    def __init__(self, path, scope):
        if type(scope) is not Scope:
            raise TypeError("expected Scope")
        self.path = Path(path)
        self.scope = scope
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with closing(self._connect()) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS receipts (seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL, checksum TEXT NOT NULL)")
            connection.commit()

    def _connect(self):
        status = self.path.lstat()
        if not stat.S_ISREG(status.st_mode):
            raise ValueError("journal must be a regular file, not a symlink")
        if os.name == "posix" and (status.st_mode & 0o077 or status.st_uid != os.getuid()):
            raise ValueError("journal requires owner-only permissions (0600)")
        return sqlite3.connect(self.path, timeout=5)

    def _scan(self, connection):
        records, previous = [], ZERO
        rows = connection.execute("SELECT seq, event_id, body, checksum FROM receipts ORDER BY seq LIMIT ?", (MAX_RECORDS + 1,))
        try:
            for sequence, event_id, body, checksum in rows:
                if len(records) >= MAX_RECORDS or sequence != len(records) + 1:
                    raise IntegrityError("sequence or capacity mismatch")
                if type(body) is not str or len(body.encode("utf-8")) > MAX_BYTES:
                    raise IntegrityError("invalid record size")
                record = json.loads(body)
                if type(record) is not dict or set(record) != {"sequence", "previous", "event"}:
                    raise IntegrityError("invalid record shape")
                if type(record["sequence"]) is not int or record["sequence"] != sequence or record["previous"] != previous:
                    raise IntegrityError("chain mismatch")
                encoded = canonical_bytes(record)
                if encoded.decode("utf-8") != body or hashlib.sha256(encoded).hexdigest() != checksum:
                    raise IntegrityError("checksum mismatch")
                scope = _validate_event(record["event"])
                if record["event"]["event_id"] != event_id or (scope.tenant_id, scope.project_id) != (self.scope.tenant_id, self.scope.project_id):
                    raise IntegrityError("event scope mismatch")
                previous = checksum
                records.append(record)
        except (ValueError, TypeError, KeyError, RecursionError, UnicodeError) as error:
            if isinstance(error, IntegrityError):
                raise
            raise IntegrityError("invalid stored record") from error
        return records, Checkpoint(self.scope.tenant_id, self.scope.project_id, len(records), previous)

    def _match(self, actual, expected):
        if type(expected) is not Checkpoint:
            raise TypeError("external Checkpoint required")
        expected.__post_init__()
        if actual != expected:
            raise IntegrityError("external checkpoint mismatch")

    def verify(self, expected_checkpoint):
        with closing(self._connect()) as connection:
            _, actual = self._scan(connection)
            self._match(actual, expected_checkpoint)
        return actual

    def export_records(self, expected_checkpoint):
        with closing(self._connect()) as connection:
            records, actual = self._scan(connection)
            self._match(actual, expected_checkpoint)
        return records

    def append(self, evidence, check, *, event_id, occurred_at, expected_checkpoint):
        event = _event(evidence, check, self.scope, event_id, occurred_at)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            records, actual = self._scan(connection)
            self._match(actual, expected_checkpoint)
            for record in records:
                if record["event"]["event_id"] == event_id:
                    if record["event"] != event:
                        raise IntegrityError("event ID already used with different content")
                    connection.commit()
                    return actual
            if actual.count >= MAX_RECORDS:
                raise IntegrityError("journal capacity reached")
            record = {"sequence": actual.count + 1, "previous": actual.head, "event": event}
            encoded = canonical_bytes(record)
            checksum = hashlib.sha256(encoded).hexdigest()
            connection.execute("INSERT INTO receipts VALUES (?, ?, ?, ?)",
                (actual.count + 1, event_id, encoded.decode("utf-8"), checksum))
            connection.commit()
            return Checkpoint(self.scope.tenant_id, self.scope.project_id, actual.count + 1, checksum)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
