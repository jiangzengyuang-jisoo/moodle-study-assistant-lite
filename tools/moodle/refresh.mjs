// Evidence collection only. An assistant reviews changes before promoting a baseline.
export function redactEvidence(value, token) {
  if (typeof value === 'string') return (token ? value.replaceAll(token, '[REDACTED]') : value)
    .replace(/([?&](?:amp;)?(?:token|wstoken|sesskey)=)[^&"'\s<>]+/gi, '$1[REDACTED]')
    .replace(/((?:Password|Passcode)\s*:?\s*(?:<[^>]*>\s*)*)[\w-]+/gi, '$1[meeting access code omitted]');
  if (Array.isArray(value)) return value.map(v => redactEvidence(v, token));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, redactEvidence(v, token)]));
  return value;
}

function partialError(error, partial) {
  error.partial = partial;
  return error;
}

export function checkWarnings(data) {
  if (data?.warnings !== undefined && !Array.isArray(data.warnings))
    throw partialError(new Error('Invalid API warning list'), data);
  if (data?.warnings?.length) throw partialError(new Error('API warnings: ' + JSON.stringify(data.warnings)), data);
  return data;
}

const validId = value => Number.isInteger(value) && value > 0;
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);

// Reject malformed success bodies while retaining valid siblings for review.
export function validateList(data, key, valid = object) {
  if (!object(data) || !Array.isArray(data[key]))
    throw partialError(new Error(`Missing or invalid ${key} list`), null);
  const items = data[key].filter(valid);
  if (items.length !== data[key].length)
    throw partialError(new Error(`Invalid ${key} entry`), {...data, [key]: items});
  if (data.warnings !== undefined && !Array.isArray(data.warnings))
    throw partialError(new Error('Invalid API warning list'), {...data, warnings: []});
  return data;
}

export function validateAssignments(data) {
  if (!object(data) || !Array.isArray(data.courses))
    throw new Error('Missing or invalid courses list');
  const clean = [], errors = [];
  if (data.warnings !== undefined && !Array.isArray(data.warnings)) errors.push('Invalid API warning list');
  for (const course of data.courses) {
    if (!object(course) || !validId(course.id) || !Array.isArray(course.assignments)) {
      errors.push('Invalid assignment course'); continue;
    }
    const assignments = course.assignments.filter(a => object(a) && validId(a.id));
    if (assignments.length !== course.assignments.length) errors.push('Invalid assignment entry');
    clean.push({...course, assignments});
  }
  if (errors.length) throw partialError(new Error(errors.join('; ')), {...data, courses: clean, warnings: Array.isArray(data.warnings) ? data.warnings : []});
  return data;
}

function validateSections(data) {
  if (!Array.isArray(data)) throw new Error('Missing course section list');
  const clean = [], errors = [];
  for (const section of data) {
    if (!object(section) || !validId(section.id) || !Array.isArray(section.modules)) {
      errors.push('Invalid course section'); continue;
    }
    const modules = section.modules.filter(m => object(m) && validId(m.id) && typeof m.modname === 'string');
    if (modules.length !== section.modules.length) errors.push('Invalid course module');
    clean.push({...section, modules});
  }
  if (errors.length) throw partialError(new Error(errors.join('; ')), clean);
  return data;
}

// Unlike action events, this includes ordinary course/group/site/user calendar notices.
// Moodle returns the full explicit time window: this API has no page/limit parameter.
export async function readOrdinaryCalendar(client, courseids, groupids, timestart, timeend) {
  const args = {'options[timestart]': timestart, 'options[timeend]': timeend,
    'options[userevents]': 1, 'options[siteevents]': 1, 'options[ignorehidden]': 1};
  courseids.forEach((id, i) => { args[`events[courseids][${i}]`] = id; });
  groupids.forEach((id, i) => { args[`events[groupids][${i}]`] = id; });
  const data = validateList(await client.call('core_calendar_get_calendar_events', args),
    'events', e => object(e) && validId(e.id));
  return checkWarnings(data);
}

