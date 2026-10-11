"""Manual exam commands may not override a failed or stale lite refresh."""
from copy import deepcopy
from datetime import timedelta
import unittest
import exam_sources
import daily
import light
import test_light as fixtures
from test_exam_sources import registered, profile, NOW

class ExamRefreshGateTests(unittest.TestCase):
    setUp = fixtures.LightTests.setUp

    def install(self):
        state,snap=registered()
        state.update(revision=0,timezone="UTC",settings={},integrations={})
        light.atom(light.STATE,state);light.atom(light.SNAPSHOT,snap)
        return state,snap

    def test_failed_refresh_cannot_be_cleared_by_manual_profile_or_sync(self):
        _,snap=self.install();light.sync_attempt(snap,False,"Synthetic network failure")
        state=light.read(light.STATE)
        with self.assertRaisesRegex(ValueError,"刷新失败"):
            exam_sources.register_profile(state,profile(),snap,NOW)
        result=exam_sources.sync_profiles(state,snap,NOW)
        self.assertFalse(result["collection_complete"])
        self.assertEqual("needs_review",state["exam_profiles"][0]["verification_status"])

    def test_manual_cli_dispatch_keeps_failed_refresh_unverified(self):
        _,snap=self.install();light.sync_attempt(snap,False,"Synthetic failure")
        original=light.STATE.read_bytes()
        intake=daily.execute(light.STATE,"exam-intake",NOW,snapshot=snap)
        self.assertFalse(intake["collection_complete"])
        self.assertIn("刷新失败",intake["source_issue"])
        with self.assertRaisesRegex(ValueError,"刷新失败"):
            daily.execute(light.STATE,"exam-profile",NOW,payload=profile(),snapshot=snap)
        self.assertEqual(original,light.STATE.read_bytes())

    def test_old_snapshot_is_rejected_after_a_new_successful_refresh(self):
        _,old=self.install();fresh=deepcopy(old)
        fresh["finished_at"]=(NOW+timedelta(minutes=1)).isoformat()
        light.sync_attempt(fresh,True,"Synthetic success")
        state=light.read(light.STATE)
        with self.assertRaisesRegex(ValueError,"最近一次"):
            exam_sources.register_profile(state,profile(),old,NOW)
        self.assertTrue(exam_sources.register_profile(state,profile(),fresh,NOW)["verified"])

    def test_retained_calendar_version_cannot_hide_its_image(self):
        media=light.media_requirements({"kind":"event","body":{"id":1,"description":"New text",
            "action_event":{"id":1,"description":'<img src="https://example.test/old-room.png">'}}})
        self.assertEqual("action_event.description",media["images"][0]["field"])
        self.assertEqual("https://example.test/old-room.png",media["images"][0]["expected_src"])

    def test_successful_recovery_can_be_reviewed_after_failure(self):
        _,snap=self.install()
        light.sync_attempt(snap,False,"Synthetic failure")
        light.sync_attempt(snap,True,"Synthetic recovery")
        state=light.read(light.STATE)
        self.assertEqual("needs_review",state["exam_profiles"][0]["verification_status"])
        self.assertTrue(state["exam_profiles"][0]["latest_source_check"]["collection_complete"])
        exam_sources.register_profile(state,profile(),snap,NOW)
        self.assertEqual("verified",state["exam_profiles"][0]["verification_status"])

if __name__=="__main__":unittest.main()
