import { checkWarnings } from './refresh.mjs';

// Auxiliary activity records only: no percentage and no inference about mastery.
export async function collectProgress(client, state) {
  const report = {checked_at: new Date().toISOString(), courses: [], errors: [], collection_complete: false};
  for (const course of state.courses ?? []) {
    for (const id of course.moodle_course_ids ?? []) {
      try {
        const sections = checkWarnings(await client.call('core_course_get_contents', {courseid: id, 'options[0][name]':'excludecontents','options[0][value]':1}));
        const completion = checkWarnings(await client.call('core_completion_get_activities_completion_status', {courseid: id, userid: client.userId}));
        if (!Array.isArray(sections) || !Array.isArray(completion.statuses)) throw new Error('Invalid progress response');
        const statuses = new Map(completion.statuses.map(s => [s.cmid,s]));
        report.courses.push({course_id:course.id,courseid:id,sections:sections.map(section => ({
          id:section.id,name:section.name,section:section.section,
          activities:(section.modules ?? []).map(m => {
            const c=statuses.get(m.id);
            return {id:m.id,name:m.name,modname:m.modname,state:c?.state ?? null,
                    tracking:c?.tracking ?? null,timecompleted:c?.timecompleted ?? null};
          })
        }))});
      } catch { report.errors.push({course_id:course.id,courseid:id,message:'本轮活动记录未完整读取，保留上次成功记录'}); }
    }
  }
  report.collection_complete=report.errors.length===0;
  return report;
}

export function applyProgress(state, report) {
  const updated=structuredClone(state);
  for (const course of updated.courses ?? []) {
    const rows=report.courses.filter(r=>r.course_id===course.id);
    const failed=report.errors.filter(r=>r.course_id===course.id);
    const prior=new Map((course.moodle_progress?.pages ?? []).map(p=>[p.courseid,p]));
    for (const row of rows) prior.set(row.courseid,{...row,checked_at:report.checked_at});
    if (rows.length || failed.length) course.moodle_progress={checked_at:report.checked_at,pages:[...prior.values()],errors:failed};
  }
  return updated;
}