export async function readDiscussions(client, forumid, perpage = 100) {
  const result = [], seen = new Set();
  try {
    for (let page = 0; page < 1000; page++) {
      const data = await client.call('mod_forum_get_forum_discussions', { forumid, page, perpage });
      if (!Array.isArray(data.discussions)) throw new Error('Missing discussion list');
      for (const d of data.discussions) {
        if (!d.discussion || seen.has(d.discussion)) throw new Error('Repeated or missing discussion ID');
        seen.add(d.discussion); result.push(d);
      }
      checkWarnings(data);
      if (data.discussions.length < perpage) return result;
    }
    throw new Error('Pagination limit reached');
  } catch (error) { throw partialError(error, result); }
}

export function verifyPosts(discussion, data) {
  try {
    checkWarnings(data);
    if (!Array.isArray(data.posts)) throw new Error('Missing post list');
    if (new Set(data.posts.map(p => p.id)).size !== data.posts.length) throw new Error('Duplicate post ID');
    if (data.posts.length !== Number(discussion.numreplies) + 1) throw new Error('Post count differs from discussion listing');
    return data.posts;
  } catch (error) { throw partialError(error, Array.isArray(data?.posts) ? data.posts : null); }
}

// Moodle supports at most 50 action events per page; the cursor is the last seen ID.
export async function readCalendar(client, timesortfrom, timesortto) {
  const result = {events: []}, seen = new Set();
  let aftereventid = 0;
  try {
    for (let page = 0; page < 1000; page++) {
      const data = await client.call('core_calendar_get_action_events_by_timesort', {
        timesortfrom, timesortto, limitnum: 50, aftereventid,
      });
      if (!Array.isArray(data.events)) throw new Error('Missing calendar event list');
      for (const event of data.events) {
        if (!Number.isInteger(event.id) || event.id <= 0 || seen.has(event.id))
          throw new Error('Repeated or missing calendar event ID');
        seen.add(event.id); result.events.push(event);
      }
      checkWarnings(data);
      if (data.events.length < 50) return result;
      aftereventid = data.events.at(-1).id;
    }
    throw new Error('Calendar pagination limit reached');
  } catch (error) { throw partialError(error, result); }
}

