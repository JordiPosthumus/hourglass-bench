# Model, hardware and release maintenance

This guide is for future maintainers and agents. Read the repository's working agreements and the current source before changing a live installation. Preserve established model capabilities and private benchmark data.

## Server and harness contracts

Read [Issue for Agents](issues-for-agents.md), [the replayable output-space patch](../backend-patches/output-space/README.md), [server specifics](server-specifics-guide.md) and [inference profiles](inference-profiles.md) before changing a backend. The patch helper checks exact source hashes, backs up changes and supplies rollback; rebuilding a deployment still requires preserving its existing image, pins, kernels, launch flags and prerequisite patches. Validate complete prompt handling, intentional small limits and a real cold-to-warm cache hit.

Hourglass 3.0.0 uses native Pi declarations for new profiles; historical profiles retain their saved behavior. The headline score is independently versioned as `linear-auc-100-v1`. [The scoring specification](results-history.md#hourglass-score) defines the scale and separates live forecasts from measured exports.

## Safe model updates

1. Inspect `/api/state`. Wait until the running and pending queues are empty before changing the inference server or restarting the controller, unless the owner explicitly authorizes interruption.
2. Record the actual model identifier, model file and quantization, context/output capacities, reasoning settings, concurrency, cache behavior and relevant kernels. Read the current configuration and recent requested/server-setting records; example configuration is not a production recommendation.
3. Make timestamped backups of affected launchers, configuration and source, with a short description of the exact intended delta. Preserve the last working model and configuration.
4. Change only what was requested. Never carry reduced diagnostic settings into production without explicit approval. Changes reducing capacity, cache reuse, intelligence, performance or retention require an explained tradeoff and authorization.
5. Verify live effective settings and exercise the capability being claimed. Prove cache reuse with a real cold-to-warm hit. A process starting or JSON parsing does not prove preservation.
6. Record the inference hardware. Start a new evaluation after changing model settings. Resume intentionally rejects changed model-config hashes and question content.
7. Use the same bank, order, repeat policy, scoring version and relevant execution settings for comparisons. Preserve original results when runs are interrupted.

The normal launcher is `./start-hourglass.sh`. `HOURGLASS_PORT` chooses a loopback UI port; reports use the same listener under `/scores/`. Identify the exact process and checkout before restarting anything. Do not kill unrelated services by port or process name.

## Scoring and execution boundaries

`weighted-hour-v1` awards fixed difficulty weights once per distinct correctly completed question: charts tier 1–10 maps linearly to 1–2, games tier 1–5 to 1–2, and math high school/undergraduate/graduate to 1/1.5/2. Other or unlabeled questions earn 1. Raw correct counts remain visible. Weights are independent of the selected bank and frozen in new manifests; historical enrichment requires a matching content hash. Authored labels are provisional rather than empirically calibrated difficulty.

`hour-v1` defines an inclusive 3,600-active-second completion boundary. Thinking, tools, initialization, grading and retries normally count; pauses between resumes do not. Late answers do not count. Partial runs are not extrapolated. Twenty consecutive incorrect answers can end a run early.

The native adapter has no turn-count cap. Do not restore a diagnostic `maxTurns` abort. The global hour limit remains intentional. Keep execution changes and scoring-policy changes separately versioned and documented.

## Hardware and machine-specific charts

The UI offers all historical runs, matching-bank comparisons and a same-hardware filter. Compatible comparisons check frozen bank, order, weights, repeats and recorded policies; version labels do not establish equivalent conditions by themselves. Each line ends at its actual elapsed time. Use the hardware filter when comparing machines under the same conditions, and inspect the individual records. See [run identity](run-identity.md).

For direct loopback inference, hardware is queried locally and frozen at evaluation creation. The private `.machine-id` supplies a stable random identity; public reports contain its hash, chip, memory, CPU and available GPU details, without hostname or serial number. Keep this identity stable on one physical machine and never copy it to another physical machine.

For remote inference—or a loopback tunnel forwarding to a remote machine—create ignored `hardware-profiles.json` keyed by the exact configured base URL:

```json
{
  "http://remote-server.example:8000/v1": {
    "machine_id": "stable-unique-physical-machine-id",
    "label": "My remote workstation",
    "chip": "verified platform name",
    "memory_bytes": 137438953472,
    "cpu_cores": 20,
    "gpu": [{"model": "verified GPU name"}]
  }
}
```

These are illustrative values, not a recommended configuration or a claim about any named product. Substitute measured values and omit unknown fields. Profiles are labeled owner supplied. Never record the controller's local hardware as that of a remote model server.

Unknown hardware is isolated per evaluation rather than combined. Changing a profile must not relabel historical runs. Evidence-backed historical attachments can be stored in ignored `hardware-records/<evaluation-id>.json` with owner authorization and a backup. Explicit owner-recorded amendments take precedence while preserving the frozen manifest; older automatic attachments remain secondary.

## Reports and GitHub publication

Use **Record & publish score** to review the generated aggregate report and charts before uploading. Inspect the exact files listed in that preview; the selected comparison scope is recorded. The individual score chart retains weighted and raw-correct curves.

Install and authenticate the GitHub CLI, choose an existing `owner/repository`, then explicitly click **Publish these files to GitHub**. The publisher uploads only the reviewed aggregate files, creates a commit under a unique `reports/` folder, and updates the default branch without force. It never pushes the local working directory. If a concurrent update prevents publication, refresh and retry. Restarting the controller invalidates existing preview tokens, so refresh afterward.

Public exports exclude questions, options, answers, per-question IDs, raw traces, private paths, endpoints, credentials, hostnames and serial numbers. Hardware equality alone does not establish equivalent quantization, context, software or cache conditions. Recorded configuration disclosure accompanies the export; unknown settings stay unknown. Inspect the reviewed output and do not claim controlled comparisons without equivalent settings.

If an owner-authorized harness timing correction is necessary, preserve raw results, back up the manifest, record exact excluded intervals and a correction ledger, and avoid double credit. Do not fabricate pause history. A small footnote can accompany the report while exact adjustment amounts remain in JSON.

## Source maintenance and releases

Relevant files:

- `hourglass.py`, `launch.py`, `web.py`: CLI, launch and queue.
- `harness_runner.py`, `harness/pi.mjs`: native Pi integration.
- `vendor/pi-0.85.1/`, `harness/pi-lock.json`: frozen dependency snapshot and inventory.
- `calibration.py`: frozen manifests and evaluation metadata.
- `hour_score.py`, `score_weights.py`, `ui/hour-score.js`: score calculation and parity.
- `hardware_records.py`: machine recording and explicit remote profiles.
- `score_report.py`, `score_publisher.py`: aggregate report allowlist and reviewed publication.
- `tests/`: unit, UI and native fixture checks.

Keep private installations and public release checkouts separate when maintaining a private question bank. Copy only an explicit list of source, tests and public documentation. Never recursively sync the private checkout into the public repository. Preserve the public entry-point and environment-variable naming when adapting code from another installation.

Never stage private banks, results, manifests, logs, sandboxes, model configuration, provenance, hardware identities/profiles/records, annotations, correction ledgers or backups. The only bundled question is the labeled hello-world demonstration. Inspect the staged diff and run the public-release audit after staging new files.

Run the ordinary checks in every affected checkout:

```sh
python3 -m unittest discover -s tests -q
node tests/test_ui.js
node tests/test_speed.js
python3 scripts/check_public_release.py
git diff --check
git diff --cached --check
```

For adapter, tool or shutdown changes, run applicable native fixtures:

```sh
python3 tests/pi_native_integration.py
python3 tests/pi_explicit_integration.py
python3 tests/pi_integration.py
python3 tests/pi_no_turn_limit_integration.py
python3 tests/pi_stop_integration.py
```

Fixtures use a local fake provider, not a production model. They require local-port/sandbox permissions where applicable. Keep fixture settings in fixtures. Review the live report graph as well as the JSON.

Before pushing, verify the remote, branch and complete staged diff. Push reviewed source commits normally; do not force-push or publish scores as an incidental part of a source update. Check CI for the exact pushed commit and record its result in the handoff.

## Shutdown and dependency upgrades

On a requested stop, the wrapper terminates Pi and drains stdout/stderr with `communicate()` while awaiting exit. Waiting without draining can deadlock when an abort fills an output pipe. Interrupted output is retained in the diagnostic artifacts outside the model workspace. The tests cover output larger than pipe capacity and native tool cancellation. The controller stops the benchmark process group, not the inference server.

Before upgrading frozen Pi, read `docs/frozen-pi.md`. Use a separately versioned snapshot, update its license/provenance and hash inventory, verify tools, unlimited turn behavior and shutdown, and preserve a rollback to the previous working snapshot. Do not patch model limits to make compatibility tests pass.

Rollback only when the affected component is idle. Restore the exact backed-up files, preserve unrelated work, and validate live behavior. A final handoff should list current run state, whether the next model can start, code commits and CI, backups, measurements, unresolved work and any approval block. Do not describe source-only changes as already active.

## Main-page charts

The selected run and publication preview use report rendering integrated into the main controller. The Results chart now uses four colored accuracy/token-efficiency quadrants: higher accuracy goes up, and fewer median output tokens per scored answer goes right. Dots are labeled by model; bubble area is proportional to scored answers per active minute. The legend retains machine, run, sample count, speed and status. Until the owner requests otherwise, both axes automatically fit the displayed data with padding, and each quadrant boundary bisects its displayed axis range. Accuracy stays within 0–100% and token counts stay nonnegative. The four colored regions are equal-sized; their numerical boundaries adapt to the data and are not pass/fail thresholds. All scored answers for a displayed run must have valid output-token counts. Missing counts are not treated as zero. Output tokens include reported reasoning, tool calls and final answers. Filtered question sets and tokenizers may differ, so this is descriptive rather than a controlled ranking.

## Recording hardware and exporting the bubble chart

Use **Record hardware** on the main run card or edit the hardware section in **Score preview**. Choose an existing physical machine or create a new identity, enter the machine label, CPU/chip, RAM in GiB, CPU core count and GPU details, then click **Save hardware & refresh preview**. This writes an owner-recorded per-run amendment with a timestamped backup; it does not alter the frozen manifest, model settings or inference server. Selected machine identity also controls which other model runs join the comparison. Hardware profiles for future runs remain a separate configuration.

Changing the form disables publishing until saved. A stale preview cannot overwrite a newer hardware record or publish outdated selected-run hardware. Unknown hardware must be recorded before publication. The exact reviewed hardware appears in report JSON and the README.

The sixth report file, `quadrants.svg`, includes the accuracy/token-efficiency/speed bubble chart and is embedded in the published README. Its aggregate data is included in `report.json` and `comparison.json`. Export uses all scored answers in the compatible runs, not temporary Results-page filters. Bubble area scales with scored answers per active minute, including the run's thinking/tool overhead; unknown timing has no speed value. The same-machine/bank/policy grouping and adaptive bisected axes remain in force. Partial runs are explicitly labeled. Scores and chart files are uploaded only by the explicit publish action.


## Hardware, ordering and comparison updates
Hardware entry is one optional `hardware` string on each model in `models.json`, editable in the same Settings card. Existing endpoint profiles remain a fallback; past run records remain frozen. Reuse a description for the same machine and distinguish separate machines in their descriptions.

New runs use a fixed easy → medium → hard cycle, rotating categories within each band. Games use tiers 1–2 / 3 / 4–5; charts and estimated math levels use 1–3 / 4–7 / 8–10. Every selected question is retained; exhausted bands are skipped and unknown difficulty follows classified questions. Existing runs resume their original order. Exact order is included in comparison fingerprints. Difficulty does not modify reasoning settings or token limits; actual reasoning time is determined by the model.

Run charts offer same/all hardware scope and cumulative/ranking/accuracy-efficiency views. All-hardware comparisons still match bank, order, repeats, scoring and timing policies, and benchmark version. The selected run is compared with the latest matching run per model and machine. Rankings show actual weighted points, hardware and score status without extrapolation. Report previews include `ranking.svg` and record the comparison scope.

The log display clears on new run, run selection and resume. It shows the current invocation; Copy full log preserves earlier resume segments. Tool validation errors are printed with details, and global leaderboard tables no longer repeat in per-question console logs. Saved leaderboards still update.

Context discovery falls back to the matching `/v1/models` entry when LM Studio metadata is unavailable. Explicit image-support rejections from Pi are classified under the existing unsupported-vision zero-score policy; malformed images, authentication and context errors remain failures. Model settings are not automatically changed.

### Controller lifecycle

Start the app from your own Terminal with `./start-hourglass.sh`. SIGINT, SIGTERM and SIGHUP request graceful worker drainage before exit. `./stop-hourglass.sh` validates checkout and controller identity, cancels queued work and waits for saved state. New run/resume requests are rejected during shutdown. The worker watches its controller parent, stops its own process group if orphaned, and atomically saves an exit receipt. Recovery uses the exact question token and timestamps and backs up evidence before changing a manifest. Completed metric files missing from the append-only result index are reconciled under the same worker lock, with an original-index backup. Without reliable exit evidence, timing stays unavailable. Reports use the main UI at `/scores/`; no report helper is required.


## Diagnostic isolation and question resets (2.5.1)

New attempts keep harness traces, stderr, integrity records, Pi request configuration and SDK sessions in `runtime-diagnostics/`, outside the model workspace. All exposed filesystem tools and bash run with OS denials for harness runtime storage, including when optional task sandboxing is disabled. Authored task files remain available. Result artifacts retain the original trace plus raw diagnostic copies; recovery supports historical locations only for older attempts. No model limits, thinking settings, question content or scoring weights change.

In the run view, choose **Reset & rerun questions**, select individual attempts, enter a reason and reset once active and queued work are idle. Raw artifacts remain available; a timestamped backup saves the original index, manifests and reference scales. A reset ledger prevents crash recovery from restoring deliberately removed results. Reset runs cannot publish their old hourly score or resume that clock. The rerun buttons select affected questions and the saved model; review the new run to start it. Previous reset plans remain accessible from the same control. These are fresh targeted evaluations, not replacements for a complete one-hour comparison.


## Hourglass 2.7.1 release

The product and repository use the name Hourglass. Legacy launch and stop entry points continue to work, and old controller identity strings remain recognized. Existing environment variables and persisted browser state retain compatibility.

Repository discovery tasks can be woven into the selected bank after every eight existing questions, with Games, Hourglass and DSG rotation and source subtotals. No private task content is included in this repository. See [methodology](methodology.md) and [private question versioning](private-question-bank.md).

The start review displays the saved configuration once, without duplicate naming inputs. Missing descriptive fields do not block execution; genuine configuration/revision errors remain visible inside the dialog. Start errors leave the reviewed request intact for retry.


## Hourglass 2.7.2 release

The public README now leads with agent-assisted installation and creating a private bank. Follow [agent setup](agent-setup.md), [question authoring](question-authoring-recipe.md), [frozen Pi and credit](frozen-pi.md), and [server telemetry](telemetry.md). The brand directory contains a generated banner and a scalable SVG mark.

The current-question API reconstructs the frozen per-run/per-repeat option layout and exposes declared images; it never returns answer keys or presentation seeds. The UI refreshes the exact preview as repeats advance. Temporary attachments for an older active controller remain ignored private data under `ui/run-previews/`.

Passive telemetry adds MTPLX, oMLX, vLLM, SGLang, llama.cpp and explicitly selected DSG worker readers. LM Studio and legacy SSH logs retain support. Ollama's missing passive live counters are shown explicitly. Rate labels disclose request-average versus decode-window versus aggregate counter throughput. See the telemetry guide for version and attribution limitations. No inference parameters, frozen Pi files, option randomization policy or scoring rules changed in this patch.
