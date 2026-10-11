"""Local, bounded context with durable source versions and explicit review."""
import argparse
from datetime import datetime, timezone
import hashlib
from html import unescape
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from notification_journal import Journal

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "Study" / "_System"
STATE = SYSTEM / "state.json"
SNAPSHOT = SYSTEM / "refresh-latest.json"
INDEX = SYSTEM / "lightweight-index.json"
REPORT = SYSTEM / "lightweight-delta.json"
LOCK = SYSTEM / "lightweight.lock"
DONE = {"completed","complete","submitted","finished","done","已完成","已提交"}

def read(path, default=None):
    if path == STATE and not path.exists():
        raise ValueError("尚未建立学习档案；请先运行 setup.cmd，再由本人连接学校和选择课程")
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default

def atom(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        json.loads(temp.read_text(encoding="utf-8"))
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()

def now():
    return datetime.now(timezone.utc).isoformat()

def canonical(v):
    if isinstance(v,dict):return {k:canonical(x) for k,x in sorted(v.items())}
    if isinstance(v,list):return [canonical(x) for x in v]
    return v

def digest(v):
    return hashlib.sha256(json.dumps(canonical(v),sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def pick(v,keys):
    return {k:v[k] for k in keys if k in v}

def validate_snapshot(snapshot):
    """Reject malformed evidence containers without discarding the original file."""
    def obj(value, label):
        if not isinstance(value,dict):raise ValueError("采集快照结构无效："+label+" 须为对象")
        return value
    def rows(value, label, objects=True):
        if not isinstance(value,list):raise ValueError("采集快照结构无效："+label+" 须为列表")
        if objects:
            for item in value:obj(item,label+"[]")
        return value
    obj(snapshot,"snapshot")
    if "collection_complete" in snapshot and not isinstance(snapshot["collection_complete"],bool):
        raise ValueError("采集快照结构无效：collection_complete 须为布尔值")
    if "finished_at" in snapshot:
        value=snapshot["finished_at"]
        if not isinstance(value,str):raise ValueError("采集快照完成时间无效")
        try:
            stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
            if stamp.tzinfo is None:raise ValueError("Missing timezone")
            stamp.timestamp()
        except (ValueError,OverflowError,OSError) as error:
            raise ValueError("采集快照完成时间无效") from error
    for field in ("submissions","attempts"):
        rows(snapshot.get(field,[]),field)
    for field in ("errors","scope_limits"):
        rows(snapshot.get(field,[]),field,False)
    for course in rows(snapshot.get("pages",[]),"pages"):
        for section in rows(course.get("sections",[]),"sections"):
            rows(section.get("modules",[]),"modules")
    for thread in rows(snapshot.get("threads",[]),"threads"):
        obj(thread.get("discussion"),"discussion")
        if thread.get("posts") is not None:rows(thread["posts"],"posts")
    for field, key in (("assignments","courses"),("quizzes","quizzes"),("calendar","events")):
        value=snapshot.get(field)
        if value is None:continue
        values=rows(obj(value,field).get(key,[]),field+"."+key)
        if field=="assignments":
            for course in values:rows(course.get("assignments",[]),"courses.assignments")


def records(snapshot):
    validate_snapshot(snapshot)
    try:return _records(snapshot)
    except (AttributeError,KeyError,TypeError) as error:
        raise ValueError("采集快照结构无效；保留原文件，不能确认完整采集") from error


def _records(snapshot):
    result={}
    coursemap={p["courseid"]:p["course_id"] for p in snapshot.get("pages",[])}
    def add(key,course,kind,title,body):
        result[key]={"id":key,"course_id":course,"kind":kind,"title":title,"hash":digest(body),"body":body}
    for p in snapshot.get("pages",[]):
        for s in p.get("sections",[]):
            add(f"section:{p['courseid']}:{s['id']}",p["course_id"],"section",s.get("name"),{k:v for k,v in s.items() if k!="modules"})
            for m in s.get("modules",[]):
                add(f"module:{m['id']}",p["course_id"],"module",m.get("name"),m)
    for t in snapshot.get("threads",[]):
        discussion=t["discussion"]
        add(f"discussion:{discussion['discussion']}",t["course_id"],"discussion",discussion.get("name"),discussion)
        for p in t.get("posts") or []:
            b=dict(p,discussion_id=discussion["discussion"],discussion_title=discussion.get("name"))
            add(f"post:{p['id']}",t["course_id"],"post",p.get("subject") or discussion.get("name"),b)
    for c in (snapshot.get("assignments") or {}).get("courses",[]):
        for a in c.get("assignments",[]):
            add(f"assignment:{a['id']}",coursemap.get(c["id"]),"assignment",a.get("name"),a)
    for a in snapshot.get("submissions",[]):
        add(f"submission:{a['assignment_id']}",coursemap.get(a["courseid"]),"submission",str(a["assignment_id"]),a)
    for q in (snapshot.get("quizzes") or {}).get("quizzes",[]):
        add(f"quiz:{q['id']}",coursemap.get(q["course"]),"quiz",q.get("name"),q)
    for a in snapshot.get("attempts",[]):
        add(f"attempts:{a['quiz_id']}",coursemap.get(a["courseid"]),"attempts",str(a["quiz_id"]),a)
    for e in (snapshot.get("calendar") or {}).get("events",[]):
        c=e.get("course",{});cid=c.get("id") if isinstance(c,dict) else c
        add(f"event:{e['id']}",coursemap.get(cid),"event",e.get("name"),e)
    for kind in ("errors","scope_limits"):
        for issue in snapshot.get(kind,[]):
            scope=issue.get("scope") if isinstance(issue,dict) else str(issue)
            key=f"issue:{kind}:{digest(issue)[:20]}"
            add(key,issue.get("course_id") if isinstance(issue,dict) else None,
                "collection_issue",kind+":"+str(scope or "unknown"),{"category":kind,"detail":issue})
    return result

def brief(r):
    return pick(r,["id","course_id","kind","title","hash"])

def reviewed_map(s):
    return s.get("integrations",{}).get("lite_moodle",{}).get("reviewed_sources",{})

def receipts(s):
    return s.get("integrations",{}).get("lite_moodle",{}).get("reviewed_events",{})

def build_delta(snapshot,previous,reviewed):
    """Compatibility comparison; durable review is handled by the journal."""
    current=records(snapshot);complete=snapshot.get("collection_complete") is True
    changed=[dict(brief(v),change="changed" if k in previous else "new_or_untracked")
             for k,v in current.items() if previous.get(k,{}).get("hash")!=v["hash"]]
    absent=[dict(brief(v),change="no_longer_visible") for k,v in previous.items() if k not in current] if complete else []
    pending=[brief(v) for k,v in current.items() if reviewed.get(k,{}).get("hash")!=v["hash"]]
    return {"checked_at":snapshot.get("finished_at"),"collection_complete":complete,"reviewed":False,
            "changes":changed+absent,"pending_review":pending,"errors":snapshot.get("errors",[]),
            "scope_limits":snapshot.get("scope_limits",[]),"absence_is_not_deletion":True},current

def journal():
    db=Journal(SYSTEM/"notification-journal.sqlite3")
    try:
        queued=sorted((SYSTEM/"collections").glob("*.json"))
        for path in queued:
            if path.is_symlink() or path.resolve().parent != (SYSTEM/"collections").resolve():
                raise ValueError("采集队列路径异常")
        snaps=[(p,read(p)) for p in queued]
        # A v1 migration can recover the last complete snapshot if no spool exists.
        if db.empty() and not snaps:
            previous=read(SYSTEM/"refresh-last-complete.json")
            if previous:snaps.append((None,previous))
        latest=read(SNAPSHOT)
        if latest:snaps.append((None,latest))
        for _,snap in snaps:validate_snapshot(snap)
        snaps.sort(key=lambda x:datetime.fromisoformat(x[1]["finished_at"].replace("Z","+00:00")).timestamp())
        legacy=reviewed_map(read(STATE))
        for path,snap in snaps:
            db.ingest(records(snap),snap,legacy)
            # Collected copies are removed only AFTER a durable SQL transaction.
            if path:
                if path.is_symlink() or path.resolve().parent != (SYSTEM/"collections").resolve():
                    raise ValueError("采集队列路径异常")
                path.unlink()
        return db
    except BaseException:
        db.close()
        raise

def health():
    problem=None
    try:
        snap=read(SNAPSHOT,{})
        records(snap)
    except (ValueError,OSError,AttributeError,KeyError,TypeError,OverflowError):
        snap={};problem={"scope":"local_snapshot","error":"采集快照损坏或结构无效；保留原档案，须修复后刷新"}
    last=read(STATE).get("integrations",{}).get("lite_moodle",{}).get("last_attempt",{})
    complete=not problem and snap.get("collection_complete") is True
    if last and not last.get("collection_complete"):complete=False
    return {"checked_at":snap.get("finished_at"),"collection_complete":complete,
            "last_attempt":last or None,"errors":snap.get("errors",[])+([problem] if problem else []),"scope_limits":snap.get("scope_limits",[])}

def event_brief(e, snapshot):
    r=e["record"];result=dict(brief(r),event_id=e["event_id"],availability=e["availability"])
    if not snapshot.get("collection_complete") and r["id"] not in records(snapshot) and e["availability"]=="visible":
        result["availability"]="unavailable_in_this_collection"
    return result

def event_order(e):
    r=e["record"];b=r.get("body",{})
    order={"collection_issue":0,"assignment":1,"event":1,"post":2,"discussion":2,"submission":3,"quiz":3,"attempts":4,"section":5,"module":5}
    due=b.get("duedate") or b.get("timestart") or b.get("timeclose")
    return (order.get(r["kind"],6),float(due) if isinstance(due,(int,float)) and due>0 else float("inf"),e["seq"])

def pending(course=None,offset=0,limit=12,queue_version=None):
    db=journal()
    try:
        rows=[e for e in db.pending(receipts(read(STATE))) if not course or e["record"].get("course_id") in (course,None)]
    finally:db.close()
    rows.sort(key=event_order)
    version=digest([e["event_id"] for e in rows])[:16]
    if queue_version and version!=queue_version:raise ValueError("待审队列已变化；从 offset 0 重新读取，不能继续旧分页")
    snap=read(SNAPSHOT,{})
    return {"collection_complete":health()["collection_complete"],"pending_review_count":len(rows),"queue_version":version,
            "offset":offset,"items":[event_brief(e,snap) for e in rows[offset:offset+limit]],"has_more":offset+limit<len(rows),
            "next_offset":offset+limit if offset+limit<len(rows) else None}

def review_page(course=None,offset=0,limit=12,maximum=12000,queue_version=None):
    """One lossless review page, without fetching metadata and then the same body again."""
    db=journal()
    try:
        rows=[e for e in db.pending(receipts(read(STATE))) if not course or e["record"].get("course_id") in (course,None)]
    finally:db.close()
    rows.sort(key=event_order)
    version=digest([e["event_id"] for e in rows])[:16]
    if queue_version and version!=queue_version:raise ValueError("待审队列已变化；从 offset 0 重新读取")
    snap=read(SNAPSHOT,{})
    out={"collection_complete":health()["collection_complete"],"pending_review_count":len(rows),"queue_version":version,
         "offset":offset,"items":[],"has_more":False}
    for e in rows[offset:offset+limit]:
        row={**event_brief(e,snap),"observed_at":e["checked_at"],"body":e["record"]["body"]}
        media=media_requirements(e["record"])
        if any(media.values()):row["media"]=media
        candidate={**out,"items":out["items"]+[row]}
        if len(json.dumps(candidate,ensure_ascii=False))>maximum-200:
            if out["items"]:break
            row=event_brief(e,snap)
            row["requires_source_paging"]=True
        out["items"].append(row)
    out["has_more"]=offset+len(out["items"])<len(rows)
    out["next_offset"]=offset+len(out["items"]) if out["has_more"] else None
    return out

def scan():
    snap=read(SNAPSHOT)
    if not snap:raise ValueError("没有采集快照，请先 refresh")
    p=pending(None,0,1000000)
    report={**health(),"reviewed":False,"changes":[dict(row,change=row["availability"]) for row in p["items"]],"pending_review":p["items"],"absence_is_not_deletion":True}
    atom(REPORT,report)
    if snap.get("collection_complete"):
        atom(INDEX,{"checked_at":snap["finished_at"],"records":{k:brief(v) for k,v in records(snap).items()}})
    return report

def sync_attempt(snapshot,success,detail):
    import review,exam_sources
    original=STATE.read_bytes();s=json.loads(original.decode("utf-8-sig"))
    checked=snapshot if success else {**(snapshot or {}),"collection_complete":False}
    s.setdefault("integrations",{}).setdefault("lite_moodle",{})["last_attempt"]={
        "at":now(),"collection_complete":success,"detail":detail,
        "snapshot_hash":exam_sources.digest(snapshot) if success else None}
    result=exam_sources.sync_profiles(s,checked,review.timestamp())
    review.save(STATE,s,original)
    return result

def cached_ok(snapshot,state,force=False):
    if force or not snapshot or snapshot.get("collection_complete") is not True:return False
    try:
        stamp=datetime.fromisoformat(snapshot["finished_at"].replace("Z","+00:00"))
        age=(datetime.now(timezone.utc)-stamp).total_seconds()
        ttl=state.get("settings",{}).get("lightweight",{}).get("moodle_cache_minutes",30)*60
        last=state.get("integrations",{}).get("lite_moodle",{}).get("last_attempt",{})
        if last and not last.get("collection_complete") and datetime.fromisoformat(last["at"])>=stamp:return False
        return 0<=age<ttl
    except (ValueError,KeyError,TypeError):return False

def refresh(force=True):
    s=read(STATE)
    if not any(c.get("moodle_course_ids") for c in s.get("courses", [])):
        raise ValueError("还没有选择课程；请先运行 choose-courses.cmd")
    fresh=None
    failure="本轮未完整刷新；采集、存档或状态核验失败"
    try:
        previous=read(SNAPSHOT)
        fresh=previous
        db=journal();db.close()  # Archive current evidence BEFORE invoking the collector.
        if cached_ok(previous,s,force):
            return {"mode":"cached","live_checked":False,**health(),"pending":review_page(),"next":"学习消息须实时检查：turn"}
        node=shutil.which("node") or read(ROOT/"runtime.local.json",{}).get("node")
        if not node or not Path(node).exists():
            raise ValueError("未找到 Node.js 22+；检查 runtime.local.json")
        completed=subprocess.run([node,str(ROOT/"tools/moodle/run.mjs"),"refresh"],cwd=ROOT,
                                 capture_output=True,text=True,encoding="utf-8",timeout=600)
        fresh=read(SNAPSHOT)
        if completed.returncode or not fresh or fresh.get("finished_at")==((previous or {}).get("finished_at")) or fresh.get("collection_complete") is not True:
            raise ValueError("Moodle 本轮未完整更新；检查网络或连接")
        report=scan()  # Durable import must succeed before reporting this attempt complete.
        db=Journal(SYSTEM/"notification-journal.sqlite3")
        try:head=db.db.execute("SELECT value FROM meta WHERE key='epoch'").fetchone()
        finally:db.close()
        if head and datetime.fromisoformat(fresh["finished_at"].replace("Z","+00:00")).timestamp()<float(head[0]):
            failure="采集时间早于已存档时间；请校准系统时间并重新刷新"
            raise ValueError(failure)
        result=sync_attempt(fresh,True,"实时采集成功；待审来源仍须逐项核读")
        return {"mode":"live","live_checked":True,"checked_at":fresh["finished_at"],
                "collection_complete":True,"errors":report["errors"],"scope_limits":report["scope_limits"],
                "profiles_needing_review":result["profiles_needing_review"],"pending":review_page(),
                "next":"已含首批原文；核读后 accept-batch，再取 review --offset 0；大项须 source 分页"}
    except (ValueError,OSError,AttributeError,KeyError,TypeError,OverflowError,sqlite3.Error,subprocess.TimeoutExpired) as error:
        # A malformed snapshot/journal must not leave old exam requirements verified.
        sync_attempt(fresh if isinstance(fresh,dict) else None,False,failure)
        archived=True
        try:
            db=journal();db.close()
        except (ValueError,OSError,AttributeError,KeyError,TypeError,OverflowError,sqlite3.Error):
            archived=False  # Keep all spool files for recovery; never replace corrupt evidence.
        try:
            db=Journal(SYSTEM/"notification-journal.sqlite3")
            try:
                failed={"finished_at":now(),"collection_complete":False,
                        "errors":[{"scope":"live_refresh","message":failure}]}
                db.ingest(records(failed),failed)
            finally:db.close()
        except (ValueError,OSError,sqlite3.Error):
            archived=False
        detail="；部分采集档案需修复，原文件未清除" if not archived else ""
        raise ValueError(failure+"；保留原证据，考试要求已标待核读"+detail) from error

FIELDS={
 "courses":["id","name","current_topic"],
 "tasks":["id","course_id","title","status","submission_status","deadline_id","material_id"],
 "deadlines":["id","course_id","title","date","time","timezone","status"],
 "materials":["id","course_id","title","relative_path","pages"],
 "mistakes":["id","course_id","entry_type","original_question","confusion_point","resolution_status"],
 "discussion_notes":["id","course_id","title","status","conclusion"],
 "schedules":["id","course_id","title","date","weekday","start","end","start_time","end_time","status"],
 "course_updates":["id","course_id","title","status","summary"],
 "pending_inputs":["id","course_id","title","status","description"]}
ACTIVE={"tasks","deadlines"}
def listing_rows(s,collection,course=None,query=None):
    if collection not in FIELDS:raise ValueError("列表入口支持 courses/tasks/deadlines/materials/mistakes/discussion_notes/schedules/course_updates/pending_inputs")
    rows=[v for v in s.get(collection,[]) if not course or (v.get("id")==course if collection=="courses" else v.get("course_id") in (course,None))]
    if collection in ACTIVE:rows=[v for v in rows if str(v.get("status","")).lower() not in DONE]
    if query:rows=[v for v in rows if query.casefold() in json.dumps(v,ensure_ascii=False).casefold()]
    rows=sorted(rows,key=lambda v:((str(v.get("date") or "9999") if collection=="deadlines" else ""),str(v.get("id",""))))
    projected=[]
    for v in rows:
        row=pick(v,FIELDS[collection]);truncated=[]
        for key,value in list(row.items()):
            if isinstance(value,str) and len(value)>800:
                row[key]=value[:800];truncated.append(key)
        if truncated:row["truncated_fields"]=truncated
        projected.append(row)
    return projected

def listing(collection,course=None,query=None,offset=0,limit=12,revision=None):
    s=read(STATE)
    if revision is not None and s["revision"]!=revision:raise ValueError("状态版本变化；从 offset 0 重新读取")
    rows=listing_rows(s,collection,course,query)
    return {"revision":s["revision"],"collection":collection,"total":len(rows),"items":rows[offset:offset+limit],
            "offset":offset,"has_more":offset+limit<len(rows),"next_offset":offset+limit if offset+limit<len(rows) else None}

def fit(payload,maximum):
    out=dict(payload);out["omitted"]={};out["more"]={}
    # Required teaching fields are exact when inlined; oversized fields have discoverable pointers.
    if len(json.dumps(out,ensure_ascii=False))>maximum:
        for key in list(out.get("course_details",{})):
            value=out["course_details"][key]
            if len(json.dumps(value,ensure_ascii=False))>maximum//4:
                out["course_details"]=dict(out["course_details"])
                out["course_details"].pop(key)
                out["detail_fields"][key]["inline"]=False
    for key in ["materials","courses","tasks","mistakes","discussion_notes","deadlines"]:
        values=list(out.get(key,[]))
        while values and len(json.dumps(out,ensure_ascii=False))>maximum-400:
            values.pop();out[key]=values
            out["omitted"][key]=out["omitted"].get(key,0)+1
            out["more"][key]={"offset":len(values),"total":len(payload.get(key,[]))}
    if len(json.dumps(out,ensure_ascii=False))>maximum-200:
        out.pop("course_details",None)
        for value in out.get("detail_fields",{}).values():value["inline"]=False
        if "teaching_cursor" in out:
            out["detail_fields"]["teaching_cursor"]={"inline":False}
            out.pop("teaching_cursor")
    out["next"]="more 用 list --collection 名称 --course 课程 --offset N --revision 当前版本；详情 item；截断字段须补读"
    return out

def context(course=None,maximum=12000):
    s=read(STATE)
    courses=[c for c in s.get("courses",[]) if not course or c["id"]==course]
    if course and not courses:raise ValueError("课程不存在")
    h=health()
    out={"revision":s["revision"],"course_id":course,"scope":"local_context_only",
         "checked_at":h["checked_at"],"collection_complete":h["collection_complete"],
         "needs_moodle_refresh":"本地上下文不代表实时检查；每条学习消息先 turn",
         "courses":listing_rows(s,"courses",course)}
    if course:
        c=courses[0];out["teaching_cursor"]=c.get("teaching_cursor")
        out["course_details"]=pick(c,["assignment_focus","orientation","assistant_notes","conventions"])
        out["detail_fields"]={k:{"inline":True} for k in out["course_details"]}
    for name in ["tasks","deadlines","materials","mistakes","discussion_notes"]:
        out[name]=listing_rows(s,name,course) if course or name not in ("mistakes","discussion_notes") else []
    return fit(out,maximum)

def page(value,offset,limit):
    encoded=json.dumps(value,ensure_ascii=False,indent=2)
    return {"total_chars":len(encoded),"offset":offset,"content":encoded[offset:offset+limit],
            "has_more":offset+limit<len(encoded),"next_offset":offset+limit if offset+limit<len(encoded) else None,
            "partial_is_not_full_review":offset>0 or offset+limit<len(encoded)}

def item(collection,identity,field,offset,limit):
    values=read(STATE).get(collection)
    if isinstance(values,dict) and collection=="settings":
        v=values if not identity else values.get(identity)
    elif isinstance(values,list):
        v=next((v for v in values if str(v.get("id"))==identity),None)
    else:raise ValueError("只支持状态列表或 settings")
    if v is None:raise ValueError("记录不存在")
    if field:
        if field not in v:raise ValueError("字段不存在")
        v=v[field]
    return page(v,offset,limit)

def html_images(text):
    # Match the collector's forum-image parser, including unquoted src attributes.
    pattern=r'<img\b[^>]*?\ssrc\s*=\s*(?:"([^"]*)"|\x27([^\x27]*)\x27|([^\s>]+))'
    return [unescape(next(v for v in match if v)) for match in re.findall(pattern,str(text or ""),re.I)
            if any(match)]


def media_requirements(record):
    b=record.get("body",{});images=[];attachments=[]
    for field in ("message","html","description","summary","intro","activity","submissionstatement"):
        for index,src in enumerate(html_images(b.get(field))):
            image={"field":field,"expected_src":src,"read_with":"browser"}
            if field=="message" and b.get("discussion_id") and b.get("id"):
                image.update(read_with="forum_image",discussionid=b["discussion_id"],postid=b["id"],index=index)
            images.append(image)
    for field in ("attachments","messageinlinefiles","introfiles","introattachments","activityattachments","summaryfiles"):
        values=b.get(field) or []
        for value in values if isinstance(values,list) else [values]:
            attachments.append({"field":field,"file":value,"read_with":"browser"})
    # Some module responses expose resource files directly rather than attachments.
    for value in b.get("contents") or []:
        if isinstance(value,dict) and value.get("type")=="file":
            attachments.append({"field":"contents","file":value,"read_with":"browser"})
    if record.get("kind")=="module" and (b.get("modname") in {"resource","folder","page","book","url"}
            or (isinstance(b.get("contentsinfo"),dict) and b["contentsinfo"].get("filescount",0))):
        attachments.append({"field":"linked_content","file":{"url":b.get("url"),"modname":b.get("modname"),
                            "contentsinfo":b.get("contentsinfo")},"read_with":"browser"})
    # Conflicting calendar reads retain their earlier body; its media also needs review.
    if record.get("kind")=="event" and isinstance(b.get("action_event"),dict):
        earlier={k:v for k,v in b["action_event"].items() if k!="action_event"}
        retained=media_requirements({"kind":"event","body":earlier})
        images.extend({**value,"field":"action_event."+value["field"]} for value in retained["images"])
        attachments.extend({**value,"field":"action_event."+value["field"]} for value in retained["attachments"])
    return {"images":images,"attachments":attachments}


def source(identity,offset=0,limit=6000,event=None):
    db=journal()
    try:e=db.event(event) if event else db.latest(identity)
    finally:db.close()
    if identity and e["source_id"]!=identity:raise ValueError("来源与通知版本不匹配")
    r=e["record"];snap=read(SNAPSHOT,{})
    return dict(page(r,offset,limit),source_id=r["id"],source_hash=r["hash"],event_id=e["event_id"],
                availability=e["availability"],media=media_requirements(r),
                from_last_complete=r["id"] not in records(snap),from_archive=True,
                checked_at=e["checked_at"],collection_complete=health()["collection_complete"])

def bundle(requests):
    if not isinstance(requests,list) or not 1<=len(requests)<=50:raise ValueError("每批请求 1–50 项")
    result=[]
    for request in requests:
        if not isinstance(request,dict):raise ValueError("请求必须为对象")
        if not isinstance(request.get("offset",0),int) or request.get("offset",0)<0 or not isinstance(request.get("limit",6000),int) or not 1<=request.get("limit",6000)<=50000:
            raise ValueError("分页参数无效")
        if request.get("source_id") or request.get("event_id"):
            value=source(request.get("source_id"),request.get("offset",0),request.get("limit",6000),request.get("event_id"))
        else:
            value=item(request["collection"],request.get("id"),request.get("field"),request.get("offset",0),request.get("limit",6000))
        if not value["partial_is_not_full_review"]:
            value["data"]=json.loads(value.pop("content"))
            for key in ("total_chars","offset","has_more","next_offset","partial_is_not_full_review"):value.pop(key,None)
        result.append(value)
    return {"items":result}

def accept_many(requests):
    """Validate an entire reviewed page before one atomic state commit."""
    import review
    if not isinstance(requests,list) or not 1<=len(requests)<=50:raise ValueError("每批确认 1–50 项")
    db=journal()
    try:
        if not health()["collection_complete"]:raise ValueError("本轮采集不完整，保持待审；不能确认完整审阅")
        original=STATE.read_bytes();s=json.loads(original.decode("utf-8-sig"))
        root=s.setdefault("integrations",{}).setdefault("lite_moodle",{})
        accepted=[];seen=set()
        for request in requests:
            identity=request.get("id");expected=request.get("hash");evidence=request.get("evidence","")
            event=request.get("event");media_evidence=request.get("media_evidence")
            if not isinstance(evidence,str) or not evidence.strip():raise ValueError("必须提供实际语义核读说明")
            if event:e=db.event(event)
            else:
                candidates=[e for e in db.pending(receipts(s)) if e["source_id"]==identity]
                if len(candidates)>1:raise ValueError("此来源有多个待审版本，请指定 --event")
                e=db.latest(identity)
            if (identity and identity!=e["source_id"]) or expected!=e["hash"]:raise ValueError("来源哈希或版本不匹配，请重新核读")
            if e["event_id"] in seen:raise ValueError("同一通知版本不能在一批中重复确认")
            seen.add(e["event_id"])
            media=media_requirements(e["record"])
            if any(media.values()) and (not isinstance(media_evidence,str) or not media_evidence.strip()):
                raise ValueError("含图片或附件；须实际核读并提供 --media-evidence，无法查看则保持待审")
            root.setdefault("reviewed_events",{})[e["event_id"]]={
                "source_id":e["source_id"],"hash":expected,"availability":e["availability"],"reviewed_at":now(),
                "evidence":evidence,"media_evidence":media_evidence}
            if e["event_id"]==db.latest(e["source_id"])["event_id"] and e["availability"]=="visible":
                root.setdefault("reviewed_sources",{})[e["source_id"]]={"hash":expected,"reviewed_at":now(),"evidence":evidence}
            accepted.append(e["event_id"])
        review.save(STATE,s,original)
    finally:db.close()
    return {"count":len(accepted),"mastery_updated":False}

def accept(identity,expected,evidence,event=None,media_evidence=None):
    result=accept_many([{"id":identity,"hash":expected,"evidence":evidence,"event":event,"media_evidence":media_evidence}])
    return {"accepted":event or identity,"mastery_updated":False}

def inbox(offset=0,limit=12):
    folder=ROOT/"Study/_Inbox";rows=[]
    s=read(STATE);indexed={m.get("relative_path"):m for m in s.get("materials",[])}
    if folder.is_dir():
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):continue
            relative=path.relative_to(ROOT/"Study").as_posix()
            stat=path.stat()
            with path.open("rb") as handle:sha=hashlib.file_digest(handle,"sha256").hexdigest()
            material=indexed.get(relative)
            known=(material.get("sha256") or material.get("content_sha256") or
                   (material.get("source") or {}).get("sha256")) if material else None
            if known==sha:continue
            status="new" if not material else ("changed" if known else "indexed_needs_content_check")
            after=path.stat()
            if (after.st_size,after.st_mtime_ns)!=(stat.st_size,stat.st_mtime_ns):status="changed_during_check"
            rows.append({"path":relative,"bytes":after.st_size,"sha256":sha,"status":status})
    return {"unindexed_count":sum(r["status"]=="new" for r in rows),"needs_review_count":len(rows),
            "items":rows[offset:offset+limit],"has_more":offset+limit<len(rows),
            "next_offset":offset+limit if offset+limit<len(rows) else None}

def turn(course=None,maximum=12000):
    try:notification=refresh(True)
    except (ValueError,OSError) as e:
        notification={"mode":"failed","live_checked":False,"error":str(e),**health(),"pending":pending()}
    return {"notifications":notification,"context":context(course,maximum),"inbox":inbox(0,5)}

def plan():
    import daily,review
    result=daily.execute(STATE,"run",review.timestamp())
    check=daily.execute(STATE,"check",review.timestamp())
    return {"date":result["date"],"fresh":check["fresh"],"issues":check["issues"],
            "views_updated_count":len(result["views_updated"]),"review_budget_minutes":(result.get("review") or {}).get("budget_minutes"),
            "path":"Study/_System/Today Plan.md"}

def doctor():
    s=read(STATE);local=(ROOT/"Study").resolve()
    configured=Path(s.get("study_root","Study"))
    configured=configured.resolve() if configured.is_absolute() else (ROOT/configured).resolve()
    missing=[]
    for m in s.get("materials",[]):
        if not m.get("relative_path"):continue
        p=(local/m["relative_path"]).resolve()
        if not p.is_relative_to(local) or not p.is_file():missing.append(m["id"])
    return {"independent_state":configured==local,"missing_material_ids":missing,
            "course_count":len(s.get("courses",[])),"credentials_present":(ROOT/".private/moodle-token.dpapi").is_file(),
            "setup_needed":not (ROOT/"config.local.json").is_file()}

def metrics():
    s=read(STATE);baseline=len(STATE.read_text(encoding="utf-8-sig"))
    samples={"overview":context(),**{c["id"]:context(c["id"]) for c in s["courses"]}}
    return {"metric":"characters_not_billed_tokens","state_chars":baseline,
            "samples":{k:{"chars":len(json.dumps(v,ensure_ascii=False))} for k,v in samples.items()},
            "note":"实际 Token 对照使用 tools/release/benchmark_tokens.py；字符不是额度"}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=["turn","context","list","item","bundle","inbox","refresh","scan","changes","pending","review","source","accept","accept-batch","plan","doctor","metrics"])
    for name in ["course","id","collection","field","hash","evidence","event","media-evidence","query","queue-version"]:p.add_argument("--"+name)
    p.add_argument("--force",action="store_true");p.add_argument("--cached",action="store_true",help="明确允许缓存；学习消息不用此选项")
    p.add_argument("--revision",type=int)
    p.add_argument("--offset",type=int,default=0);p.add_argument("--limit",type=int)
    p.add_argument("--max-chars",type=int,default=12000)
    a=p.parse_args()
    if a.offset<0 or not 2500<=a.max_chars<=50000 or (a.limit is not None and not 1<=a.limit<=50000):raise ValueError("分页或预算参数无效")
    if not STATE.exists():raise ValueError("尚未建立学习档案；请先运行 setup.cmd")
    lock=None
    if a.command in {"turn","refresh","scan","accept","accept-batch","plan","pending","changes","review","source","bundle"}:
        try:lock=os.open(LOCK,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:raise ValueError("另一个轻量操作正在运行；确认旧进程退出后才清理 lightweight.lock")
    try:
        if a.command=="turn":result=turn(a.course,a.max_chars)
        elif a.command=="context":result=context(a.course,a.max_chars)
        elif a.command=="list":result=listing(a.collection,a.course,a.query,a.offset,a.limit or 12,a.revision)
        elif a.command=="item":result=item(a.collection,a.id,a.field,a.offset,a.limit or 6000)
        elif a.command=="bundle":result=bundle(json.load(sys.stdin))
        elif a.command=="inbox":result=inbox(a.offset,a.limit or 12)
        elif a.command=="refresh":result=refresh(a.force or not a.cached)
        elif a.command=="scan":
            r=scan();result={"collection_complete":r["collection_complete"],"pending_review_count":len(r["pending_review"])}
        elif a.command in {"changes","pending"}:result=pending(a.course,a.offset,a.limit or 12,a.queue_version)
        elif a.command=="review":result=review_page(a.course,a.offset,a.limit or 12,a.max_chars,a.queue_version)
        elif a.command=="source":result=source(a.id,a.offset,a.limit or 6000,a.event)
        elif a.command=="accept":result=accept(a.id,a.hash,a.evidence or "",a.event,a.media_evidence)
        elif a.command=="accept-batch":result=accept_many(json.load(sys.stdin))
        elif a.command=="plan":result=plan()
        elif a.command=="doctor":result=doctor()
        else:result=metrics()
        print(json.dumps(result,ensure_ascii=False,separators=(",",":")))
    finally:
        if lock is not None:os.close(lock);LOCK.unlink(missing_ok=True)

if __name__=="__main__":
    for stream in (sys.stdin,sys.stdout,sys.stderr):stream.reconfigure(encoding="utf-8")
    try:main()
    except (ValueError,OSError,KeyError,TypeError,sqlite3.Error,subprocess.TimeoutExpired) as e:
        print(json.dumps({"error":str(e)},ensure_ascii=False),file=sys.stderr);raise SystemExit(1)
