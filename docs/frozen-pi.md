# Frozen Pi harness

Hourglass is built on [Pi](https://github.com/earendil-works/pi), created by **Mario Zechner and the Pi contributors**. The bundled coding-agent SDK is version **0.85.1** ([upstream release source](https://github.com/earendil-works/pi/tree/v0.85.1/packages/coding-agent)). Pi is MIT licensed; its [license](../licenses/pi-MIT.txt) and [third-party notices](../THIRD_PARTY_NOTICES.md) are retained.

## Responsibilities

| Component | Responsibility |
|---|---|
| Your setup agent | Installs Hourglass, configures an endpoint and helps author your private bank |
| Pi coding-agent SDK | Runs the evaluated model's agent loop, file tools, bash and context compaction |
| Hourglass adapter | Supplies the question and final-answer tools, constrains workspace access and records execution evidence |
| Hourglass controller | Freezes the evaluation, schedules questions, enforces the active-time budget and saves results |
| Hourglass grader and UI | Grade submissions, show evidence and compare compatible runs |

The evaluated model receives the benchmark's prompt and tools through Pi. It does not run inside whichever coding-agent product helped you set up Hourglass.

## Native session baseline in 3.0.0

Hourglass 3.0.0 introduces the `pi-native-v1` baseline. Model declarations use Pi’s native compatibility and sampling fields. `pi_thinking_level` is an ordinary Pi session choice, checked against the model’s declared capabilities. Existing Qwen configurations retain xhigh; no extension forces a different request effort. Pi owns output sizing: its model output ceiling is clamped to estimated remaining context with Pi’s built-in 4,096-token margin. This is an estimate, not the server tokenizer; exact acceptance still requires a live backend check.

Native sessions use Pi’s default automatic compaction (16,384 reserved tokens; 20,000 recent tokens retained), retries (three retries, 2,000 ms base delay), and 300,000 ms HTTP idle timeout. The benchmark’s 15-minute question and one-hour run boundaries still apply. A model-requested bash timeout is respected. Personal Pi packages, extensions and settings are isolated from Hourglass.

`python3 tests/pi_native_integration.py` compares entire serialized request bodies with a plain pinned-Pi SDK session and exercises tool continuation, native MTPLX thinking fields, transient retries, and automatic compaction retaining xhigh. Native request capture includes compaction and retry requests. `tests/test_stock_pi.py` checks migration preservation and safe configuration handoff.

Historical unmarked and `explicit-v1` profiles retain their saved serialization and timeout behavior. Their results remain separate from native profiles. See [inference profiles](inference-profiles.md) and [server specifics](server-specifics-guide.md).

## Reproducibility

The vendored dependency snapshot and per-file SHA-256 manifest are checked before each attempt. The local adapter is `harness/pi.mjs`. A global Pi installation is neither required nor modified. The full snapshot is intentionally committed so future package resolution does not silently change an experiment. Its Darwin ARM64 binaries currently constrain the supported installation platform.

Leave the frozen dependency snapshot alone during normal setup and model experiments. An intentional Pi upgrade is a harness release: preserve the previous snapshot, update integrity metadata, exercise the integration and isolation checks, record the change and assess comparison compatibility. A passing hash check proves the expected files are present; it does not establish that a model's tool calling or reasoning works correctly.

First-party code has its own MIT license. Credit for Pi's capabilities belongs to its authors; Hourglass adds the evaluation method and surrounding application.
