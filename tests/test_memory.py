# Copyright (c) 2026 Carlos Felipe
# SPDX-License-Identifier: MIT
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from radar_evidence import Evidence, Scope
from radar_evidence.memory import MemoryStore, MemoryError, MAX_TTL


def source(**changes):
    text = "O projeto exige aprovação documental antes da publicação."
    values = dict(tenant_id="tenant-a", project_id="projeto-a", document_id="doc-1",
                  revision=1, page=1, start=0, end=len(text), text=text,
                  source_sha256="1" * 64, text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                  review_status="approved", reviewer="fixture-source-reviewer",
                  identity_verified=True)
    values.update(changes)
    return Evidence(**values)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "memory.sqlite3"
        self.db = MemoryStore(self.path)
        self.scope = Scope("tenant-a", "projeto-a", {"doc-1": 1})
        self.sources = [source()]

    def draft(self, **kw):
        args = dict(note_id="continuidade", text="Conferir aprovação antes de publicar.",
                    sources=self.sources, scope=self.scope, proposer="fixture-author", now=100, ttl=50)
        args.update(kw)
        return self.db.propose(**args)

    def decide(self, draft, **kw):
        args = dict(scope=self.scope, note_id=draft["note_id"], proposal_hash=draft["proposal_hash"],
                    reviewer="fixture-reviewer", identity_verified=True, decision="approved",
                    sources=self.sources, now=101)
        args.update(kw)
        self.db.decide(**args)

    def recall(self, **kw):
        args = dict(scope=self.scope, sources=self.sources, now=102)
        args.update(kw)
        return self.db.recall(**args)

    def test_proposal_is_not_visible(self):
        self.draft()
        self.assertEqual(self.recall(), [])

    def test_review_queue_is_scoped_and_latest_only(self):
        self.draft()
        latest = self.draft(text="Última proposta.")
        self.assertEqual(self.db.pending(scope=self.scope, now=102)[0]["proposal_hash"], latest["proposal_hash"])
        self.assertEqual(self.db.pending(scope=Scope("other", "projeto-a", {}), now=102), [])
        self.assertEqual(self.db.pending(scope=self.scope, now=150), [])

    def test_review_survives_restart(self):
        draft = self.draft()
        self.decide(draft)
        self.db = MemoryStore(self.path)
        self.assertEqual(self.recall()[0]["text"], draft["text"])
        self.assertTrue(self.recall()[0]["identity_verified"])

    def test_changed_proposal_requires_new_review(self):
        old = self.draft()
        new = self.draft(text="Nova formulação.")
        with self.assertRaises(MemoryError):
            self.decide(old)
        self.decide(new)
        self.assertEqual(self.recall()[0]["version"], 2)

    def test_pending_edit_does_not_replace_approved(self):
        first = self.draft()
        self.decide(first)
        self.draft(text="Aguardar revisão.")
        self.assertEqual(self.recall()[0]["proposal_hash"], first["proposal_hash"])

    def test_review_cannot_be_replayed(self):
        draft = self.draft()
        self.decide(draft)
        with self.assertRaises(MemoryError):
            self.decide(draft)

    def test_rejection_is_terminal_and_invisible(self):
        draft = self.draft()
        self.decide(draft, decision="rejected")
        self.assertEqual(self.recall(), [])
        with self.assertRaises(MemoryError):
            self.decide(draft)

    def test_self_review_denied(self):
        draft = self.draft()
        with self.assertRaises(MemoryError):
            self.decide(draft, reviewer="fixture-author")

    def test_default_requires_verified_source_and_reviewer(self):
        with self.assertRaises(MemoryError):
            self.draft(sources=[source(identity_verified=False)])
        draft = self.draft()
        with self.assertRaises(MemoryError):
            self.decide(draft, identity_verified=False)

    def test_local_labels_remain_unverified_and_strict_reopen_hides(self):
        self.db = MemoryStore(self.path, local_review=True)
        self.sources = [source(identity_verified=False)]
        draft = self.draft()
        self.decide(draft, identity_verified=False)
        self.assertFalse(self.recall()[0]["identity_verified"])
        self.db = MemoryStore(self.path)
        self.assertEqual(self.recall(), [])

    def test_source_changes_block_read_and_approval(self):
        for changes in ({"review_status": "rejected"}, {"revision": 2},
                        {"source_sha256": "2" * 64}, {"reviewer": "other"}):
            with self.subTest(changes=changes):
                draft = self.draft()
                altered = [source(**changes)]
                with self.assertRaises(MemoryError):
                    self.decide(draft, sources=altered)
                self.decide(draft)
                self.assertEqual(self.recall(sources=altered), [])

    def test_scope_isolates_reads_and_decisions(self):
        draft = self.draft()
        self.decide(draft)
        for scope in (Scope("other", "projeto-a", {"doc-1": 1}),
                      Scope("tenant-a", "other", {"doc-1": 1}),
                      Scope("tenant-a", "projeto-a", {"doc-1": 2})):
            with self.subTest(scope=scope):
                self.assertEqual(self.recall(scope=scope), [])

    def test_no_source_cannot_be_promoted(self):
        with self.assertRaises(MemoryError):
            self.draft(sources=[])
        with self.assertRaises(MemoryError):
            self.draft(sources=self.sources * 2)

    def test_expiry_and_future_time_are_denied(self):
        draft = self.draft()
        self.decide(draft)
        self.assertEqual(self.recall(now=150), [])
        self.assertEqual(self.recall(now=99), [])
        self.db.purge_expired(now=150)
        with sqlite3.connect(self.path) as db:
            self.assertIsNone(db.execute("SELECT payload FROM notes").fetchone()[0])

    def test_unicode_size_and_ttl_limits(self):
        for changes in ({"text": "é" * 2049}, {"ttl": MAX_TTL + 1}, {"ttl": True}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                self.draft(**changes)

    def test_undo_restores_previous_review_and_replay_is_denied(self):
        first = self.draft()
        self.decide(first)
        second = self.draft(text="Segunda nota revisada.")
        self.decide(second)
        args = dict(scope=self.scope, note_id=second["note_id"], proposal_hash=second["proposal_hash"],
                    actor="operator", sources=self.sources, now=103)
        self.db.undo(**args)
        self.assertEqual(self.recall()[0]["proposal_hash"], first["proposal_hash"])
        with self.assertRaises(MemoryError):
            self.db.undo(**args)

    def test_undo_will_not_restore_revoked_source(self):
        first = self.draft()
        self.decide(first)
        second = self.draft(text="Segunda nota.")
        self.decide(second)
        with self.assertRaises(MemoryError):
            self.db.undo(scope=self.scope, note_id=second["note_id"],
                         proposal_hash=second["proposal_hash"], actor="operator", sources=[], now=103)

    def test_forget_erases_all_versions_and_replay_fails(self):
        first = self.draft()
        second = self.draft(text="Outro texto privado.")
        with self.assertRaises(MemoryError):
            self.db.forget(scope=self.scope, note_id=first["note_id"],
                           proposal_hash=first["proposal_hash"], actor="operator", now=104)
        self.db.forget(scope=self.scope, note_id=second["note_id"],
                       proposal_hash=second["proposal_hash"], actor="operator", now=104)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM notes WHERE payload IS NOT NULL").fetchone()[0], 0)
        self.assertNotIn(second["text"].encode(), self.path.read_bytes())
        self.assertEqual(self.recall(), [])

    def test_receipts_do_not_contain_note_or_raw_actor(self):
        draft = self.draft()
        self.decide(draft)
        audit = json.dumps(self.db.audit())
        self.assertNotIn(draft["text"], audit)
        self.assertNotIn("fixture-reviewer", audit)
        self.assertEqual([event["action"] for event in self.db.audit()], ["propose", "approved"])

    def test_concurrent_approvals_exactly_once(self):
        draft = self.draft()
        def approve(_):
            try:
                self.decide(draft)
                return True
            except MemoryError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sum(executor.map(approve, range(2))), 1)

    def test_concurrent_versions_are_distinct(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            versions = list(executor.map(lambda _: self.draft()["version"], range(2)))
        self.assertEqual(sorted(versions), [1, 2])

    def test_content_tampering_fails_closed(self):
        draft = self.draft()
        self.decide(draft)
        with sqlite3.connect(self.path) as db:
            payload = json.loads(db.execute("SELECT payload FROM notes").fetchone()[0])
            payload["text"] = "Texto adulterado"
            db.execute("UPDATE notes SET payload=?", (json.dumps(payload),))
        self.assertEqual(self.recall(), [])

    def test_sqlite_backup_can_be_reopened(self):
        self.decide(self.draft())
        backup = Path(self.tmp.name) / "backup.sqlite3"
        with sqlite3.connect(self.path) as src, sqlite3.connect(backup) as dest:
            src.backup(dest)
        restored = MemoryStore(backup)
        self.assertEqual(restored.recall(scope=self.scope, sources=self.sources, now=102), self.recall())

    def test_database_permissions_and_symlink(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        link = Path(self.tmp.name) / "link"
        link.symlink_to(self.path)
        with self.assertRaises(MemoryError):
            MemoryStore(link)
