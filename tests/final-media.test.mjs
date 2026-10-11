import test from 'node:test';
import assert from 'node:assert/strict';
import {forumImageSources,forumImage} from '../tools/moodle/forum-image.mjs';

test('forum image indices and URL entities match the local media review route',()=>{
  assert.deepEqual(forumImageSources('<img data-src="ignore.png" src="first.png?a=1&amp;b=2"><img src=second.png><img src=""><img src="third.png?x=&#49;">'),
    ['first.png?a=1&b=2','second.png','third.png?x=1']);
});

test('an unquoted forum source can be checked against its archived URL',async()=>{
  const client={baseUrl:'https://school.example/moodle',token:'synthetic-token',
    call:async()=>({posts:[{id:3,message:'<img src=https://school.example/moodle/webservice/pluginfile.php/image.png?a=&#49;>'}]})};
  let requested;
  const result=await forumImage(client,{discussionid:1,postid:3,index:0,
    expected_src:'https://school.example/moodle/webservice/pluginfile.php/image.png?a=1'},async(url)=>{
      requested=new URL(url);
      return new Response(new Uint8Array([137,80,78,71,13,10,26,10]),{status:200});
    });
  assert.equal(requested.searchParams.get('a'),'1');
  assert.equal(requested.searchParams.get('token'),'synthetic-token');
  assert.equal(result.mimeType,'image/png');
  assert.equal(result.post_id,3);
});
