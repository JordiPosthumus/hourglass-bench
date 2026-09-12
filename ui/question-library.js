'use strict';
// Read-only statistics: actual attempts, current question revision, saved runs.
const QuestionLibrary = (() => {
  function summarize(tasks, results, jobs, model = '') {
    const catalog = new Map(tasks.map(t => [t.id, t]));
    const saved = new Set(Object.values(jobs || {}).flat().map(j => j.id));
    const stats = new Map(tasks.map(t => [t.id, {attempts:0, answered:0, wrong:0, timeouts:0, errors:0, timed:0, seconds:0}]));
    const seen = new Set();
    for (const r of results || []) {
      const t = catalog.get(r.task);
      if (!t || !saved.has(r.evaluation_id) || r.repair_inherited || (model && r.model !== model)) continue;
      const matches = r.task_bundle_sha ? r.task_bundle_sha === t.task_bundle_sha : r.task_sha && r.task_sha === t.task_sha;
      if (!matches || !['completed','timeout','error'].includes(r.status) || r.score_reason === 'unsupported_vision' || r.score_reason === 'abstained') continue;
      const key = r.artifact_dir || r.run_id || JSON.stringify([r.evaluation_id,r.task,r.run,r.ts]);
      if (seen.has(key)) continue;
      seen.add(key);
      const s = stats.get(t.id);
      s.attempts++;
      if (r.status === 'error') s.errors++;
      else if (r.status === 'timeout') s.timeouts++;
      else if (!r.score_reason && typeof r.solved === 'boolean') {
        s.answered++;
        if (!r.solved) s.wrong++;
        if (Number.isFinite(r.duration_s) && r.duration_s >= 0) { s.timed++; s.seconds += r.duration_s; }
      }
    }
    for (const s of stats.values()) {
      s.average = s.timed ? s.seconds / s.timed : null;
      s.wrongRate = s.answered ? s.wrong / s.answered : null;
      s.timeoutRate = s.attempts ? s.timeouts / s.attempts : null;
      s.errorRate = s.attempts ? s.errors / s.attempts : null;
    }
    return stats;
  }
  function sort(tasks, stats, key, direction = 'desc') {
    if (key === 'order') return [...tasks];
    const value = t => key === 'title' ? t.title : key === 'points' ? t.points : key === 'tier' ? (t.order_tier ?? t.tier) : stats.get(t.id)?.[key];
    return tasks.map((t,i) => ({t,i})).sort((a,b) => {
      const x=value(a.t), y=value(b.t), missing=v=>v==null || (typeof v==='number' && !Number.isFinite(v));
      if (missing(x) || missing(y)) return missing(x)===missing(y) ? a.i-b.i : missing(x) ? 1 : -1;
      const delta=typeof x==='string' ? x.localeCompare(y) : x-y;
      return (direction==='asc' ? delta : -delta) || a.i-b.i;
    }).map(x=>x.t);
  }
  return {summarize, sort};
})();
if (typeof module !== 'undefined') module.exports = QuestionLibrary;
