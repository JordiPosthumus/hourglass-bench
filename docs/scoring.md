# Scoring: net-hour-v2

New runs use net-hour-v2: an incorrect final answer costs one point per distinct question, a later correct repeat supersedes that penalty, and unsupported vision, timeout, or no final submission contributes zero. Explicit abstention is not offered. Historical scoring policies and original scores are retained.

The main score awards fixed difficulty weights to distinct correctly completed questions at or before 3,600 active seconds. Charts use authored tiers 1–10 mapped linearly to 1–2 points; games use tiers 1–5 mapped linearly to 1–2; math uses advanced high school = 1, advanced undergraduate = 1.5, graduate = 2. Other or unlabeled questions earn 1 point. Raw correct counts remain alongside the weighted score. Weights are fixed independently of the selected bank and frozen in new run manifests. Historical manifests are enriched only from content matching their saved hash. These authored labels are provisional, not empirical calibration. The exact boundary is inclusive; later records are excluded even if shutdown takes an additional moment.

The clock starts when the queued evaluation begins executing. It includes model initialization, thinking, tool use, grading, errors and retries. It excludes queue time and recorded pauses between resumes. Scores from old resumed runs without sufficient interval history are withheld rather than guessed.

Text and vision points add to the total. Wrong answers and execution errors are distinguished. Unfinished and unreached questions contribute zero without being presented as observed incorrect answers.

Use one repeat per question. If you deliberately configure multiple repeats, any correct repeat inside the window can earn that question's fixed weight; additional correct repeats cannot increase it. Compare only identical repeat policies.

The UI shows an in-progress score while the hour is running. An early stopped run is partial unless all its questions finished. There is no extrapolation from early throughput. A model that completes the whole bank early receives its actual weighted score, with elapsed time retained as a diagnostic. If this creates a ceiling, expand your private bank and give the new bank a distinct scope.

Questions run in repeated easy → medium → hard waves, rotating subjects within each band and skipping exhausted bands. Unknown difficulty follows classified questions. These authored labels are provisional; math education labels map to estimated scheduling tiers (1, 5, 9) when no numeric tier is supplied. See [the method: waves of questions](methodology.md), including the challenge insertion used by the private reference evaluation. The existing stop after 20 consecutive incorrect questions is retained and may end a run before one hour; such a score is partial.

At the deadline the UI controller signals the benchmark process group, preserves completed attempts, and plays a system chime. The model server itself is not stopped. Each question has a 900-second active budget including tools, retries and repeats; expiry advances automatically. There are no separate bash or generation deadlines; there is no harness turn-count limit. Configured model output/context limits still apply.

For comparison, hold bank content and order, repeats, harness version, model configuration, and hardware constant or disclose their differences. Record server sampling settings when available. Hourglass is a measurement tool, not a shared standardized test set.

## Publishing

Use **Publish score** in Results to review aggregate JSON data, individual and combined SVG graphs, and a README. Select `owner/repository` and click **Publish these files to GitHub**. Install the GitHub CLI and authenticate with `gh auth login` first. The repository must already have a branch. Publication adds the reviewed aggregate files in a unique folder under `reports/` with a non-forced atomic commit; it never pushes the local working directory.

Reports are served by the local controller under `/scores/`. Reports carry a bank/order/weight fingerprint and label unfinished runs as partial or in progress. No questions, answers, per-question IDs, raw traces, endpoints or credentials are exported. Hardware is frozen per run; model configuration disclosure is currently marked as not supplied.

The comparison offers all historical versions or same-bank hardware filters. Completed equivalent repeats are averaged by default, with individual runs available separately. Live and partial runs retain their actual measured endpoints. See [run identity and comparisons](run-identity.md). Clearing a local run removes it from future comparisons; historical published snapshots remain intact.
