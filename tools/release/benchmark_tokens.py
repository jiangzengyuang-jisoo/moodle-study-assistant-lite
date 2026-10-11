"""Reproducible local text-token benchmark. Never reads a real Study directory."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import json
import os
import subprocess
import sys
import tempfile
import uuid
import random

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools/study"),str(ROOT/".local/audit-deps")]
os.environ.setdefault("TIKTOKEN_CACHE_DIR",str(ROOT/".local/tokenizer-cache"))
import light, daily, review
from synthetic_corpus import corpus
from test_learning_loop import fixture, AT
try:
    import tiktoken
except ImportError:
    raise SystemExit("Optional benchmark dependency: install tiktoken==0.12.0; production does not need it.")

OUT=ROOT/".local/token-benchmark-v2"
OUT.mkdir(parents=True,exist_ok=True)
ENC={name:tiktoken.get_encoding(name) for name in ("o200k_base","cl100k_base")}
def compact(v):return json.dumps(v,ensure_ascii=False,separators=(",",":"))
def count(text):return {name:len(enc.encode(text)) for name,enc in ENC.items()}
def text_total(outputs):return "\n".join(compact(x) if not isinstance(x,str) else x for x in outputs)
def save(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

@contextmanager
def isolated(state,snapshot=None):
    with tempfile.TemporaryDirectory(prefix="synthetic-",dir=OUT) as temp, ExitStack() as stack:
        root=Path(temp);system=root/"Study/_System";system.mkdir(parents=True)
        for key,path in {"ROOT":root,"SYSTEM":system,"STATE":system/"state.json","SNAPSHOT":system/"refresh-latest.json",
            "INDEX":system/"lightweight-index.json","REPORT":system/"lightweight-delta.json","LOCK":system/"lightweight.lock"}.items():
            stack.enter_context(patch.object(light,key,path))
        rng=random.Random(733)
        stack.enter_context(patch.object(uuid,"uuid4",side_effect=lambda:uuid.UUID(int=rng.getrandbits(128))))
        light.atom(light.STATE,deepcopy(state))
        if snapshot:light.atom(light.SNAPSHOT,deepcopy(snapshot))
        yield

result={"measurement":"actual tokenizer counts of local plain-text tool outputs; synthetic data only",
 "excludes":["model-generated responses","reasoning","tool-call arguments and schemas","system prompt","history replay/cache","images and attachments","Plus quota"],
 "tokenizer_version":tiktoken.__version__,"course_context":{},"notifications":{}}
for name,shape in (("small",(3,8,4)),("medium",(5,24,12)),("large",(8,48,24))):
    state=corpus(*shape);cid="DEMO001"
    with isolated(state,{"finished_at":"2026-10-12T00:00:00+00:00","collection_complete":True}):
        ctx=light.context(cid);outputs=[ctx];calls=1;recovered={}
        for collection,route in ctx["more"].items():
            rows=ctx.get(collection,[])[:];offset=route["offset"]
            while True:
                page=light.listing(collection,cid,offset=offset,limit=24,revision=ctx["revision"])
                outputs.append(page);calls+=1;rows+=page["items"]
                if not page["has_more"]:break
                offset=page["next_offset"]
            recovered[collection]=rows
        for collection in ("tasks","deadlines","materials","mistakes","discussion_notes"):
            assert recovered.get(collection,ctx[collection])==light.listing_rows(state,collection,cid)
        assert ctx["course_details"]==light.pick(state["courses"][0],["orientation","assistant_notes","assignment_focus","conventions"])
        details=light.bundle([{"collection":"mistakes","id":cid+"-E0"},{"collection":"discussion_notes","id":cid+"-N0"}])
        outputs.append(details);calls+=1
        assert details["items"][0]["data"]==state["mistakes"][0]
        assert details["items"][1]["data"]==state["discussion_notes"][0]
        fixed=count(text_total(outputs));whole=count(json.dumps(state,ensure_ascii=False,indent=2)+"\n");minified=count(compact(state))
        result["course_context"][name]={"shape":shape,"original_whole_state_pretty":whole,"original_whole_state_compact":minified,
            "fixed_context_all_pages_and_evidence":fixed,"tool_calls":calls,"all_course_index_rows_recovered":True,
            "saved_vs_pretty_percent":{e:round(100*(1-fixed[e]/whole[e]),2) for e in ENC},
            "saved_vs_compact_percent":{e:round(100*(1-fixed[e]/minified[e]),2) for e in ENC}}
        save(name+"-outputs.json",outputs)

class FixedDatetime(datetime):
    @classmethod
    def now(cls,tz=None):return AT.astimezone(tz) if tz else AT.replace(tzinfo=None)

plan_state=fixture(6);plan_state.update(revision=0,timezone="Asia/Hong_Kong",materials=[],deadlines=[],schedules=[])
def pages():return "\n".join((light.SYSTEM/name).read_text(encoding="utf-8") for name in ("Today Plan.md","Today Review.md"))
with patch.object(review,"datetime",FixedDatetime),isolated(plan_state):
    oldrun=daily.execute(light.STATE,"run",AT);oldcheck=daily.execute(light.STATE,"check",AT)
    oldpages=pages();oldtext=json.dumps(oldrun,ensure_ascii=False)+"\n"+json.dumps(oldcheck,ensure_ascii=False)+"\n"+oldpages
with patch.object(review,"datetime",FixedDatetime),isolated(plan_state):
    original_timestamp=review.timestamp
    with patch.object(review,"timestamp",side_effect=lambda value=None:AT if value is None else original_timestamp(value)):
        fixed=light.plan()
    assert pages()==oldpages
    newtext=compact(fixed)+"\n"+pages()
result["plan"]={"original_complete_local_outputs":count(oldtext),"fixed_complete_local_outputs":count(newtext),
                "plan_and_questions_identical":True}

def school_snapshot():
    snap={"finished_at":"2026-10-12T00:00:00+00:00","collection_complete":True,"pages":[],"threads":[],
          "assignments":{"courses":[]},"calendar":{"events":[]},"errors":[],"scope_limits":[]}
    for c in range(1,6):
        cid=f"DEMO{c:03d}"
        snap["pages"].append({"course_id":cid,"courseid":c,"sections":[{"id":c,"name":"Current work","summary":"Review definitions and restrictions.","modules":[]}]})
        snap["assignments"]["courses"].append({"id":c,"assignments":[{"id":100+c,"name":"Problem set","duedate":1791817200,"intro":"Show all working. Submit before 23:59."}]})
        snap["threads"].append({"course_id":cid,"discussion":{"discussion":c,"name":"Teacher clarifications"},
            "posts":[{"id":c*1000+p,"subject":f"Clarification {p+1}","message":f"Example {p+1}: use the definitions stated in lecture. Explain the assumptions before calculating. Chapter {p%5+1} has optional questions; optional does not mean examinable.",
                      "author":{"id":c,"fullname":"Example Teacher"},"timemodified":100+p} for p in range(8)]})
    return snap

def acknowledge_page(rows):
    return [light.accept_many([{"id":row["id"],"hash":row["hash"],"event":row["event_id"],
        "evidence":"Synthetic benchmark: read source, confirmed teacher role and requirements",
        "media_evidence":"Synthetic visual evidence" if row["kind"]=="post" else None} for row in rows])]

for mode in ("unchanged","one_teacher_edit","first_sync"):
    state=corpus(5,24,12);snap=school_snapshot()
    with isolated(state,snap):
        if mode!="first_sync":
            while True:
                rows=light.pending(None,0,12)["items"]
                if not rows:break
                acknowledge_page(rows)
        fresh=deepcopy(snap);fresh["finished_at"]="2026-10-12T00:01:00+00:00"
        if mode=="one_teacher_edit":fresh["threads"][0]["posts"][0]["message"]="Important: deadline moved to tonight. Chapter 5 is excluded. Submit before 23:59."
        def fake_run(*args,**kwargs):
            light.atom(light.SYSTEM/"collections/new.json",fresh)
            light.atom(light.SNAPSHOT,fresh);light.atom(light.SYSTEM/"refresh-last-complete.json",fresh)
            return subprocess.CompletedProcess(args[0],0,"","")
        with patch.object(light.shutil,"which",return_value=sys.executable),patch.object(light.subprocess,"run",side_effect=fake_run) as runner:
            start=light.refresh(True)
        assert runner.call_count==1
        outputs=[start];rows=start["pending"]["items"];read_events=[]
        while rows:
            assert all("body" in row and not row.get("requires_source_paging") for row in rows), "All source pages must be included in this fixture"
            read_events.extend(row["event_id"] for row in rows)
            outputs.extend(acknowledge_page(rows))
            nextpage=light.review_page(None,0,12);outputs.append(nextpage);rows=nextpage["items"]
        assert not light.pending()["pending_review_count"]
        if mode=="one_teacher_edit":
            assert "deadline moved to tonight" in text_total(outputs) and "Chapter 5 is excluded" in text_total(outputs)
        result["notifications"][mode]={
            "original_full_snapshot_pretty":count(json.dumps(fresh,ensure_ascii=False,indent=2)),
            "original_full_snapshot_compact":count(compact(fresh)),
            "fixed_refresh_all_pending_source_and_ack_outputs":count(text_total(outputs)),
            "events_actually_read":len(read_events),"all_pending_consumed":True,"real_school_requests":0,
            "baseline_note":"Whole-snapshot reading baseline; an original implementation doing its own precise diff can be smaller."}
        save("notifications-"+mode+"-outputs.json",outputs)
result["ten_notification_cycles_including_first"]={}
for enc in ENC:
    original=result["notifications"]["first_sync"]["original_full_snapshot_compact"][enc]*10
    fixed=result["notifications"]["first_sync"]["fixed_refresh_all_pending_source_and_ack_outputs"][enc]+9*result["notifications"]["unchanged"]["fixed_refresh_all_pending_source_and_ack_outputs"][enc]
    result["ten_notification_cycles_including_first"][enc]={"original_compact_snapshot_text":original,"fixed_review_text":fixed,"saved_percent":round(100*(1-fixed/original),2)}
result["rules"]={"current_agents":count((ROOT/"AGENTS.md").read_text(encoding="utf-8-sig")),
                 "note":"Instruction loading is separate; no automatic claim about full-session savings."}
save("results.json",result)
sys.stdout.reconfigure(encoding="utf-8")
print(json.dumps(result,ensure_ascii=False,indent=2))
