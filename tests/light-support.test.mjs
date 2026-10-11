import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync,readdirSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve,dirname} from 'node:path';
import {initialize,ReadOnlyClient} from '../tools/moodle/core.mjs';
import {storeSnapshot} from '../tools/moodle/snapshot-store.mjs';
import {collectProgress,applyProgress} from '../tools/moodle/progress.mjs';
import {forumImage} from '../tools/moodle/forum-image.mjs';

test('every collected version is spooled before heads are replaced; partial retains complete head',()=>{
  const root=mkdtempSync(join(tmpdir(),'light-spool-'));
  try {
    initialize(root);
    const complete={finished_at:'2026-10-12T00:00:00Z',collection_complete:true,threads:[{id:1}]};
    const partial={finished_at:'2026-10-12T00:01:00Z',collection_complete:false,errors:[{scope:'forum'}]};
    storeSnapshot(root,complete);storeSnapshot(root,partial);
    const dir=join(root,'Study/_System');
    assert.equal(readdirSync(join(dir,'collections')).length,2);
    assert.deepEqual(JSON.parse(readFileSync(join(dir,'refresh-last-complete.json'))),complete);
    assert.deepEqual(JSON.parse(readFileSync(join(dir,'refresh-latest.json'))),partial);
  } finally {
    assert.equal(dirname(resolve(root)),resolve(tmpdir()));
    rmSync(root,{recursive:true,force:true});
  }
});

test('progress keeps platform status separate from learning position and retains failed pages',async()=>{
  const state={courses:[{id:'A',moodle_course_ids:[1,2],current_topic:'KEEP',teaching_cursor:{topic:'KEEP'},
    moodle_progress:{pages:[{courseid:2,sections:[{name:'last successful'}]}]}}]};
  const client={userId:5,call:async(method,args)=>{
    if(args.courseid===2)throw new Error('synthetic timeout');
    if(method==='core_course_get_contents')return [{id:1,name:'Chapter 9',modules:[{id:10,name:'Exercise'}]}];
    return {statuses:[{cmid:10,state:3,tracking:1,timecompleted:123}]};
  }};
  const report=await collectProgress(client,state);
  const result=applyProgress(state,report);
  assert.equal(report.collection_complete,false);
  assert.equal(result.courses[0].current_topic,'KEEP');
  assert.deepEqual(result.courses[0].teaching_cursor,{topic:'KEEP'});
  assert.equal(result.courses[0].moodle_progress.pages.find(p=>p.courseid===1).sections[0].activities[0].state,3);
  assert.equal(result.courses[0].moodle_progress.pages.find(p=>p.courseid===2).sections[0].name,'last successful');
  assert(!JSON.stringify(result).includes('percent'));
  assert.equal(state.courses[0].moodle_progress.pages.length,1);
});

const png=Buffer.from([137,80,78,71,13,10,26,10,0,0,0,0]);
const client=url=>({baseUrl:'https://school.example/moodle',token:'SYNTHETIC_SECRET',call:async()=>({posts:[
  {id:30,message:'<p>考试范围见图</p><img src="'+url+'">'}]})});

test('forum image comes only from an actual post, returns pixels and no credential',async()=>{
  const result=await forumImage(client('https://school.example/moodle/webservice/pluginfile.php/1/a.png?token=OLD&amp;x=1'),
    {discussionid:1},async(url,options)=>{
      assert.equal(url.searchParams.get('token'),'SYNTHETIC_SECRET');
      assert.equal(url.searchParams.get('x'),'1');
      assert.equal(options.redirect,'error');
      return new Response(png);
    });
  assert.equal(result.mimeType,'image/png');assert.equal(result.post_id,30);
  assert.deepEqual(Buffer.from(result.data,'base64'),png);
  assert(!JSON.stringify(result).includes('SYNTHETIC_SECRET'));
});

test('forum image rejects other hosts, other paths, redirects and non-images',async()=>{
  for (const url of ['https://evil.example/webservice/pluginfile.php/x','https://school.example/moodle/login/index.php',
                     'https://school.example/webservice/pluginfile.php/x','http://school.example/moodle/webservice/pluginfile.php/x']) {
    await assert.rejects(forumImage(client(url),{discussionid:1},async()=>{throw new Error('must not request');}),/本校/);
  }
  const c=client('https://school.example/moodle/webservice/pluginfile.php/x');
  await assert.rejects(forumImage(c,{discussionid:1},async()=>new Response('login page')),/格式/);
  await assert.rejects(forumImage(c,{discussionid:1},async()=>new Response(null,{status:302,headers:{location:'https://evil.example'}})),/失败/);
  await assert.rejects(forumImage(c,{discussionid:1},async()=>new Response(png,{headers:{'content-length':String(11*1024*1024)}})),/失败/);
});

test('completion lookup is read-only and no completion setter is allowed',async()=>{
  const c=new ReadOnlyClient('https://school.example','fake',async()=>({ok:true,json:async()=>({statuses:[]})}));
  assert.deepEqual(await c.call('core_completion_get_activities_completion_status'),{statuses:[]});
  await assert.rejects(c.call('core_completion_update_activity_completion_status_manually'),/not allowed/);
});

test('image preview selects the source post and rejects changed image URLs',async()=>{
  const c=client('https://school.example/moodle/webservice/pluginfile.php/first.png');
  c.call=async()=>({posts:[
    {id:10,message:'<img src="https://school.example/moodle/webservice/pluginfile.php/first.png">'},
    {id:30,message:'<img src="https://school.example/moodle/webservice/pluginfile.php/right.png">'}
  ]});
  const args={discussionid:1,postid:30,index:0,expected_src:'https://school.example/moodle/webservice/pluginfile.php/right.png'};
  await forumImage(c,args,async url=>{assert(url.pathname.endsWith('/right.png'));return new Response(png);});
  await assert.rejects(forumImage(c,{...args,expected_src:'https://school.example/moodle/webservice/pluginfile.php/old.png'},async()=>{throw new Error('must not request');}),/已变化/);
});
