"""Synthetic adversarial delivery tests; never opens a student's project state."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
import notification_journal
from notification_journal import Journal


def record(identity, message, kind="post"):
    body={"message":message}
    return {"id":identity,"course_id":"SYNTHETIC","kind":kind,"title":"Synthetic notice",
            "hash":hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest(),"body":body}


def snap(minute, complete=True):
    return {"finished_at":f"2026-10-12T10:{minute:02d}:00+00:00","collection_complete":complete}


class FinalJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="hku-final-journal-")
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"journal.sqlite3"
        self.db=Journal(self.path)
        self.addCleanup(lambda:self.db.close())

    def ingest(self, minute, message, complete=True):
        r=record("post:1",message)
        return self.db.ingest({r["id"]:r},snap(minute,complete))

    def test_clock_rollback_retains_notice_without_replacing_newer_head(self):
        self.ingest(10,"Exam Friday")
        self.ingest(9,"URGENT: Exam moved to Thursday")
        events=self.db.events()
        self.assertEqual(["Exam Friday","URGENT: Exam moved to Thursday"],
                         [e["record"]["body"]["message"] for e in events])
        self.assertEqual("observed_late",events[-1]["availability"])
        self.assertEqual("Exam Friday",self.db.latest("post:1")["record"]["body"]["message"])
        self.assertEqual(2,len(self.db.pending({})))
        self.assertIn("Thursday",self.db.event(events[-1]["event_id"])["record"]["body"]["message"])

    def test_late_complete_snapshot_cannot_generate_disappearance(self):
        a=record("post:1","Newer A");b=record("post:2","Newer B")
        self.db.ingest({a["id"]:a,b["id"]:b},snap(10))
        older=record("post:1","Older A")
        self.db.ingest({older["id"]:older},snap(9))
        self.assertEqual("visible",self.db.latest("post:2")["availability"])
        self.assertEqual(3,len(self.db.events()))
        self.assertFalse(any(e["availability"]=="no_longer_visible" for e in self.db.events()))

    def test_latest_replay_after_late_snapshot_is_idempotent(self):
        self.ingest(10,"Latest")
        self.ingest(9,"Late")
        before=self.db.events()
        for _ in range(4):
            self.assertEqual(0,self.ingest(10,"Latest"))
            self.assertEqual(0,self.ingest(9,"Late"))
        self.assertEqual(before,self.db.events())

    def test_unchanged_late_snapshots_do_not_repeat_notifications(self):
        self.ingest(20,"Before clock adjustment")
        self.ingest(9,"Revised after clock adjustment")
        self.assertEqual(0,self.ingest(10,"Revised after clock adjustment"))
        self.assertEqual(0,self.ingest(11,"Revised after clock adjustment"))
        self.assertEqual(2,len(self.db.events()))

    def test_failure_watermark_does_not_drop_late_spool(self):
        self.ingest(10,"Old notice")
        failure=record("issue:live_refresh","Collector timed out","collection_issue")
        self.db.ingest({failure["id"]:failure},snap(12,False))
        self.ingest(11,"Changed during failed refresh",False)
        late=self.db.events()[-1]
        self.assertEqual("observed_late",late["availability"])
        self.assertIn("Changed",late["record"]["body"]["message"])
        self.assertEqual("Old notice",self.db.latest("post:1")["record"]["body"]["message"])
        self.ingest(13,"Changed during failed refresh")
        self.assertEqual("Changed during failed refresh",self.db.latest("post:1")["record"]["body"]["message"])
        self.assertEqual("resolved",self.db.latest("issue:live_refresh")["availability"])

    def test_late_only_source_is_readable_without_promoting_head(self):
        self.ingest(10,"Current source")
        r=record("post:2","Previously unseen historical source")
        self.db.ingest({r["id"]:r},snap(9))
        event=self.db.latest("post:2")
        self.assertEqual("observed_late",event["availability"])
        self.assertEqual(r,self.db.event(event["event_id"])["record"])
        self.assertIsNone(self.db.db.execute("SELECT 1 FROM current WHERE source_id='post:2'").fetchone())
        self.assertEqual("visible",self.db.latest("post:1")["availability"])

    def test_rollback_reversion_and_later_updates_are_all_preserved(self):
        self.ingest(20,"A")
        self.ingest(9,"B")
        self.ingest(10,"A")
        self.ingest(21,"B")
        self.ingest(22,"C")
        self.assertEqual(["A","B","A","B","C"],
                         [e["record"]["body"]["message"] for e in self.db.events()])
        self.assertEqual("C",self.db.latest("post:1")["record"]["body"]["message"])

    def test_snapshot_dedup_is_durable_across_reopen(self):
        self.ingest(10,"Current")
        self.ingest(9,"Late")
        before=self.db.events()
        self.db.close();self.db=Journal(self.path)
        self.assertEqual(0,self.ingest(10,"Current"))
        self.assertEqual(0,self.ingest(9,"Late"))
        self.assertEqual(before,self.db.events())

    def test_old_database_migration_preserves_events_and_receipts(self):
        self.ingest(10,"Current")
        event=self.db.latest("post:1")
        receipt={event["event_id"]:{"hash":event["hash"]}}
        with self.db.db:
            self.db.db.execute("DROP TABLE processed_snapshots")
            self.db.db.execute("DROP TABLE last_observed")
        self.db.close();self.db=Journal(self.path)
        self.assertEqual(0,self.ingest(10,"Current"))
        self.assertEqual([],self.db.pending(receipt))
        self.ingest(9,"Late")
        self.assertEqual(1,len(self.db.pending(receipt)))
        self.assertEqual(event,self.db.latest("post:1"))

    def test_failure_rolls_back_fingerprint_and_partial_records(self):
        self.ingest(10,"Initial")
        records={r["id"]:r for r in (record("post:1","Changed"),record("post:2","New"))}
        original=notification_journal.uuid.uuid4
        count=0
        def broken_uuid():
            nonlocal count
            count+=1
            if count==2:raise RuntimeError("Synthetic transaction interruption")
            return original()
        with patch.object(notification_journal.uuid,"uuid4",side_effect=broken_uuid):
            with self.assertRaises(RuntimeError):self.db.ingest(records,snap(11))
        self.assertEqual(1,len(self.db.events()))
        self.assertEqual(2,self.db.ingest(records,snap(11)))
        self.assertEqual(3,len(self.db.events()))

    def test_equal_timestamp_different_observation_is_not_deduplicated(self):
        self.ingest(10,"A")
        self.ingest(10,"B")
        self.assertEqual(2,len(self.db.events()))
        self.assertEqual("B",self.db.latest("post:1")["record"]["body"]["message"])


if __name__=="__main__":unittest.main()
