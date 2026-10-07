# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
"""Local reviewed notes. Scope, source bytes and identities belong to the caller.

Notes are data, never instructions or primary evidence. No provider or tool is
called. SQLite is local persistence, not a tamper-proof or multi-user service.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from contextlib import contextmanager

from .canonical import canonical_bytes
from .checks import check_evidence
from .modelos import Evidence, Scope, _hash, _identifier, _integer, _string

MAX_TTL = 30 * 24 * 3600
MAX_VERSIONS = 1000
MAX_EVENTS = 10000


class MemoryError(ValueError):
    """Static failure messages intentionally exclude note and source content."""


def _clock(now):
    _integer(now, "now", minimum=0)


class MemoryStore:
    """Experimental v1 contract; only the operator chooses the database path.

    ``local_review=True`` permits unverified labels for an offline single-user
    fixture. It never changes those labels into authenticated identities.
    Each operation requires fresh Scope/Evidence issued by the application.
    The application must serialize source changes with memory reads/decisions
    when concurrent source writes are possible (no cross-database transaction).
    """

    def __init__(self, path, *, local_review=False):
        if type(local_review) is not bool:
            raise TypeError("local_review must be a boolean")
        self.path = Path(path)
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise MemoryError("database symlinks are not supported")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.local_review = local_review
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self._transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS notes (
                  tenant TEXT, project TEXT, note TEXT, version INTEGER,
                  digest TEXT, payload TEXT, status TEXT, reviewer TEXT,
                  verified INTEGER, expires INTEGER,
                  PRIMARY KEY(tenant, project, note, version));
                CREATE TABLE IF NOT EXISTS active (
                  tenant TEXT, project TEXT, note TEXT, version INTEGER,
                  PRIMARY KEY(tenant, project, note));
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY, action TEXT, digest TEXT,
                  actor_hash TEXT, at INTEGER);
                CREATE TABLE IF NOT EXISTS predecessors (
                  tenant TEXT, project TEXT, note TEXT, version INTEGER,
                  previous_version INTEGER, PRIMARY KEY(tenant,project,note,version));
            """)

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _sources(self, sources, scope):
        if type(scope) is not Scope or type(sources) not in (list, tuple):
            raise TypeError("trusted Scope and source sequence required")
        result = {}
        for source in sources:
            if type(source) is not Evidence:
                raise TypeError("sources must contain Evidence")
            if check_evidence(source, scope, not self.local_review).supported:
                result[source.evidence_id] = source
        return result

    def _event(self, db, action, digest, actor, now):
        if db.execute("SELECT count(*) FROM events").fetchone()[0] >= MAX_EVENTS:
            raise MemoryError("event quota reached; operator archival required")
        db.execute("INSERT INTO events(action,digest,actor_hash,at) VALUES(?,?,?,?)",
                   (action, digest, hashlib.sha256(actor.encode()).hexdigest(), now))

    @staticmethod
    def _payload(row):
        if row["payload"] is None:
            raise MemoryError("note content was erased")
        payload = json.loads(row["payload"])
        if hashlib.sha256(canonical_bytes(payload)).hexdigest() != row["digest"]:
            raise MemoryError("note digest mismatch")
        return payload

    def _eligible(self, row, scope, sources, now):
        payload = self._payload(row)
        if (payload["tenant_id"], payload["project_id"]) != (scope.tenant_id, scope.project_id):
            raise MemoryError("scope mismatch")
        if now < payload["created_at"] or now >= payload["expires_at"]:
            raise MemoryError("note outside validity period")
        if not set(payload["source_ids"]).issubset(sources):
            raise MemoryError("source absent, changed or ineligible")
        return payload

    def propose(self, *, note_id, text, sources, scope, proposer, now, ttl=MAX_TTL):
        _identifier(note_id, "note_id")
        _identifier(proposer, "proposer")
        _string(text, "text", nonempty=True)
        _clock(now)
        _integer(ttl, "ttl", minimum=1)
        if len(text.encode("utf-8")) > 4096 or ttl > MAX_TTL:
            raise MemoryError("note size or validity limit exceeded")
        eligible = self._sources(sources, scope)
        if not 1 <= len(sources) <= 8 or len(eligible) != len(sources):
            raise MemoryError("one to eight distinct eligible sources required")
        key = (scope.tenant_id, scope.project_id, note_id)
        with self._transaction() as db:
            if db.execute("SELECT count(*) FROM notes").fetchone()[0] >= MAX_VERSIONS:
                raise MemoryError("version quota reached; operator archival required")
            version = db.execute("SELECT coalesce(max(version),0)+1 FROM notes "
                                 "WHERE tenant=? AND project=? AND note=?", key).fetchone()[0]
            payload = dict(schema_version=1, tenant_id=key[0], project_id=key[1],
                           note_id=note_id, version=version, text=text,
                           purpose="project-continuity", trust_class="reviewed-document-note",
                           source_ids=sorted(eligible), proposer=proposer,
                           created_at=now, expires_at=now + ttl)
            encoded = canonical_bytes(payload)
            digest = hashlib.sha256(encoded).hexdigest()
            db.execute("INSERT INTO notes VALUES(?,?,?,?,?,?,?,NULL,NULL,?)",
                       (*key, version, digest, encoded.decode(), "proposed", now + ttl))
            self._event(db, "propose", digest, proposer, now)
        return dict(payload, proposal_hash=digest, status="proposed")

    @staticmethod
    def _find(db, scope, note_id, digest, *, active=False):
        _identifier(note_id, "note_id")
        _hash(digest, "proposal_hash")
        if type(scope) is not Scope:
            raise TypeError("trusted Scope required")
        key = (scope.tenant_id, scope.project_id, note_id)
        query = ("SELECT n.* FROM notes n JOIN active a USING(tenant,project,note,version) "
                 if active else "SELECT * FROM notes ")
        row = db.execute(query + "WHERE tenant=? AND project=? AND note=? AND digest=?",
                         (*key, digest)).fetchone()
        if row is None:
            raise MemoryError("note or expected version not found")
        return row, key

    def decide(self, *, scope, note_id, proposal_hash, reviewer, identity_verified,
               decision, sources, now):
        _identifier(reviewer, "reviewer")
        _clock(now)
        if type(identity_verified) is not bool or decision not in ("approved", "rejected"):
            raise MemoryError("invalid review decision")
        if not identity_verified and not self.local_review:
            raise MemoryError("verified reviewer required")
        eligible = self._sources(sources, scope)
        with self._transaction() as db:
            row, key = self._find(db, scope, note_id, proposal_hash)
            latest = db.execute("SELECT max(version) FROM notes WHERE tenant=? AND project=? AND note=?",
                                key).fetchone()[0]
            payload = self._payload(row)
            if row["status"] != "proposed" or row["version"] != latest:
                raise MemoryError("review is stale or already decided")
            if reviewer == payload["proposer"]:
                raise MemoryError("distinct reviewer required")
            if decision == "approved":
                self._eligible(row, scope, eligible, now)
                previous = db.execute("SELECT version FROM active WHERE tenant=? AND project=? AND note=?",
                                      key).fetchone()
                db.execute("INSERT INTO predecessors VALUES(?,?,?,?,?)",
                           (*key, row["version"], previous[0] if previous else None))
                db.execute("INSERT OR REPLACE INTO active VALUES(?,?,?,?)", (*key, row["version"]))
            db.execute("UPDATE notes SET status=?,reviewer=?,verified=? "
                       "WHERE tenant=? AND project=? AND note=? AND version=?",
                       (decision, reviewer, int(identity_verified), *key, row["version"]))
            self._event(db, decision, proposal_hash, reviewer, now)

    def recall(self, *, scope, sources, now):
        _clock(now)
        eligible = self._sources(sources, scope)
        result = []
        with self._transaction() as db:
            rows = db.execute("SELECT n.* FROM notes n JOIN active a USING(tenant,project,note,version) "
                              "WHERE tenant=? AND project=? AND status='approved' ORDER BY note",
                              (scope.tenant_id, scope.project_id)).fetchall()
            for row in rows:
                if not row["verified"] and not self.local_review:
                    continue
                try:
                    payload = self._eligible(row, scope, eligible, now)
                except MemoryError:
                    continue
                result.append(dict(payload, proposal_hash=row["digest"],
                                   reviewer=row["reviewer"], identity_verified=bool(row["verified"])))
        return result

    def pending(self, *, scope, now):
        """Latest proposals for review only; never treat these as recall results."""
        _clock(now)
        return [row for row in self.latest(scope=scope)
                if row["status"] == "proposed" and row["created_at"] <= now < row["expires_at"]]

    def latest(self, *, scope):
        """Scoped management view, including rejected/withdrawn notes, NOT recall."""
        if type(scope) is not Scope:
            raise TypeError("trusted Scope required")
        with self._transaction() as db:
            rows = db.execute("SELECT n.* FROM notes n WHERE tenant=? AND project=? "
                              "AND payload IS NOT NULL AND version="
                              "(SELECT max(version) FROM notes p WHERE p.tenant=n.tenant "
                              "AND p.project=n.project AND p.note=n.note) ORDER BY note",
                              (scope.tenant_id, scope.project_id)).fetchall()
            return [dict(self._payload(row), proposal_hash=row["digest"], status=row["status"])
                    for row in rows]

    def undo(self, *, scope, note_id, proposal_hash, actor, sources, now):
        _identifier(actor, "actor")
        _clock(now)
        eligible = self._sources(sources, scope)
        with self._transaction() as db:
            row, key = self._find(db, scope, note_id, proposal_hash, active=True)
            predecessor = db.execute("SELECT previous_version FROM predecessors "
                                     "WHERE tenant=? AND project=? AND note=? AND version=?",
                                     (*key, row["version"])).fetchone()
            if predecessor is None:
                raise MemoryError("legacy approval lacks predecessor; explicit withdrawal required")
            previous = db.execute("SELECT * FROM notes WHERE tenant=? AND project=? AND note=? AND version=?",
                                  (*key, predecessor[0])).fetchone() if predecessor[0] is not None else None
            if predecessor[0] is not None and (previous is None or previous["status"] != "approved"):
                raise MemoryError("predecessor approval is unavailable")
            if previous is not None:
                if not previous["verified"] and not self.local_review:
                    raise MemoryError("verified review required")
                self._eligible(previous, scope, eligible, now)
                db.execute("UPDATE active SET version=? WHERE tenant=? AND project=? AND note=?",
                           (previous["version"], *key))
            else:
                db.execute("DELETE FROM active WHERE tenant=? AND project=? AND note=?", key)
            db.execute("UPDATE notes SET status='undone' WHERE tenant=? AND project=? AND note=? AND version=?",
                       (*key, row["version"]))
            self._event(db, "undo", proposal_hash, actor, now)

    def forget(self, *, scope, note_id, proposal_hash, actor, now):
        _identifier(actor, "actor")
        _clock(now)
        with self._transaction() as db:
            row, key = self._find(db, scope, note_id, proposal_hash)
            latest = db.execute("SELECT max(version) FROM notes WHERE tenant=? AND project=? AND note=?",
                                key).fetchone()[0]
            if row["version"] != latest or row["payload"] is None:
                raise MemoryError("forget is stale or already applied")
            db.execute("DELETE FROM active WHERE tenant=? AND project=? AND note=?", key)
            db.execute("UPDATE notes SET payload=NULL,status='forgotten',reviewer=NULL "
                       "WHERE tenant=? AND project=? AND note=?", key)
            self._event(db, "forget", proposal_hash, actor, now)
        self._compact()

    def purge_expired(self, *, now):
        _clock(now)
        with self._transaction() as db:
            db.execute("DELETE FROM active WHERE EXISTS(SELECT 1 FROM notes n "
                       "WHERE n.tenant=active.tenant AND n.project=active.project "
                       "AND n.note=active.note AND n.version=active.version AND n.expires<=?)", (now,))
            db.execute("UPDATE notes SET payload=NULL,status='expired',reviewer=NULL "
                       "WHERE expires<=? AND payload IS NOT NULL", (now,))
        self._compact()

    def _compact(self):
        # Logical deletion + compaction; not secure erasure of backups/SSD copies.
        with sqlite3.connect(self.path) as db:
            db.execute("VACUUM")

    def audit(self):
        with self._transaction() as db:
            return [dict(row) for row in db.execute("SELECT * FROM events ORDER BY id")]
