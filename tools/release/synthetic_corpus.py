"""Generated fictional data only; no real learner records."""
topics=["Consumer choice and budget constraint","Demand, supply and equilibrium","Elasticity and tax incidence",
        "Journal entries and adjusting entries","Accrual accounting and financial statements","Limits and continuity",
        "Differentiation and applications","Integration and area","Probability and conditional events","Sampling distributions",
        "Optimization with constraints","Externalities and public goods"]

def corpus(nc,nm,ne):
    s={"revision":3,"timezone":"Asia/Hong_Kong","settings":{"lightweight":{"moodle_cache_minutes":30}},
       "courses":[],"materials":[],"tasks":[],"deadlines":[],"mistakes":[],"discussion_notes":[],
       "review_attempts":[],"learning_feedback":[],"integrations":{}}
    for c in range(1,nc+1):
        cid=f"DEMO{c:03d}"
        s["courses"].append({"id":cid,"name":f"Demonstration course {c}","moodle_course_ids":[c],
            "current_topic":topics[(c+2)%len(topics)],
            "orientation":{"teacher":"Example lecturer","method":"依据原课件定义与符号，保留限制条件，先解释概念再独立练习。",
                           "assessment":"作业与期末要求分别核对老师公告；未知内容保持待确认。"},
            "assistant_notes":["没有独立作答证据的内容不标为掌握。","讨论区的问题属于其他同学，不能记成本人的错误。"],
            "assignment_focus":{"task_id":f"{cid}-T1","chapters":[2,3],"evidence":"Synthetic assignment requires exercises from Chapters 2 and 3."},
            "teaching_cursor":{"topic":topics[c%len(topics)],"stage":"awaiting_independent_attempt"},
            "conventions":{"notation":"Follow the lecturer's notation","timezone":"Asia/Hong_Kong"}})
        for m in range(nm):
            s["materials"].append({"id":f"{cid}-MAT{m}","course_id":cid,
                "title":f"Lecture {m+1}: {topics[(m+c)%len(topics)]}","relative_path":f"{cid}/Lectures/Lecture {m+1}.pdf",
                "pages":18+m%13,"source":{"type":"moodle","module_id":c*1000+m,"url":f"https://moodle.example.edu/mod/resource/view.php?id={c*1000+m}"},
                "outline":[{"pages":[1,4],"topic":"Definitions and assumptions"},{"pages":[5,12],"topic":topics[(m+c)%len(topics)]},
                           {"pages":[13,18],"topic":"Worked examples and independent exercises"}]})
        for t in range(4):
            s["tasks"].append({"id":f"{cid}-T{t}","course_id":cid,"title":f"Problem set {t+1}",
                "status":"pending","submission_status":"not_confirmed","deadline_id":f"{cid}-D{t}","material_id":f"{cid}-MAT{t}",
                "requirements":{"questions":[t+1,t+2,t+3],"chapters":[2,3],"working":"Show intermediate steps and justify assumptions."}})
            s["deadlines"].append({"id":f"{cid}-D{t}","course_id":cid,"title":f"Problem set {t+1} deadline",
                "date":f"2026-10-{15+t:02d}","time":"23:59","timezone":"Asia/Hong_Kong","status":"pending"})
        for e in range(ne):
            s["mistakes"].append({"id":f"{cid}-E{e}","course_id":cid,"entry_type":"question",
                "original_question":f"{topics[(e+c)%len(topics)]}: 为什么条件改变后不能直接套用同一个公式？",
                "confusion_point":"需要区分定义、公式适用条件和图形上的变化方向。","resolution_status":"awaiting_independent_check",
                "explanation":"先写出题设与约束，再比较变化前后保持不变的量；用一个具体数值例子检验推导。",
                "source":{"material_id":f"{cid}-MAT{e%nm}","pages":[3+e%10]},
                "evidence":{"type":"synthetic_user_question","at":f"2026-10-{1+e%10:02d}T17:00:00+08:00","independent_answer":None}})
            s["review_attempts"].append({"id":f"{cid}-A{e}","course_id":cid,"mistake_id":f"{cid}-E{e}",
                "answer":f"Example attempt {e}: hold income constant, change the relative price, and recalculate the feasible set.",
                "feedback":"检查了条件陈述；数值计算正确，但解释仍缺少对边界情况的说明。",
                "independent":True,"rating":"hard","minutes":4+e%3})
        for n in range(max(2,ne//2)):
            s["discussion_notes"].append({"id":f"{cid}-N{n}","course_id":cid,"title":f"Teacher clarification {n+1}: {topics[n%len(topics)]}",
                "status":"teacher_confirmed","conclusion":"按课堂定义解释，并明确区分课堂练习与考试范围；没有公布的题型保持待确认。",
                "source":{"id":f"post:{c*100+n}","author_role":"teacher","excerpt":"State your assumptions and show all intermediate steps."}})
    return s
