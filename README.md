# Hourglass Bench

**One hour. How much can your agent solve?**

Hourglass Bench is a local evaluation harness for tool-using AI models. Give each model the same private question bank and measure how many questions it answers correctly within **one hour of active wall time**.

## Bring your own questions

**Bring your own question bank.** This repository includes only a tiny, explicitly labeled [hello-world demo](examples/hello-world) to check your setup. No private benchmark questions, private answer keys, question images, datasets, or recorded model runs are included. There is no bundled 100-question test and no universal leaderboard.

Create your bank locally under `tasks/`. That directory, model configuration, results, logs, and backups are ignored by Git. See [the task format](docs/task-format.md). The automated tests use small software fixtures, not a benchmark question bank.

Scores are comparable only when models use the **same questions, order, repeat policy, harness and relevant execution settings**. A score from somebody else's private bank is not directly comparable with yours.

## What it measures

- 1–2 fixed difficulty points for each distinct question answered correctly within 3,600 active seconds, alongside the raw correct count.
- Thinking, tools, initialization, grading, and retries consume the time budget. Pauses between resumes do not.
- Wrong, unfinished, and unreached questions earn no points.
- Text and vision subtotals accompany the main score.
- At one hour, the harness stops the benchmark process group and plays a short system chime.
- Results preserve per-attempt timing, token usage, tool traces, model settings provenance, and question hashes.

Difficulty weights are versioned as `weighted-hour-v1`; the active-clock boundary remains `hour-v1`. See [scoring](docs/scoring.md) for boundaries, partial runs, and repeat behavior.

## Waves of questions

Regular questions cycle through **easy → medium → hard**, rotating subjects within each difficulty band. This gives the early part of a run a mixture of difficulty and subject matter. The order is fixed before the run and does not adapt to the model's answers.

The private version 2.2 reference evaluation adds a challenge after every four regular questions. The regular cycle continues across those insertions. Its 120-question bank remains private; the public runtime currently implements the regular waves.

All waves share the same one-hour clock, with no separate short per-question limit. Time spent reasoning and checking answers reduces the time available for later questions. Read [the method: waves of questions](docs/methodology.md) for the sequence, challenge cadence, scoring rationale and comparison limits.

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

The UI opens on a free loopback port, normally `http://127.0.0.1:8788`. Select your bank and model, use **one repeat** for the standard score, review, and start. Use `HOURGLASS_PORT=8790 ./start-hourglass.sh --no-open` for an explicit port.

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