export async function collectRefresh(client, state) {
  const report = { started_at: new Date().toISOString(), moodle_url: client.baseUrl, pages: [], forums: [], threads: [],
    submissions: [], attempts: [], errors: [], scope_limits: [], files_downloaded: 0, reviewed: false };
  const safe = async (scope, work) => {
    try { return await work(); } catch (e) { report.errors.push({ scope, error: e.message }); return e.partial ?? null; }
  };
  const pageMap = new Map(state.courses.flatMap(c => (c.moodle_course_ids ?? []).map(id => [id, c.id])));
  if (!pageMap.size || [...pageMap.keys()].some(id => !Number.isInteger(id) || id <= 0))
    throw new Error('Choose valid course IDs first');
  const courseArgs = Object.fromEntries([...pageMap.keys()].map((id, i) => [`courseids[${i}]`, id]));
  report.assignments = await safe('assignment_catalog', async () => validateAssignments(await client.call('mod_assign_get_assignments', courseArgs)));
  report.quizzes = await safe('quiz_catalog', async () => checkWarnings(validateList(
    await client.call('mod_quiz_get_quizzes_by_courses', courseArgs), 'quizzes', q => object(q) && validId(q.id) && validId(q.course))));
  for (const [courseid, course_id] of pageMap) {
    const sections = await safe(`course:${courseid}`, async () => validateSections(await client.call('core_course_get_contents', {
      courseid, 'options[0][name]': 'excludecontents', 'options[0][value]': 1,
    })));
    if (!sections) continue;
    report.pages.push({ course_id, courseid, sections });
    for (const module of sections.flatMap(s => s.modules).filter(m => m.modname === 'forum')) {
      const discussions = await safe(`forum:${module.instance}`, () => readDiscussions(client, module.instance));
      report.forums.push({ course_id, courseid, module, discussions });
    }
  }
  const visibleModules = new Set(report.pages.flatMap(p => p.sections.flatMap(s => s.modules))
    .filter(m => m.uservisible !== false).map(m => m.id));
  for (const w of report.assignments?.warnings ?? []) {
    if (w.item === 'module' && w.warningcode === '1' && !visibleModules.has(Number(w.itemid))) {
      report.scope_limits.push({ scope: `module:${w.itemid}`, reason: 'not_accessible_in_current_student_course_view', api_warning: w });
    } else report.errors.push({ scope: 'assignment_catalog', error: JSON.stringify(w) });
  }
  const threads = report.forums.flatMap(f => (f.discussions ?? []).map(d => ({ course_id: f.course_id,
    forumid: f.module.instance, forum_url: f.module.url, discussion: d })));
  let cursor = 0;
  await Promise.all(Array.from({ length: 3 }, async () => {
    while (cursor < threads.length) {
      const item = threads[cursor++];
      const posts = await safe(`discussion:${item.discussion.discussion}`, async () => verifyPosts(item.discussion,
        await client.call('mod_forum_get_discussion_posts', { discussionid: item.discussion.discussion, sortby: 'created', sortdirection: 'ASC' })));
      report.threads.push({ ...item, posts });
    }
  }));
  for (const c of report.assignments?.courses ?? []) {
    for (const a of c.assignments) {
      const status = await safe(`assignment:${a.id}`, async () => checkWarnings(await client.call('mod_assign_get_submission_status', { assignid: a.id })));
      report.submissions.push({ assignment_id: a.id, courseid: c.id, cmid: a.cmid, status });
    }
  }
  // Required quizzes or existing tracked tasks; question banks are not automatically homework.
  const urls = new Set((state.tasks ?? []).map(t => t.source?.url).filter(Boolean));
  for (const q of report.quizzes?.quizzes ?? []) {
    if (!q.timeclose && !urls.has(`${client.baseUrl ?? process.env.MOODLE_URL}/mod/quiz/view.php?id=${q.coursemodule}`)) continue;
    const data = await safe(`quiz:${q.id}`, async () => checkWarnings(await client.call('mod_quiz_get_user_attempts', {
      quizid: q.id, userid: client.userId, status: 'all', includepreviews: 0,
    })));
    report.attempts.push({ quiz_id: q.id, courseid: q.course, cmid: q.coursemodule, data });
  }
  const now = Math.floor(Date.now() / 1000);
  const timeend = now + 31 * 86400;
  const action = await safe('calendar', () => readCalendar(client, now, timeend));
  const groups = new Set();
  for (const courseid of pageMap.keys()) {
    const data = await safe(`calendar_groups:${courseid}`, async () => checkWarnings(validateList(
      await client.call('core_group_get_course_user_groups', {courseid, userid: client.userId}),
      'groups', g => object(g) && validId(g.id))));
    for (const group of data?.groups ?? []) groups.add(group.id);
  }
  const ordinary = await safe('calendar_general', () => readOrdinaryCalendar(client,
    [...pageMap.keys()], [...groups], now, timeend));
  const events = new Map((action?.events ?? []).map(event => [event.id, event]));
  for (const event of ordinary?.events ?? []) {
    const previous = events.get(event.id);
    const merged = {...previous, ...event, course: previous?.course ?? {id: event.courseid ?? 0}};
    if (previous && ['name', 'description', 'timestart'].some(key =>
      previous[key] !== undefined && event[key] !== undefined && previous[key] !== event[key])) {
      merged.action_event = previous;
      report.errors.push({scope:`calendar_event:${event.id}`, error:'Calendar event changed between API reads; both versions retained'});
    }
    events.set(event.id, merged);
  }
  report.calendar = {events: [...events.values()].sort((a,b) => a.id - b.id),
    coverage: {timestart: now, timeend, action_events_requested: true, ordinary_events_requested: true,
      courseids: [...pageMap.keys()], groupids: [...groups], siteevents: true, userevents: true}};
  report.finished_at = new Date().toISOString();
  report.collection_complete = report.errors.length === 0;
  return report;
}
