# Hourglass Bench

**One hour. How much can your agent solve?**

Hourglass Bench is a local evaluation harness for tool-using AI models. Give each model the same private question bank and measure how many questions it answers correctly within **one hour of active wall time**.

## Results

I use **private questions** for my own Hourglass Bench evaluations. Published results contain aggregate scores, hardware and recorded model configurations; the questions, answers and traces stay private.

Browse the [Results index](reports/README.md) for published runs and model improvement charts. Related releases share a model-family label, with dated entries for weights revisions, quantization, inference engines, harnesses and parameters. Earlier runs remain available, including regressions. Different hardware and evaluation protocols are separated; partial runs are clearly marked.

See [recording model improvements](docs/results-history.md) for the workflow and repository layout. This is a record of experiments on a private bank, not a universal model ranking.

## Bring your own questions

**Bring your own question bank.** This repository includes only a tiny, explicitly labeled [hello-world demo](examples/hello-world) to check your setup. No private benchmark questions, private answer keys, question images, datasets, or recorded model runs are included. There is no bundled 100-question test and no universal leaderboard.

Create your bank locally under `tasks/`. That directory, model configuration, results, logs, and backups are ignored by Git. See [the task format](docs/task-format.md). The automated tests use small software fixtures, not a benchmark question bank.

Scores are comparable only when models use the **same questions, order, repeat policy, harness and relevant execution settings**. A score from somebody else's private bank is not directly comparable with yours.

## What it measures

- 1–2 fixed difficulty points for each distinct question answered correctly within 3,600 active seconds, alongside the raw correct count.
- Thinking, tools, initialization, grading, and retries consume the time budget. Pauses between resumes do not.
- Correct questions earn 1–2 points; an incorrect final answer costs 1 point. Timeouts, unsupported vision, and no final answer earn zero.
- Text and vision subtotals accompany the main score.
- At one hour, the harness stops the benchmark process group and plays a short system chime.
- Results preserve per-attempt timing, token usage, tool traces, model settings provenance, and question hashes.

Difficulty weights are versioned as `weighted-hour-v1`; the active-clock boundary remains `hour-v1`. See [scoring](docs/scoring.md) for boundaries, partial runs, and repeat behavior.

## Waves of questions

Regular questions cycle through **easy → medium → hard**, rotating subjects within each difficulty band. This gives the early part of a run a mixture of difficulty and subject matter. The order is fixed before the run and does not adapt to the model's answers.

The private version 2.2 reference evaluation adds a challenge after every four regular questions. The regular cycle continues across those insertions. Its 120-question bank remains private; the public runtime supports this cadence for user-authored challenge tasks.

All waves share the same one-hour clock. Each question has a 15-minute total limit, including tools, retries and repeats. Time spent reasoning and checking answers reduces the time available for later questions. Read [the method: waves of questions](docs/methodology.md) for the sequence, challenge cadence, scoring rationale and comparison limits.

## Requirements

The current supported environment is **macOS on Apple Silicon**, Python 3.10+, Git, and Node.js **22.19+**. The bundled frozen Pi dependency snapshot includes Darwin ARM64 binaries; other platforms are not currently validated. Sandboxing uses macOS `sandbox-exec`; the completion chime uses `afplay`.

Run an OpenAI-compatible local model server with chat-completions streaming and tool calling. Vision questions additionally require a vision-capable model. LM Studio metadata discovery is supported. Other servers need an explicit, accurate `context_window` in configuration when context metadata is unavailable.

## Quick start

```sh
git clone https://github.com/JordiPosthumus/hourglass-bench.git
cd hourglass-bench
cp models.example.json models.json
```

Edit `models.json` with your actual model ID, endpoint, context window, and output capacity. Match the limits supported by your loaded server. Temperature is delegated to the server; unknown server settings are shown as unknown rather than invented.

Add your own local task definitions under `tasks/<your-id>/task.json`, following [the schema and authoring guide](docs/task-format.md). No questions will appear until you add them. To install only the optional setup demo, run `python3 scripts/install_demo.py`.

```sh
./start-hourglass.sh
```

The UI opens on a free loopback port, normally `http://127.0.0.1:4534`. Select your bank and model, use **one repeat** for the standard score, review, and start. Use `HOURGLASS_PORT=8790 ./start-hourglass.sh --no-open` for an explicit port.

## Frozen agent harness

The runtime uses the **Pi 0.85.1 SDK**, vendored with its dependencies and a per-file SHA-256 manifest. It uses Pi's agent loop, file tools, bash, and compaction, plus a final-answer tool and workspace restrictions. The snapshot is verified before every attempt. It does not depend on, upgrade, or reconfigure a globally installed Pi.

The vendor snapshot makes this repository larger than a typical Python project. It is included deliberately for reproducibility. See [third-party notices](THIRD_PARTY_NOTICES.md).

