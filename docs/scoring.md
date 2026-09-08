# Scoring: hour-v1

The score is a count, not a percentage or difficulty-weighted estimate. Each distinct question contributes one point if a completed, correct result is recorded at or before 3,600 active seconds. The exact boundary is inclusive; later records are excluded even if shutdown takes an additional moment.

The clock starts when the queued evaluation begins executing. It includes model initialization, thinking, tool use, grading, errors and retries. It excludes queue time and recorded pauses between resumes. Scores from old resumed runs without sufficient interval history are withheld rather than guessed.

Text and vision points add to the total. Wrong answers and execution errors are distinguished. Unfinished and unreached questions contribute zero without being presented as observed incorrect answers.

Use one repeat per question. If you deliberately configure multiple repeats, any correct repeat inside the window can earn that question's one point; additional correct repeats cannot increase it. Compare only identical repeat policies.

The UI shows an in-progress score while the hour is running. An early stopped run is partial unless all its questions finished. There is no extrapolation from early throughput. A model that completes the whole bank early receives its actual count, with elapsed time retained as a diagnostic. If this creates a ceiling, expand your private bank and give the new bank a distinct scope.

Questions run in ascending authored difficulty tier, alternating sections within a tier. These are labels, not empirically calibrated difficulty. Math education labels can be mapped to estimated scheduling tiers (1, 5, 9). The existing stop after 20 consecutive incorrect questions is retained and may end a run before one hour; such a score is partial.

At the deadline the UI controller signals the benchmark process group, preserves completed attempts, and plays a system chime. The model server itself is not stopped. There are no separate short per-question, bash, or generation deadlines; there is no harness turn-count limit. Configured model output/context limits still apply.

For comparison, hold bank content and order, repeats, harness version, model configuration, and hardware constant or disclose their differences. Record server sampling settings when available. Hourglass Bench is a measurement tool, not a shared standardized test set.
