import { createHash } from 'node:crypto';

function imageType(bytes) {
  if (bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) return 'image/png';
  if (bytes[0]===255 && bytes[1]===216 && bytes[2]===255) return 'image/jpeg';
  if (/^GIF8[79]a/.test(bytes.subarray(0,6).toString('ascii'))) return 'image/gif';
  if (bytes.subarray(0,4).toString()==='RIFF' && bytes.subarray(8,12).toString()==='WEBP') return 'image/webp';
  throw new Error('论坛图片格式不支持；保持待核读，用本人浏览器检查');
}

function decodeImageUrl(value) {
  return value.replace(/&(?:amp|quot|apos|lt|gt|#\d+|#x[\da-f]+);/gi, entity => {
    const named={'&amp;':'&','&quot;':'"','&apos;':"'",'&lt;':'<','&gt;':'>'};
    if (named[entity.toLowerCase()]) return named[entity.toLowerCase()];
    const body=entity.slice(2,-1),number=body[0].toLowerCase()==='x' ? parseInt(body.slice(1),16) : parseInt(body,10);
    return number>0 && number<=0x10ffff && !(number>=0xd800 && number<=0xdfff) ? String.fromCodePoint(number) : '\ufffd';
  });
}

export function forumImageSources(message) {
  return [...String(message ?? '').matchAll(/<img\b[^>]*?\ssrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/gi)]
    .map(match=>decodeImageUrl(match[1] || match[2] || match[3] || '')).filter(Boolean);
}

export async function forumImage(client, {discussionid,postid,index=0,expected_src}, transport=fetch) {
  if (!Number.isSafeInteger(discussionid) || discussionid<=0 || !Number.isSafeInteger(index) || index<0)
    throw new Error('图片编号无效');
  const posts=await client.call('mod_forum_get_discussion_posts',{discussionid,sortby:'created',sortdirection:'ASC'});
  if (!Array.isArray(posts.posts)) throw new Error('无法读取论坛正文；保持待核读');
  if (postid !== undefined && (!Number.isSafeInteger(postid) || postid<=0)) throw new Error('帖子编号无效');
  const images=posts.posts.filter(post=>postid===undefined || post.id===postid).flatMap(post => forumImageSources(post.message)
    .map(url=>({post_id:post.id,url})));
  const entry=images[index];
  if (!entry) throw new Error('没有这个图片；保持待核读');
  const base=new URL(client.baseUrl);
  const url=new URL(entry.url,base);
  const prefix=base.pathname.replace(/\/$/,'')+'/webservice/pluginfile.php/';
  if (url.protocol!=='https:' || url.origin!==base.origin || !url.pathname.startsWith(prefix) || url.username || url.password)
    throw new Error('图片不是本校受支持的论坛文件地址；用本人浏览器核读');
  if (expected_src !== undefined) {
    const expected=new URL(decodeImageUrl(expected_src),base);
    const actual=new URL(url);
    for (const key of ['wstoken','token','sesskey']) {expected.searchParams.delete(key);actual.searchParams.delete(key);}
    if (expected.href!==actual.href) throw new Error('论坛图片来源已变化；不要把新图当作旧版本，保持旧版本待核读');
  }
  for (const key of ['wstoken','token','sesskey']) url.searchParams.delete(key);
  url.searchParams.set('token',client.token);
  let bytes;
  try {
    const response=await transport(url,{redirect:'error',signal:AbortSignal.timeout(30000)});
    if (!response.ok || !response.body || Number(response.headers.get('content-length'))>10*1024*1024) throw new Error();
    const chunks=[];let size=0;
    for await (const chunk of response.body) {
      size+=chunk.byteLength;
      if (size>10*1024*1024) throw new Error();
      chunks.push(Buffer.from(chunk));
    }
    bytes=Buffer.concat(chunks);
  } catch { throw new Error('论坛图片读取失败或超过10MiB；保持待核读'); }
  return {post_id:entry.post_id,index,mimeType:imageType(bytes),data:bytes.toString('base64'),
          sha256:createHash('sha256').update(bytes).digest('hex')};
}