## Development

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/test_ui.js
node tests/test_speed.js
python3 scripts/check_public_release.py
```

On the supported macOS environment, `python3 tests/pi_integration.py` and `python3 tests/pi_stop_integration.py` exercise the frozen harness against a local fake streaming endpoint. They do not call a real model. `python3 tests/pi_no_turn_limit_integration.py` also verifies that historical turn-limit metadata cannot stop the agent.

The low-level `python3 hourglass.py run ...` command runs an individual task for diagnostics. **Use the UI run controller for the one-hour automatic stop.** A manual single-task invocation does not start a timed evaluation by itself.

## Privacy and local execution

The web UI binds to loopback and provides access to your local questions and results. Do not expose it to the internet. Model requests go to the endpoint you configure; using a remote endpoint sends it your question content. Results and tool traces can contain private prompts and generated reasoning, so keep them out of public Git repositories.

## License

First-party code is MIT licensed. Vendored dependencies retain their respective licenses and notices.

## Maintaining an installation

See [the model, hardware and release maintenance guide](docs/maintenance.md) before changing models, updating GitHub, or handing work to another agent.

## Net scoring and Run editor

New UI runs use `net-hour-v2`: +1–2 by difficulty for a correct question, −1 for a submitted incorrect final answer, and zero for unsupported vision, timeout or no final submission. Tool errors have no direct penalty. Each question is counted once; any correct repeat supersedes a previous wrong submission, otherwise a question with an incorrect submission loses one point. Gross points, incorrect counts and abstentions remain visible. The original question instructions and final-answer tool schema are retained; scoring is applied by the grader without an extra scoring paragraph. Explicit abstention is not offered. Historical `net-hour-v1` runs retain their original abstention rules and are compared separately. Net scores and signed step AUC can be negative. Historical runs retain their original scoring policy and comparison cohort.

Open **Run editor** beside the saved-run selector to record model/revision, quantization, server/version or PR, hardware, sampling settings, limits, reasoning, concurrency, cache details and notes. Identity components offer saved choices and lint new values; the run name is generated from those components. Saving creates an immutable revision and retains older choices. You can restore an earlier revision's values and save them as a new revision. Descriptions are user-reported; captured execution records are shown separately. This editor records details and does not change endpoint configuration. Run records and reusable choices stay local.

The console defaults to `http://127.0.0.1:4534`. Score preview and publication review are served on the same site under `/scores/`; the launcher no longer starts a second listener. An explicit port environment variable still overrides the default.

## Reliability and chart update (2.5.0)

Run configuration is captured at enqueue time and passed unchanged to each question. Editing saved endpoints affects future runs. Interrupted runs with uncertain active time keep their results but withhold a final hourly score; use New run to reuse their setup. Final status waits for all planned repeats or the hour boundary. Timeouts are excluded from answer accuracy. Historical policy names are normalized consistently.

New run copies the selected run’s model, question selection, repeats and recorded details, while starting a new clock under the current grading policy. Run editor labels populate score preview; notes remain local. Explicit report-label overrides remain until the run details change, except the configuration name, which always follows the canonical identity. Token-efficiency charts use a base-10 logarithmic x-axis, with fewer tokens to the right; zero-token points are omitted and counted in the caption.

See [the exact prompt contract](docs/prompt-contract.md).

## Release versions and comparisons

Comparisons default to all hardware and include runs with the same major release and exact frozen questions, order, weights and repeat counts. Minor and patch releases do not hide earlier runs. Use Same hardware to narrow the comparison. Original scores remain unchanged; chart labels disclose each run's release, scoring policy and question deadline.

Major releases mark incompatible benchmark generations. Minor releases add functionality or explicitly versioned evaluation policies; patch releases fix implementation and presentation. The release number alone never establishes identical conditions: frozen bank identity and recorded policies remain authoritative.

## Starting, stopping and resuming

Run `./start-hourglass-bench.sh` in your own Terminal; it opens the UI. Keep that Terminal open. On macOS, `./stop-hourglass-bench.sh` cancels queued work, asks the active test to stop, waits for results to be saved, and closes only this checkout's UI and report helper. Model servers remain running.

Use **Resume run** to continue a stopped evaluation with its recorded time and completed answers. After an interrupted controller, startup can also recover the clock when a finished phase and a persisted stopped-Pi shutdown trace agree. Recovery backs up the original manifest and supporting evidence, retains the completed answers, charges interrupted work, and excludes downtime. Without that evidence, the clock is shown as unavailable instead of a misleading zero or fresh hour.

Controller shutdown now waits for saved worker state. If the controller is killed unexpectedly, its worker stops its own workload and writes a matching exit receipt for clock recovery. Recovery preserves completed answers, prior pauses and frozen run metadata; status refresh retries if the receipt arrives after startup. Committed attempt files missing from the result index are restored once with an index backup. Power loss or killing both processes may leave timing unavailable when no trustworthy exit evidence exists.

