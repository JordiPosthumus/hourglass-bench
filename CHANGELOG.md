# Changelog

## Unreleased

- Move new-run setup into an on-demand, keyboard-accessible right-side drawer, preserving drafts on close and showing setup inline before the first saved run.
- Collapse technical setup details and benchmark rules, simplify the fixed-bank summary, and remove redundant score breakdown cards beneath the chart.

## 4.1.0 — 2026-09-12

### A focused workspace

- Moved the question library into a dedicated Questions tab beside Runs and Archived runs.
- Added question previews, a model filter, and sortable answer-time, outcome-rate, points and attempt-count columns. Column headings toggle direction and expose accessible sort state.
- Removed question-selection controls. New benchmarks require the full installed bank; the server determines execution order and rejects subsets. New targeted reruns are disabled without deleting historical repair records.
- Simplified graph labels to avoid repeated hardware names and policy/deadline text. Detailed metadata remains in the run records.
- Added regression coverage for statistic definitions, revision matching, duplicate exclusion, header sorting, full-bank enforcement and preserved historical resumes.

### Documentation

- Added the [workspace guide](docs/workspace.md) and refreshed the README, scoring and maintainer guidance.
- Removed stale descriptions of AUC scoring, forecasts and selectable benchmark subsets.

## 4.0.0 — 2026-09-12

- Replaced the headline metric with recorded total points; removed AUC scoring, forecasts and custom calibration.
- Added automatic whole-bank rounds: wrong answers, unfinished questions, then correct answers, slowest first within each group. All attempts share the original one-hour clock.
- Added visible chart tabs, run-identifying line labels, and reversible archive/restore.
- Preserved frozen run evidence and existing model configuration. New runs and resumes use an unscored warm-up before their scoring clocks start.
