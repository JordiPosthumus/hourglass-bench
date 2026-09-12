# Scoring: total points

Every new benchmark uses the full installed bank. The server rejects subsets and computes first-pass order from the catalog, regardless of library sorting. Invalid installed questions must be repaired before starting, not omitted from a run.

New evaluations use `net-hour-v3` and `total-points-v1`. Every correct attempt earns its frozen authored weight; every incorrect final answer loses one point. Unsupported vision, timeouts and unfinished attempts earn zero. A later correct answer does not erase an earlier penalty. There is no AUC, normalization, prediction or custom calibration.

The first pass uses the existing bank order. Each subsequent round visits the whole bank once, ordered by the latest attempt: wrong answers, unfinished questions, then correct answers. Within each group, longest duration first; ties retain original bank order. A fresh conversation and workspace isolate every attempt from previous answers and grading. Round order is persisted before execution and survives resume.

All rounds share the original inclusive 3,600-active-second clock. Each round attempt has 900 seconds, including tools and time spent before an interruption; resume does not reset that allowance. Queue time, recorded pauses and the separate unscored warm-up are excluded. There is no turn-count or consecutive-wrong-answer stop. Model context, output, thinking and server settings are preserved.

Correct weights remain unchanged: charts tiers 1–10 map to 1–2 points, games tiers 1–5 map to 1–2, and math high school/undergraduate/graduate map to 1/1.5/2. Authored challenge weights and other sections retain their established rules. Text and vision subtotals add to total points. Reaching the bank’s end starts another round; it does not finalize the score early.

Historical evaluations retain their recorded execution and once-per-question award rules. Saved evidence and previously published snapshots are unchanged. New reports identify the metric and recorded policy; incompatible policies are not averaged.

## Charts and history

Visible tabs expose points over time, score ranking, accuracy/efficiency, throughput and speed comparison. The default chart is the recorded points-over-time step graph, with right-hand run labels and hover/focus highlighting. Rankings use recorded totals, never forecasts. Individual runs are shown by default; optional averaging only combines compatible completed runs.

Archive/restore changes backed-up visibility metadata only. Archived runs are excluded from normal local results and comparisons but remain viewable and restorable. No answers, settings, logs or artifacts are deleted.

Use Record & publish score to review aggregate files before publishing. Public reports exclude question content, answer keys, per-question identifiers, endpoints, credentials and raw traces. Existing published snapshots remain immutable.
