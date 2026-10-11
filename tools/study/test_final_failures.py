"""Delivery regressions use only synthetic exam evidence and temporary state."""
from copy import deepcopy
import unittest
import subprocess
import sys
from unittest.mock import patch
import light
import test_light as fixtures
import exam_sources
from test_exam_sources import registered, NOW

class ExamMediaRegressions(unittest.TestCase):
    def test_image_only_or_attachment_change_invalidates_official_requirements(self):
        for field, value in (("message", '10 multiple choice questions <img src="new-scope.png">'),
                             ("attachments", [{"filename":"scope.pdf","fileurl":"https://example.test/new.pdf"}])):
            with self.subTest(field=field):
                state, snap = registered()
                snap["threads"][0]["posts"][0][field] = value
                exam_sources.sync_profiles(state, snap, NOW)
                self.assertEqual("needs_review", state["exam_profiles"][0]["verification_status"])

    def test_unchanged_media_does_not_invalidate_a_reviewed_profile(self):
        state, snap = registered()
        exam_sources.sync_profiles(state, deepcopy(snap), NOW)
        self.assertEqual("verified", state["exam_profiles"][0]["verification_status"])

class RefreshFailureRegressions(unittest.TestCase):
    setUp = fixtures.LightTests.setUp

    def install_exam(self):
        state, snap = registered()
        state.update(revision=0,timezone="UTC",settings={},integrations={})
        state["courses"][0]["moodle_course_ids"]=[1]
        light.atom(light.STATE,state);light.atom(light.SNAPSHOT,snap)

    def test_invalid_json_refresh_marks_exam_and_attempt_incomplete(self):
        self.install_exam()
        def run(*args,**kwargs):
            light.SNAPSHOT.write_text("{broken synthetic json",encoding="utf-8")
            return subprocess.CompletedProcess(args[0],0,"","")
        with patch.object(light.shutil,"which",return_value=sys.executable),patch.object(light.subprocess,"run",side_effect=run):
            with self.assertRaisesRegex(ValueError,"待核读"):light.refresh(True)
        state=light.read(light.STATE)
        self.assertEqual("needs_review",state["exam_profiles"][0]["verification_status"])
        self.assertFalse(state["integrations"]["lite_moodle"]["last_attempt"]["collection_complete"])
        self.assertEqual("{broken synthetic json",light.SNAPSHOT.read_text(encoding="utf-8"))

    def test_unreadable_journal_also_invalidates_exam_without_overwriting_it(self):
        self.install_exam()
        dbpath=light.SYSTEM/"notification-journal.sqlite3"
        dbpath.write_bytes(b"SYNTHETIC BROKEN DATABASE")
        with self.assertRaisesRegex(ValueError,"待核读"):light.refresh(True)
        self.assertEqual("needs_review",light.read(light.STATE)["exam_profiles"][0]["verification_status"])
        self.assertEqual(b"SYNTHETIC BROKEN DATABASE",dbpath.read_bytes())

    def test_clock_rollback_keeps_body_but_refuses_current_completeness(self):
        from datetime import datetime, timedelta
        self.install_exam()
        old=light.read(light.SNAPSHOT);db=light.journal();db.close()
        late=deepcopy(old)
        late["finished_at"]=(datetime.fromisoformat(old["finished_at"])-timedelta(minutes=1)).isoformat()
        late["threads"][0]["posts"][0]["message"]="URGENT: exam moved to Thursday"
        def run(*args,**kwargs):
            light.atom(light.SNAPSHOT,late)
            return subprocess.CompletedProcess(args[0],0,"","")
        with patch.object(light.shutil,"which",return_value=sys.executable),patch.object(light.subprocess,"run",side_effect=run):
            with self.assertRaisesRegex(ValueError,"校准系统时间"):light.refresh(True)
        self.assertFalse(light.health()["collection_complete"])
        db=light.journal()
        try:self.assertTrue(any("Thursday" in str(e["record"]) and e["availability"]=="observed_late" for e in db.events()))
        finally:db.close()

    def test_linked_module_content_requires_actual_source_review(self):
        for kind in ("resource","folder","page","book","url"):
            media=light.media_requirements({"kind":"module","body":{"modname":kind,"url":"https://example.test/source"}})
            self.assertTrue(media["attachments"])
            self.assertEqual("browser",media["attachments"][0]["read_with"])

    def test_multiple_issues_in_the_same_scope_are_all_retained(self):
        snap={"errors":[{"scope":"assignment_catalog","error":"A inaccessible"},
                        {"scope":"assignment_catalog","error":"B inaccessible"}]}
        values=list(light.records(snap).values())
        self.assertEqual(2,len(values))
        self.assertEqual({"A inaccessible","B inaccessible"},{v["body"]["detail"]["error"] for v in values})

if __name__ == "__main__": unittest.main()
