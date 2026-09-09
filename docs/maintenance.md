# Model, hardware and release maintenance

This guide is for future maintainers and agents. Read the repository's working agreements and the current source before changing a live installation. Preserve established model capabilities and private benchmark data.

## Safe model updates

1. Inspect `/api/state`. Wait until the running and pending queues are empty before changing the inference server or restarting the controller, unless the owner explicitly authorizes interruption.
2. Record the actual model identifier, model file and quantization, context/output capacities, reasoning settings, concurrency, cache behavior and relevant kernels. Read the current configuration and recent requested/server-setting records; example configuration is not a production recommendation.
3. Make timestamped backups of affected launchers, configuration and source, with a short description of the exact intended delta. Preserve the last working model and configuration.
4. Change only what was requested. Never carry reduced diagnostic settings into production without explicit approval. Changes reducing capacity, cache reuse, intelligence, performance or retention require an explained tradeoff and authorization.
5. Verify live effective settings and exercise the capability being claimed. Prove cache reuse with a real cold-to-warm hit. A process starting or JSON parsing does not prove preservation.
6. Record the inference hardware. Start a new evaluation after changing model settings. Resume intentionally rejects changed model-config hashes and question content.
7. Use the same bank, order, repeat policy, scoring version and relevant execution settings for comparisons. Preserve original results when runs are interrupted.

The normal launcher is `./start-hourglass.sh`. `HOURGLASS_PORT` chooses a loopback UI port; the report helper uses UI port + 20. Identify the exact process and checkout before restarting anything. Do not kill unrelated services by port or process name.

## Scoring and execution boundaries

`weighted-hour-v1` awards fixed difficulty weights once per distinct correctly completed question: charts tier 1–10 maps linearly to 1–2, games tier 1–5 to 1–2, and math high school/undergraduate/graduate to 1/1.5/2. Other or unlabeled questions earn 1. Raw correct counts remain visible. Weights are independent of the selected bank and frozen in new manifests; historical enrichment requires a matching content hash. Authored labels are provisional rather than empirically calibrated difficulty.

`hour-v1` defines an inclusive 3,600-active-second completion boundary. Thinking, tools, initialization, grading and retries normally count; pauses between resumes do not. Late answers do not count. Partial runs are not extrapolated. Twenty consecutive incorrect answers can end a run early.

The native adapter has no turn-count cap. Do not restore a diagnostic `maxTurns` abort. The global hour limit remains intentional. Keep execution changes and scoring-policy changes separately versioned and documented.

## Hardware and machine-specific charts

Charts combine only the same inference machine, question-bank/order/weight fingerprint, timing policy and benchmark version. A selected run is compared with the latest eligible run of each other model. Each line ends at its actual elapsed time. Separate machines receive separate comparisons, including two machines with identical chip names.

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

Use **Publish score** in Results to review an immutable snapshot of six files: `README.md`, `report.json`, `score.svg`, `comparison.json`, `comparison.svg`, and `quadrants.svg`. The combined SVG is the same-machine model chart; the individual SVG retains both weighted and raw-correct curves.

Install and authenticate the GitHub CLI, choose an existing `owner/repository`, then explicitly click **Publish these files to GitHub**. The publisher uploads only the reviewed aggregate files, creates a commit under a unique `reports/` folder, and updates the default branch without force. It never pushes the local working directory. If a concurrent update prevents publication, refresh and retry. Restarting the helper invalidates existing preview tokens, so refresh afterward.

Public exports exclude questions, options, answers, per-question IDs, raw traces, private paths, endpoints, credentials, hostnames and serial numbers. Hardware equality alone does not establish equivalent quantization, context, software or cache conditions. Configuration disclosure is currently marked as not supplied; do not claim fully controlled comparisons without equivalent settings.

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
python3 tests/pi_integration.py
python3 tests/pi_no_turn_limit_integration.py
python3 tests/pi_stop_integration.py
```

Fixtures use a local fake provider, not a production model. They require local-port/sandbox permissions where applicable. Keep fixture settings in fixtures. Review the live report graph as well as the JSON.

Before pushing, verify the remote, branch and complete staged diff. Push reviewed source commits normally; do not force-push or publish scores as an incidental part of a source update. Check CI for the exact pushed commit and record its result in the handoff.

## Shutdown and dependency upgrades

On a requested stop, the wrapper terminates Pi and drains stdout/stderr with `communicate()` while awaiting exit. Waiting without draining can deadlock when an abort fills an output pipe. Interrupted output is retained in the benchmark workspace. The tests cover output larger than pipe capacity and native tool cancellation. The controller stops the benchmark process group, not the inference server.

Before upgrading frozen Pi, read `docs/frozen-pi.md`. Use a separately versioned snapshot, update its license/provenance and hash inventory, verify tools, unlimited turn behavior and shutdown, and preserve a rollback to the previous working snapshot. Do not patch model limits to make compatibility tests pass.

Rollback only when the affected component is idle. Restore the exact backed-up files, preserve unrelated work, and validate live behavior. A final handoff should list current run state, whether the next model can start, code commits and CI, backups, measurements, unresolved work and any approval block. Do not describe source-only changes as already active.

## Main-page charts

The selected run shows the same taller cumulative weighted-score graph as the publishing preview, refreshed every 30 seconds through the independent helper. The Results chart now uses four colored accuracy/token-efficiency quadrants: higher accuracy goes up, and fewer median output tokens per scored answer goes right. Dots are labeled by model; bubble area is proportional to scored answers per active minute. The legend retains machine, run, sample count, speed and status. Until the owner requests otherwise, both axes automatically fit the displayed data with padding, and each quadrant boundary bisects its displayed axis range. Accuracy stays within 0–100% and token counts stay nonnegative. The four colored regions are equal-sized; their numerical boundaries adapt to the data and are not pass/fail thresholds. All scored answers for a displayed run must have valid output-token counts. Missing counts are not treated as zero. Output tokens include reported reasoning, tool calls and final answers. Filtered question sets and tokenizers may differ, so this is descriptive rather than a controlled ranking.

## Recording hardware and exporting the bubble chart

Use **Record hardware** on the main run card or edit the hardware section in **Score preview**. Choose an existing physical machine or create a new identity, enter the machine label, CPU/chip, RAM in GiB, CPU core count and GPU details, then click **Save hardware & refresh preview**. This writes an owner-recorded per-run amendment with a timestamped backup; it does not alter the frozen manifest, model settings or inference server. Selected machine identity also controls which other model runs join the comparison. Hardware profiles for future runs remain a separate configuration.

Changing the form disables publishing until saved. A stale preview cannot overwrite a newer hardware record or publish outdated selected-run hardware. Unknown hardware must be recorded before publication. The exact reviewed hardware appears in report JSON and the README.

The sixth report file, `quadrants.svg`, includes the accuracy/token-efficiency/speed bubble chart and is embedded in the published README. Its aggregate data is included in `report.json` and `comparison.json`. Export uses all scored answers in the compatible runs, not temporary Results-page filters. Bubble area scales with scored answers per active minute, including the run's thinking/tool overhead; unknown timing has no speed value. The same-machine/bank/policy grouping and adaptive bisected axes remain in force. Partial runs are explicitly labeled. Scores and chart files are uploaded only by the explicit publish action.