The score comparison has a taller plot and a scrollable model table. Hover over the plot or use the time slider to see each model’s question and time spent at that point, plus its longest question so far. Expand a model for its full name and recorded rules. Question summaries are 5–7 words in a separate, hash-matched `question-summaries.json` catalogue; they do not change question content or scoring. Question details remain local and are excluded from public report exports.

Custom model scale lets you assign your own numeric targets to recorded Hourglass runs, including completed hours and partial snapshots. All runs are shown by default. Reference points are frozen when saved; a shared linear fit places other models approximately on your scale and labels extrapolation. Original Hourglass scores are retained. Targets are local, backed up on edits and excluded from publication. The optional full-bank accuracy tools remain available separately.

### Live throughput and request overlap

The live run panel separates measured decode TPS from tools and prompt processing. LM Studio telemetry reads existing server logs, preserving their timestamps; it sends no inference requests and changes no server settings. It shows the three-second decode rate, request average, observed active requests, and an explicit unknown state when telemetry is stale or attribution is ambiguous. Counts cover the observed server, not other GPU applications.

For a local LM Studio endpoint, create an ignored `telemetry-sources.json` file (merge with existing entries):

```json
{"_endpoints":{"http://127.0.0.1:1234/v1":{"type":"lmstudio","log_dir":"~/.lmstudio/server-logs"}}}
```

Use the endpoint URL exactly as saved in the model configuration. The reader resolves the model ID from each run’s frozen configuration and starts with subsequent runs. Existing per-model remote log sources remain supported and take precedence. An already running controller can receive telemetry without restarting the benchmark: run `python3 lmstudio_telemetry.py --root . --job RUN_ID` from the benchmark directory. This passive reader exits when that run stops; it records only timing and request metadata, never prompts. A file lock prevents duplicate collectors.

## Add models without editing JSON

In **Model settings**, choose **Add from LM Studio** to search downloaded variants and loaded aliases through the local `lms` CLI. The picker reads the library, loaded models and server status; it does not load, unload, download or reconfigure models.

Choose **Add a server model**, paste a server root or OpenAI-compatible base URL, then click **Inspect endpoint**. Discovery reads `/v1/models` (or `/models`), LM Studio metadata, `/props` and `/health` where available. Select a model to see its reported context, output maximum, provider and supported parameters. Missing settings remain unknown. DS4 endpoints that advertise an OpenAI-compatible model list are supported. The form does not configure authentication credentials.

Review the display name, model ID, hardware and explicit output limit before adding. A reported output maximum is suggested when available; otherwise a reported context is suggested visibly for review. The optional context field remains empty for runtime discovery. Adding appends one configuration, preserves existing entries and additional fields, and creates a timestamped backup. Duplicate copies additional fields; the advanced JSON editor remains available. Revision checks reject stale saves. Discovery sends no inference requests and does not alter server settings.


## Diagnostic isolation and question resets (2.5.1)

New attempts keep harness traces, stderr, integrity records, Pi request configuration and SDK sessions in `runtime-diagnostics/`, outside the model workspace. All exposed filesystem tools and bash run with OS denials for harness runtime storage, including when optional task sandboxing is disabled. Authored task files remain available. Result artifacts retain the original trace plus raw diagnostic copies; recovery supports historical locations only for older attempts. No model limits, thinking settings, question content or scoring weights change.

In the run view, choose **Reset & rerun questions**, select individual attempts, enter a reason and reset once active and queued work are idle. Raw artifacts remain available; a timestamped backup saves the original index, manifests and reference scales. A reset ledger prevents crash recovery from restoring deliberately removed results. Reset runs cannot publish their old hourly score or resume that clock. The rerun buttons select affected questions and the saved model; review the new run to start it. Previous reset plans remain accessible from the same control. These are fresh targeted evaluations, not replacements for a complete one-hour comparison.

For endpoints that return incomplete streamed tool arguments, an explicitly selected `"response_mode": "complete"` in a saved model configuration requests complete JSON responses. The benchmark adapts these for frozen Pi, preserving reasoning, usage and tool arguments. Generation settings and the direct endpoint stay unchanged; token-by-token progress is unavailable until each response finishes. The default remains streaming.

## Canonical run identity and bank hardening (2.6.0)

Hardware comparison groups are editable for any installation; original labels, machine identities and results are retained. New evaluations freeze complete question bundles, reject stale configuration reviews, and randomize option IDs and positions with auditable seeds. See [run identity and migration](docs/run-identity.md).

## Readable configurations and complete history (2.6.1)

Names use compact hardware/server-recipe/model/quantization components, are editable and resettable, and persist across repeated runs of the same configuration. New-run review requires missing identity details. All historical runs remain selectable across bank versions. Completed equivalent repeats can be averaged or expanded to individual measurements. See [run identity and comparison details](docs/run-identity.md).
