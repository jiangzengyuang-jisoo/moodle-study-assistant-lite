import test from 'node:test';
import assert from 'node:assert/strict';
import {collectRefresh, readOrdinaryCalendar} from '../tools/moodle/refresh.mjs';
import {ReadOnlyClient} from '../tools/moodle/core.mjs';

const state = {courses:[{id:'TEST',moodle_course_ids:[101]}],tasks:[]};
function client(overrides={}) {
  const calls=[];
  return {baseUrl:'https://example.test',userId:7,calls,call:async(method,args)=>{
    calls.push({method,args});
    if(method in overrides) return typeof overrides[method] === 'function' ? overrides[method](args) : overrides[method];
    if(method==='mod_assign_get_assignments') return {courses:[]};
    if(method==='mod_quiz_get_quizzes_by_courses') return {quizzes:[]};
    if(method==='core_course_get_contents') return [{id:10,modules:[]}];
    if(method==='core_group_get_course_user_groups') return {groups:[]};
    if(method==='core_calendar_get_action_events_by_timesort' || method==='core_calendar_get_calendar_events') return {events:[]};
    if(method==='mod_assign_get_submission_status') return {lastattempt:{submission:{status:'submitted'}}};
    throw new Error('Unexpected method '+method);
  }};
}

test('ordinary course/group/site/user notices are collected even when there are no action events',async()=>{
  const c=client({
    core_group_get_course_user_groups: args=>{
      assert.equal(args.courseid,101);assert.equal(args.userid,7);return {groups:[{id:501,courseid:101}]};
    },
    core_calendar_get_calendar_events: args=>{
      assert.equal(args['events[courseids][0]'],101);
      assert.equal(args['events[groupids][0]'],501);
      assert.equal(args['options[siteevents]'],1);assert.equal(args['options[userevents]'],1);
      assert.equal(args['options[timeend]']-args['options[timestart]'],31*86400);
      assert.equal(args.limitnum,undefined);
      return {events:[
        {id:1,courseid:101,eventtype:'course',name:'Synthetic exam room changed'},
        {id:2,courseid:101,groupid:501,eventtype:'group',name:'Synthetic group session'},
        {id:3,courseid:1,eventtype:'site',name:'Synthetic campus closure'},
        {id:4,courseid:0,userid:7,eventtype:'user',name:'Synthetic personal reminder'},
      ]};
    },
  });
  const r=await collectRefresh(c,state);
  assert.equal(r.collection_complete,true);assert.equal(r.calendar.events.length,4);
  assert.deepEqual(r.calendar.events[0].course,{id:101});
  assert.deepEqual(r.calendar.coverage.groupids,[501]);
});

test('ordinary calendar is not silently capped at action-calendar page size',async()=>{
  const events=Array.from({length:151},(_,i)=>({id:i+1,courseid:101}));
  const r=await readOrdinaryCalendar(client({core_calendar_get_calendar_events:{events}}),[101],[],1,1000);
  assert.equal(r.events.length,151);
});

test('duplicate action and ordinary event IDs merge without losing either source fields',async()=>{
  const r=await collectRefresh(client({
    core_calendar_get_action_events_by_timesort:{events:[{id:1,course:{id:101},name:'Exam',action:{url:'https://example.test/task'}}]},
    core_calendar_get_calendar_events:{events:[{id:1,courseid:101,name:'Exam',description:'Room B'}]},
  }),state);
  assert.equal(r.collection_complete,true);assert.equal(r.calendar.events.length,1);
  assert.equal(r.calendar.events[0].description,'Room B');
  assert.equal(r.calendar.events[0].action.url,'https://example.test/task');
});

test('calendar changes between API reads retain both versions and require a fresh check',async()=>{
  const r=await collectRefresh(client({
    core_calendar_get_action_events_by_timesort:{events:[{id:1,name:'Exam room A'}]},
    core_calendar_get_calendar_events:{events:[{id:1,courseid:101,name:'Exam room B'}]},
  }),state);
  assert.equal(r.collection_complete,false);
  assert.equal(r.calendar.events[0].name,'Exam room B');
  assert.equal(r.calendar.events[0].action_event.name,'Exam room A');
  assert(r.errors.some(e=>e.scope==='calendar_event:1'));
});

test('ordinary calendar warnings preserve returned notices and mark collection incomplete',async()=>{
  const r=await collectRefresh(client({
    core_calendar_get_action_events_by_timesort:{events:[{id:1,name:'Action deadline'}]},
    core_calendar_get_calendar_events:{events:[{id:2,courseid:101,name:'Exam changed'}],warnings:[{warningcode:'partial'}]},
  }),state);
  assert.equal(r.collection_complete,false);assert.equal(r.calendar.events.length,2);
  assert(r.errors.some(e=>e.scope==='calendar_general'));
  assert.equal(r.calendar.coverage.ordinary_events_requested,true);
  assert.equal(r.calendar.coverage.ordinary_events,undefined);
});

test('group permission failure cannot hide ordinary course notices or be labelled complete',async()=>{
  const r=await collectRefresh(client({
    core_group_get_course_user_groups:()=>{throw new Error('Synthetic permission failure');},
    core_calendar_get_calendar_events:{events:[{id:2,courseid:101,name:'Exam changed'}]},
  }),state);
  assert.equal(r.collection_complete,false);assert.equal(r.calendar.events[0].id,2);
  assert(r.errors.some(e=>e.scope==='calendar_groups:101'));
});

test('malformed successful catalog/calendar responses cannot become complete empty collections',async()=>{
  for (const method of ['mod_assign_get_assignments','mod_quiz_get_quizzes_by_courses',
    'core_calendar_get_calendar_events','core_calendar_get_action_events_by_timesort','core_group_get_course_user_groups']) {
    for (const value of [null,[],{},'invalid']) {
      const r=await collectRefresh(client({[method]:value}),state);
      assert.equal(r.collection_complete,false,method+' '+JSON.stringify(value));
      assert(r.errors.length>0);
    }
  }
});

test('invalid assignment course/entries preserve valid siblings instead of throwing away the collection',async()=>{
  const r=await collectRefresh(client({mod_assign_get_assignments:{courses:[null,{id:101,assignments:[null,{id:99,cmid:100}]}]}}),state);
  assert.equal(r.collection_complete,false);
  assert.equal(r.assignments.courses[0].assignments[0].id,99);
  assert.equal(r.submissions[0].assignment_id,99);
  assert(r.errors.some(e=>e.scope==='assignment_catalog'));
});

test('malformed nested quiz/calendar entries retain valid notices and prevent completeness',async()=>{
  const r=await collectRefresh(client({
    mod_quiz_get_quizzes_by_courses:{quizzes:[null,{id:1,course:101,timeclose:0}]},
    core_calendar_get_calendar_events:{events:[null,{id:2,courseid:101,name:'Exam notice'}]},
  }),state);
  assert.equal(r.collection_complete,false);assert.equal(r.quizzes.quizzes[0].id,1);
  assert.equal(r.calendar.events[0].id,2);
});

test('calendar and own-group lookups remain read-only and empty valid responses remain complete',async()=>{
  const c=new ReadOnlyClient('https://example.test','SYNTHETIC',async()=>({ok:true,json:async()=>({events:[]})}));
  for(const method of ['core_calendar_get_calendar_events','core_group_get_course_user_groups']) await c.call(method);
  await assert.rejects(c.call('core_calendar_create_calendar_events'),/not allowed/);
  await assert.rejects(c.call('core_group_add_group_members'),/not allowed/);
  assert.equal((await collectRefresh(client(),state)).collection_complete,true);
});