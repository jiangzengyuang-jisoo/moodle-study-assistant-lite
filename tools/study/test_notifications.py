"""Synthetic-only tests of notification delivery and bounded, recoverable context."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
import light
import test_light as fixtures
from test_light import snapshot, state
from test_exam_sources import registered

class NotificationTests(unittest.TestCase):
    setUp = fixtures.LightTests.setUp
    # Reuse isolation, not the parent's test cases (loaded twice is avoided below).
    def advance(self, change):
        snap=light.read(light.SNAPSHOT)
        snap["finished_at"]=(datetime.fromisoformat(snap["finished_at"])+timedelta(seconds=1)).isoformat()
        change(snap)
        light.atom(light.SNAPSHOT,snap)
        if snap["collection_complete"]:light.atom(light.SYSTEM/"refresh-last-complete.json",snap)
        return snap

    def ack_all(self):
        while True:
            rows=light.pending(None,0,12)["items"]
            if not rows:break
            for row in rows:
                light.accept(row["id"],row["hash"],"Synthetic actual source review",row["event_id"],"Synthetic visual check")

    def test_disappearance_stays_pending_and_source_survives_repeated_scans(self):
        light.scan()
        self.advance(lambda s:s.update(threads=[]))
        light.scan();light.scan()
        rows=[r for r in light.pending(None,0,100)["items"] if r["id"]=="post:30"]
        self.assertEqual(2,len(rows))
        self.assertEqual({"visible","no_longer_visible"},{r["availability"] for r in rows})
        for r in rows:
            self.assertIn("Not including Unit 3",light.source(r["id"],event=r["event_id"])["content"])
        self.ack_all()
        self.assertEqual(0,light.pending()["pending_review_count"])

    def test_reviewed_notice_disappearance_is_a_new_unreviewed_event(self):
        light.scan();self.ack_all()
        self.advance(lambda s:s.update(threads=[]))
        rows=light.pending()["items"]
        self.assertTrue(any(r["id"]=="post:30" and r["availability"]=="no_longer_visible" for r in rows))

    def test_multiple_edits_and_reversion_are_all_retained(self):
        light.scan();self.ack_all()
        self.advance(lambda s:s["threads"][0]["posts"][0].update(message="Revised: include Unit 3"))
        light.scan()
        self.advance(lambda s:s["threads"][0]["posts"][0].update(message='Not including Unit 3. <img src="figure-a.png">'))
        light.scan()
        rows=[r for r in light.pending(None,0,100)["items"] if r["id"]=="post:30"]
        self.assertEqual(2,len(rows))
        with self.assertRaisesRegex(ValueError,"多个"):light.accept("post:30",rows[-1]["hash"],"reviewed")
        light.accept("post:30",rows[0]["hash"],"Reviewed first revision",rows[0]["event_id"])
        self.assertEqual(1,len([r for r in light.pending()["items"] if r["id"]=="post:30"]))

    def test_spool_recovers_versions_even_if_latest_was_overwritten(self):
        first=light.read(light.SNAPSHOT)
        second=deepcopy(first);second["finished_at"]=(datetime.fromisoformat(first["finished_at"])+timedelta(seconds=1)).isoformat()
        second["threads"][0]["posts"][0]["message"]="Revised scope"
        for name,snap in (("a.json",first),("b.json",second)):
            light.atom(light.SYSTEM/"collections"/name,snap)
        light.atom(light.SNAPSHOT,second);light.atom(light.SYSTEM/"refresh-last-complete.json",second)
        rows=[r for r in light.pending(None,0,100)["items"] if r["id"]=="post:30"]
        self.assertEqual(2,len(rows))
        self.assertEqual([],list((light.SYSTEM/"collections").glob("*.json")))
        self.assertEqual(2,len([r for r in light.pending(None,0,100)["items"] if r["id"]=="post:30"]))

    def test_partial_failure_invalidates_exam_and_retains_new_notice(self):
        s,old=registered();s.update(revision=0,timezone="UTC",settings={},integrations={})
        s["courses"][0]["moodle_course_ids"]=[1]
        light.atom(light.STATE,s);light.atom(light.SNAPSHOT,old)
        partial=deepcopy(old);partial.update(collection_complete=False,finished_at=(datetime.fromisoformat(old["finished_at"])+timedelta(seconds=1)).isoformat(),
                                           errors=[{"scope":"other-course","message":"Synthetic timeout"}])
        partial["threads"][0]["posts"][0]["message"]="New scope includes Chapter 5"
        def run(*args,**kwargs):
            light.atom(light.SNAPSHOT,partial)
            return subprocess.CompletedProcess(args[0],2,"","")
        with patch.object(light.shutil,"which",return_value=sys.executable),patch.object(light.subprocess,"run",side_effect=run):
            with self.assertRaises(ValueError):light.refresh(True)
        self.assertEqual("needs_review",light.read(light.STATE)["exam_profiles"][0]["verification_status"])
        self.assertTrue(any(r["kind"]=="collection_issue" for r in light.pending(None,0,100)["items"]))
        db=light.journal()
        try:self.assertTrue(any("Chapter 5" in json.dumps(e["record"]) for e in db.events()))
        finally:db.close()

    def test_timeout_also_invalidates_exam_without_overwriting_snapshot(self):
        s,snap=registered();s.update(revision=0,timezone="UTC",settings={},integrations={})
        s["courses"][0]["moodle_course_ids"]=[1]
        light.atom(light.STATE,s);light.atom(light.SNAPSHOT,snap);before=light.SNAPSHOT.read_bytes()
        with patch.object(light.shutil,"which",return_value=sys.executable),patch.object(light.subprocess,"run",side_effect=subprocess.TimeoutExpired("node",600)):
            with self.assertRaises(ValueError):light.refresh(True)
        self.assertEqual(before,light.SNAPSHOT.read_bytes())
        self.assertEqual("needs_review",light.read(light.STATE)["exam_profiles"][0]["verification_status"])

    def test_every_turn_forces_check_and_cross_course_notifications_remain_visible(self):
        s=state();s["courses"][1]["moodle_course_ids"]=[2];light.atom(light.STATE,s)
        with patch.object(light,"refresh",return_value={"live_checked":True}) as refresh:
            light.turn("COURSE-A");light.turn("COURSE-A")
        self.assertEqual([((True,),{}),((True,),{})],refresh.call_args_list)
        snap=light.read(light.SNAPSHOT);snap["threads"][0]["course_id"]="COURSE-B";light.atom(light.SNAPSHOT,snap)
        self.assertTrue(any(r["course_id"]=="COURSE-B" for r in light.pending()["items"]))

    def test_scope_limit_is_durable_high_priority_and_requires_review_when_resolved(self):
        self.advance(lambda s:s.update(scope_limits=[{"scope":"module:99","reason":"inaccessible"}]))
        light.scan()
        row=light.pending()["items"][0];self.assertEqual("collection_issue",row["kind"])
        self.advance(lambda s:s.update(scope_limits=[]))
        rows=light.pending(None,0,100)["items"]
        self.assertEqual(2,len([r for r in rows if r["id"]==row["id"]]))
        self.assertTrue(any(r["availability"]=="resolved" for r in rows))

    def test_queue_cursor_rejects_changes_instead_of_skipping_items(self):
        p=light.pending(None,0,2)
        row=p["items"][0]
        light.accept(row["id"],row["hash"],"read",row["event_id"],"visual review")
        with self.assertRaisesRegex(ValueError,"队列已变化"):
            light.pending(None,2,2,p["queue_version"])

    def test_media_cannot_be_silently_acknowledged(self):
        row=next(r for r in light.pending()["items"] if r["id"]=="post:30")
        with self.assertRaisesRegex(ValueError,"图片或附件"):
            light.accept(row["id"],row["hash"],"Read text only",row["event_id"])
        self.assertTrue(any(r["id"]=="post:30" for r in light.pending()["items"]))

    def test_ordered_source_arrays_are_not_sorted_away(self):
        self.assertNotEqual(light.digest({"steps":["first","second"]}),light.digest({"steps":["second","first"]}))

    def test_large_context_has_exact_recovery_route_and_keeps_earliest_deadline(self):
        s=state()
        s["materials"]=[{"id":str(i),"course_id":"COURSE-A","title":f"Lecture {i} on conditions and exceptions"} for i in range(150)]
        s["deadlines"]=[{"id":str(i),"course_id":"COURSE-A","title":"Later deadline","date":"2026-12-01","status":"pending"} for i in range(90)]
        s["deadlines"].append({"id":"URGENT","course_id":"COURSE-A","title":"Tonight","date":"2026-10-12","status":"pending"})
        s["discussion_notes"]=[{"id":"N","course_id":"COURSE-A","title":"Exam","conclusion":"Chapter 5 is NOT examined","status":"confirmed"}]
        light.atom(light.STATE,s);ctx=light.context("COURSE-A")
        self.assertEqual("URGENT",ctx["deadlines"][0]["id"])
        self.assertIn("NOT examined",json.dumps(ctx))
        self.assertLessEqual(len(json.dumps(ctx,ensure_ascii=False)),12000)
        for key,route in ctx["more"].items():
            recovered=ctx.get(key,[])[:];offset=route["offset"]
            while True:
                p=light.listing(key,"COURSE-A",offset=offset,limit=17,revision=ctx["revision"])
                recovered+=p["items"]
                if not p["has_more"]:break
                offset=p["next_offset"]
            self.assertEqual(light.listing_rows(s,key,"COURSE-A"),recovered)

    def test_revision_checked_paging_and_batch_exact_content(self):
        with self.assertRaisesRegex(ValueError,"状态版本"):light.listing("materials",revision=999)
        result=light.bundle([{"collection":"courses","id":"COURSE-A","field":"orientation"}])
        self.assertEqual(state()["courses"][0]["orientation"],result["items"][0]["data"])

    def test_review_page_contains_exact_bodies_or_explicit_source_paging(self):
        page=light.review_page()
        raw=light.records(light.read(light.SNAPSHOT))
        for row in page["items"]:
            self.assertEqual(raw[row["id"]]["body"],row["body"])
        self.advance(lambda s:s["threads"][0]["posts"][0].update(message="Synthetic long source. "*3000))
        page=light.review_page(limit=100,maximum=2500)
        self.assertTrue(page["has_more"])
        offset=0;saw_paged=False
        while True:
            p=light.review_page(offset=offset,limit=100,maximum=2500)
            self.assertLessEqual(len(json.dumps(p,ensure_ascii=False)),2500)
            saw_paged=saw_paged or any(r.get("requires_source_paging") for r in p["items"])
            if not p["has_more"]:break
            offset=p["next_offset"]
        self.assertTrue(saw_paged)

    def test_batch_accept_is_all_or_nothing(self):
        rows=light.pending(None,0,12)["items"][:2]
        requests=[{"id":r["id"],"hash":r["hash"],"event":r["event_id"],"evidence":"Synthetic review","media_evidence":"Synthetic image"} for r in rows]
        original=light.STATE.read_bytes()
        invalid=deepcopy(requests);invalid[-1]["hash"]="invalid"
        with self.assertRaises(ValueError):light.accept_many(invalid)
        self.assertEqual(original,light.STATE.read_bytes())
        result=light.accept_many(requests);self.assertEqual(2,result["count"])
        remaining={r["event_id"] for r in light.pending()["items"]}
        self.assertFalse(remaining.intersection(r["event_id"] for r in rows))

    def test_inbox_only_lists_unindexed_files_in_this_project(self):
        folder=light.ROOT/"Study/_Inbox";folder.mkdir()
        (folder/"lecture.pdf").write_bytes(b"SYNTHETIC")
        (folder/"known.pdf").write_bytes(b"SYNTHETIC")
        s=state();s["materials"]=[{"id":"KNOWN","relative_path":"_Inbox/known.pdf","sha256":light.hashlib.sha256(b"SYNTHETIC").hexdigest()}];light.atom(light.STATE,s)
        result=light.inbox();self.assertEqual(1,result["unindexed_count"])
        self.assertEqual("_Inbox/lecture.pdf",result["items"][0]["path"])
        (folder/"known.pdf").write_bytes(b"REVISED SYNTHETIC")
        result=light.inbox()
        self.assertEqual("changed",next(r for r in result["items"] if r["path"]=="_Inbox/known.pdf")["status"])
        s["materials"][0].pop("sha256");light.atom(light.STATE,s)
        self.assertEqual("indexed_needs_content_check",next(r for r in light.inbox()["items"] if r["path"]=="_Inbox/known.pdf")["status"])

if __name__=="__main__":unittest.main()
