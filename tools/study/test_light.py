"""Synthetic-only regressions for bounded context, source review and cache failures."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import light


def snapshot():
    return {'finished_at':datetime.now(timezone.utc).isoformat(),'collection_complete':True,
            'pages':[{'courseid':1,'course_id':'COURSE-A','sections':[{'id':10,'name':'Unit','summary':'original','modules':[]}]}],
            'threads':[{'course_id':'COURSE-A','discussion':{'discussion':20,'name':'Exam'},
                        'posts':[{'id':30,'subject':'Scope','message':'Not including Unit 3. <img src="figure-a.png">',
                                  'author':{'id':4,'fullname':'Example Teacher'},'timemodified':123}]}],
            'assignments':{'courses':[{'id':1,'assignments':[{'id':40,'name':'Homework','duedate':100}]}]},
            'submissions':[],'quizzes':{'quizzes':[]},'attempts':[],'calendar':{'events':[]},'errors':[]}


def state():
    return {'revision':0,'study_root':'Study','timezone':'UTC','settings':{'lightweight':{'moodle_cache_minutes':30}},
            'courses':[{'id':'COURSE-A','name':'Example A','moodle_course_ids':[1],'current_topic':'Unit 1','orientation':{'method':'Use teacher notation'},'teaching_cursor':{'stage':'needs independent attempt'}},
                       {'id':'COURSE-B','name':'Example B','current_topic':'PRIVATE_OTHER_COURSE'}],
            'materials':[],'tasks':[],'deadlines':[],'mistakes':[],'discussion_notes':[],
            'mock_exams':[{'id':'EXAMPLE','answer_key':'HIDDEN_ANSWER'}], 'integrations':{}}


class LightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);system=root/'Study/_System';system.mkdir(parents=True)
        for k,v in {'ROOT':root,'SYSTEM':system,'STATE':system/'state.json','SNAPSHOT':system/'refresh-latest.json',
                    'INDEX':system/'lightweight-index.json','REPORT':system/'lightweight-delta.json','LOCK':system/'lightweight.lock'}.items():
            patcher=patch.object(light,k,v);patcher.start();self.addCleanup(patcher.stop)
        light.atom(light.STATE,state());light.atom(light.SNAPSHOT,snapshot())

    def test_context_is_local_bounded_and_does_not_expose_other_courses_or_answers(self):
        s=state();s['materials']=[{'id':str(i),'course_id':'COURSE-A','title':'Material '*80} for i in range(80)]
        light.atom(light.STATE,s);before=light.STATE.read_bytes()
        with patch.object(light.subprocess,'run',side_effect=AssertionError('Unexpected network/process')):
            value=light.context('COURSE-A',2500)
        text=json.dumps(value,ensure_ascii=False)
        self.assertLessEqual(len(text),2500)
        self.assertNotIn('PRIVATE_OTHER_COURSE',text);self.assertNotIn('HIDDEN_ANSWER',text)
        self.assertTrue(value['omitted']);self.assertEqual(before,light.STATE.read_bytes())
        self.assertIn('orientation',value['detail_fields'])

    def test_unknown_course_is_not_silently_replaced_by_all_courses(self):
        with self.assertRaises(ValueError):light.context('UNKNOWN')

    def test_exact_source_pagination_reassembles_without_loss(self):
        expected=json.dumps(light.records(light.read(light.SNAPSHOT))['post:30'],ensure_ascii=False,indent=2)
        chunks=[]
        for offset in range(0,len(expected),37):
            v=light.source('post:30',offset,37);chunks.append(v['content'])
            self.assertTrue(v['partial_is_not_full_review'])
        self.assertEqual(expected,''.join(chunks));self.assertIn('Not including Unit 3',expected)

    def test_same_content_with_new_collection_time_is_not_a_change(self):
        old=snapshot();index={k:light.brief(v) for k,v in light.records(old).items()}
        new=deepcopy(old);new['finished_at']=datetime.now(timezone.utc).isoformat()
        result,_=light.build_delta(new,index,{})
        self.assertEqual([],result['changes']);self.assertGreater(len(result['pending_review']),0)

    def test_body_author_image_and_deadline_changes_are_detected(self):
        old=snapshot();index={k:light.brief(v) for k,v in light.records(old).items()}
        for key,value in [('message','New requirement'),('author',{'id':7}),('message','<img src="figure-b.png">')]:
            new=deepcopy(old);new['threads'][0]['posts'][0][key]=value
            result,_=light.build_delta(new,index,{})
            self.assertIn('post:30',[r['id'] for r in result['changes']])
        new=deepcopy(old);new['assignments']['courses'][0]['assignments'][0]['duedate']=200
        result,_=light.build_delta(new,index,{})
        self.assertIn('assignment:40',[r['id'] for r in result['changes']])

    def test_partial_collection_keeps_complete_index_and_pending_missing_sources(self):
        light.scan();baseline=light.INDEX.read_bytes()
        previous=light.read(light.SNAPSHOT);light.atom(light.SYSTEM/'refresh-last-complete.json',previous)
        partial=deepcopy(previous);partial['collection_complete']=False;partial['threads'][0]['posts']=None
        light.atom(light.SNAPSHOT,partial);report=light.scan()
        self.assertEqual(baseline,light.INDEX.read_bytes())
        self.assertFalse(any(r['change']=='no_longer_visible' for r in report['changes']))
        pending=light.pending(None,0,20)
        row=next(x for x in pending['items'] if x['id']=='post:30')
        self.assertEqual('unavailable_in_this_collection',row['availability'])
        self.assertTrue(light.source('post:30',0,6000)['from_last_complete'])

    def test_complete_absence_is_not_reported_as_school_deletion(self):
        old=snapshot();index={k:light.brief(v) for k,v in light.records(old).items()}
        new=deepcopy(old);new['threads']=[]
        report,_=light.build_delta(new,index,{})
        self.assertTrue(report['absence_is_not_deletion'])
        self.assertEqual('no_longer_visible',next(r for r in report['changes'] if r['id']=='post:30')['change'])

    def test_cache_honors_force_age_failure_and_timezone(self):
        snap=snapshot();s=state()
        self.assertTrue(light.cached_ok(snap,s));self.assertFalse(light.cached_ok(snap,s,True))
        stale=deepcopy(snap);stale['finished_at']=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        self.assertFalse(light.cached_ok(stale,s))
        future=deepcopy(snap);future['finished_at']=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        self.assertFalse(light.cached_ok(future,s))
        s['integrations']['lite_moodle']={'last_attempt':{'at':datetime.now(timezone.utc).isoformat(),'collection_complete':False}}
        self.assertFalse(light.cached_ok(snap,s))

    def test_failed_live_refresh_preserves_snapshot_and_blocks_cache(self):
        before=light.SNAPSHOT.read_bytes()
        with patch.object(light.shutil,'which',return_value=__import__('sys').executable):
            with patch.object(light.subprocess,'run',side_effect=light.subprocess.TimeoutExpired('node',600)):
                with self.assertRaisesRegex(ValueError,'未完整刷新'):light.refresh(True)
        self.assertEqual(before,light.SNAPSHOT.read_bytes())
        updated=light.read(light.STATE)
        self.assertFalse(updated['integrations']['lite_moodle']['last_attempt']['collection_complete'])
        self.assertFalse(light.cached_ok(light.read(light.SNAPSHOT),updated))

    def test_cached_refresh_is_explicit_and_starts_no_process(self):
        with patch.object(light.subprocess,'run',side_effect=AssertionError('Unexpected process')):
            result=light.refresh(False)
        self.assertEqual('cached',result['mode']);self.assertFalse(result['live_checked'])

    def test_accept_requires_current_hash_and_actual_review_and_requeues_edits(self):
        h=light.records(light.read(light.SNAPSHOT))['post:30']['hash']
        with self.assertRaises(ValueError):light.accept('post:30','old-hash','reviewed')
        with self.assertRaises(ValueError):light.accept('post:30',h,'')
        light.accept('post:30',h,'Synthetic test: reviewed teacher role and original requirement',media_evidence='Synthetic image checked')
        self.assertNotIn('post:30',[x['id'] for x in light.pending(None,0,20)['items']])
        self.assertTrue(light.STATE.with_name('state.previous.json').is_file())
        snap=light.read(light.SNAPSHOT);snap['threads'][0]['posts'][0]['message']='Changed condition';light.atom(light.SNAPSHOT,snap)
        self.assertIn('post:30',[x['id'] for x in light.pending(None,0,20)['items']])

    def test_incomplete_snapshot_cannot_be_accepted(self):
        snap=snapshot();snap['collection_complete']=False;light.atom(light.SNAPSHOT,snap)
        with self.assertRaises(ValueError):light.accept('post:30',light.records(snap)['post:30']['hash'],'reviewed')

    def test_blank_state_needs_own_courses_before_network(self):
        s=state();s['courses']=[];light.atom(light.STATE,s)
        with patch.object(light.subprocess,'run',side_effect=AssertionError('Unexpected network')):
            with self.assertRaisesRegex(ValueError,'选择课程'):light.refresh(True)

    def test_missing_state_has_setup_instruction_and_creates_nothing(self):
        light.STATE.unlink()
        with self.assertRaisesRegex(ValueError,'setup.cmd'):light.context()
        self.assertFalse(light.STATE.exists())

    def test_doctor_rejects_cross_project_material_path(self):
        s=state();s['materials']=[{'id':'ESCAPE','relative_path':'../../other-project/private.pdf'}]
        light.atom(light.STATE,s)
        result=light.doctor()
        self.assertEqual(['ESCAPE'],result['missing_material_ids']);self.assertTrue(result['independent_state'])

class SourcePackageTests(unittest.TestCase):
    def test_source_allowlist_excludes_personal_and_dependency_directories(self):
        import importlib.util
        script=Path(__file__).resolve().parents[1]/'release/package_source.py'
        spec=importlib.util.spec_from_file_location('source_package',script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for path in ['README.md','tools/study/light.py','docs/WORKFLOW.md','templates/config.example.json',
                         'Study/_System/state.json','.private/moodle-token.dpapi','config.local.json',
                         'runtime.local.json','.venv/secret.py','tools/__pycache__/hidden.py']:
                p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic',encoding='utf-8')
            names=[p.relative_to(root).as_posix() for p in module.sources(root)]
            self.assertEqual(sorted(['README.md','tools/study/light.py','docs/WORKFLOW.md','templates/config.example.json']),sorted(names))

if __name__=='__main__':unittest.main()
