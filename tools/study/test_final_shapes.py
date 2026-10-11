"""Malformed snapshots must fail closed; fixtures never read a real study profile."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
import light
import test_light as fixtures
from test_exam_sources import registered


class SnapshotShapeRegressions(unittest.TestCase):
    setUp=fixtures.LightTests.setUp

    def install_exam(self):
        state,snap=registered()
        state.update(revision=0,timezone="UTC",settings={},integrations={})
        state["courses"][0]["moodle_course_ids"]=[1]
        light.atom(light.STATE,state);light.atom(light.SNAPSHOT,snap)
        return snap

    def test_invalid_json_shapes_invalidate_exam_and_do_not_report_complete(self):
        mutations=[lambda s:"synthetic invalid root",lambda s:[],lambda s:None,
                   lambda s:dict(s,assignments="synthetic invalid assignments"),
                   lambda s:dict(s,assignments=[]),lambda s:dict(s,quizzes=True),
                   lambda s:dict(s,calendar="synthetic invalid calendar"),
                   lambda s:dict(s,pages=[1]),lambda s:dict(s,threads=[{"discussion":[]}]),
                   lambda s:dict(s,finished_at=123),lambda s:dict(s,finished_at="2026-10-12T10:00:00")]
        for index,mutate in enumerate(mutations):
            with self.subTest(shape=index):
                original=self.install_exam()
                broken=mutate(dict(original,finished_at=light.now()))
                def run(*args,**kwargs):
                    light.atom(light.SNAPSHOT,broken)
                    return subprocess.CompletedProcess(args[0],0,"","")
                with patch.object(light.shutil,"which",return_value=sys.executable),patch.object(light.subprocess,"run",side_effect=run):
                    with self.assertRaisesRegex(ValueError,"待核读"):light.refresh(True)
                state=light.read(light.STATE)
                self.assertEqual("needs_review",state["exam_profiles"][0]["verification_status"])
                self.assertFalse(state["integrations"]["lite_moodle"]["last_attempt"]["collection_complete"])
                self.assertFalse(light.health()["collection_complete"])
                self.assertEqual(broken,json.loads(light.SNAPSHOT.read_text(encoding="utf-8")))

    def test_invalid_spool_is_retained_and_valid_spool_recovers_after_repair(self):
        original=self.install_exam()
        late=deepcopy(original);late["finished_at"]=light.now()
        late["threads"][0]["posts"][0]["message"]="URGENT synthetic revised exam notice"
        valid_path=light.SYSTEM/"collections/valid.json"
        invalid_path=light.SYSTEM/"collections/invalid.json"
        light.atom(valid_path,late);light.atom(invalid_path,"SYNTHETIC INVALID SPOOL")
        before=valid_path.read_bytes(),invalid_path.read_bytes()
        with self.assertRaisesRegex(ValueError,"待核读"):light.refresh(True)
        self.assertEqual(before,(valid_path.read_bytes(),invalid_path.read_bytes()))
        repaired=deepcopy(late)
        repaired["finished_at"]=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()
        light.atom(invalid_path,repaired)
        db=light.journal()
        try:
            self.assertTrue(any("URGENT" in str(e["record"]) for e in db.events()))
        finally:db.close()
        self.assertFalse(valid_path.exists());self.assertFalse(invalid_path.exists())
        self.assertFalse(light.health()["collection_complete"])

    def test_health_rejects_invalid_shape_even_without_a_previous_attempt(self):
        for invalid in ("SYNTHETIC",[],None,{"collection_complete":True,"assignments":[]}):
            light.atom(light.SNAPSHOT,invalid)
            health=light.health()
            self.assertFalse(health["collection_complete"])
            self.assertTrue(any(e.get("scope")=="local_snapshot" for e in health["errors"]))


if __name__=="__main__":unittest.main()
