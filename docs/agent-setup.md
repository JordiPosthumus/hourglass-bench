# Agent setup recipe

For Hourglass 3.0.0, also read [inference profiles](inference-profiles.md) and [Issue for Agents](issues-for-agents.md). New configurations use native Pi model declarations. Record the actual backend/build, context and output capacities, optional thinking choice and any required route. The example is a format reference; verify its fields before using it. Preserve existing historical profiles unless the owner authorizes migration.

Use a coding agent to perform this checklist in order. Your setup agent installs and configures Hourglass. The model being evaluated runs through the frozen Pi harness; it does not inherit your setup agent's context or tools.

## 1. Inspect before changing anything

Read the repository README, maintenance guide and any owner instructions. Confirm macOS on Apple Silicon, Python 3.10+, Node.js 22.19+ and Git. Inspect an existing checkout before cloning another. Read its Git status and preserve local edits.

Identify the intended model server, base URL, loaded model ID, authentication mechanism, supported context and output limits, and hardware. Read the server's existing configuration and reported metadata. Never infer a capacity from a model alias or substitute the example file's numbers. Record unresolved settings as unknown and ask only for information needed to make the connection work.

Preserve established model files, launchers, context/output capacity, reasoning, sampling, concurrency, kernels, quantization and cache settings. Make a timestamped backup before changing a local configuration. Do not restart a busy model server or change its settings merely to install Hourglass.

## 2. Configure one endpoint

For a fresh install, clone this repository. Use `models.example.json` as a format reference. Create `models.json` only if absent; otherwise merge one reviewed entry and retain all other fields and entries. The example API key is a placeholder. Keep real credentials in the ignored local configuration and out of terminal output, screenshots and commits.

Alternatively, launch Hourglass and use **Model settings → Add a server model → Inspect endpoint**. This reads reported metadata without generating an answer. **Add from LM Studio** inspects downloaded and loaded variants through the local `lms` CLI. These discovery controls do not load, unload or reconfigure models. The endpoint form does not configure authentication credentials; use the local configuration when needed.

Set the actual `base_url`, `model` and explicit output capacity. Set an accurate `context_window` when runtime metadata cannot supply it. Preserve additional existing fields, including a configured `response_mode`. Temperature is delegated to the server in the default configuration. Do not claim an effective setting has been verified merely because JSON parses.

## 3. Check the public demo

Install the optional fixture:

```sh
python3 scripts/install_demo.py
python3 hourglass.py cert hello-world
```

The installer refuses to overwrite an existing demo. Certification should report that the clean calculator passes and the deliberately broken version fails. It does not prove model compatibility.

Launch `./start-hourglass.sh` from the owner's Terminal and leave it open. Use the UI's connection check, then run the **hello-world question only**, with the chosen model and one repeat. This small run is an installation test. Verify a real tool call, a final submission and a saved result, and inspect any reported request or harness error. It uses inference and writes local diagnostic artifacts.

Do not upgrade or regenerate the vendored Pi snapshot during setup. If its integrity check fails, inspect the mismatch and restore the expected release snapshot without overwriting unrelated user work. See [frozen Pi](frozen-pi.md).

## 4. Add your private bank

Follow [the question-authoring recipe](question-authoring-recipe.md). A setup demo does not establish benchmark quality. Keep private material in the ignored bank and audit locations, and register external private backups as explained in [private question versioning](private-question-bank.md) so that attempts cannot read them.

Remove the demo from the timed question selection. Confirm every selected question is ready. Use one repeat, check the frozen order and question count, and record the exact model/server/hardware setup. Start the full evaluation through the UI; an individual `hourglass.py run` invocation does not enforce the evaluation hour.

## 5. Connect telemetry and hand back a verified installation

Use [server telemetry](telemetry.md) to select a passive source for the actual endpoint. Merge its ignored configuration. Verify measured speed and request counts while inference is active when the backend exposes them. Label missing telemetry as unavailable, and state its scope. Never infer tokens from text length, streaming chunks or loaded-model counts.

Give the owner the checkout path, start/stop commands, local UI address, configured model alias, exact configuration changes and backup locations. Report the demo's result and where its local evidence lives. Distinguish observed effective settings from user-reported or unknown values. Explain how to select their bank and begin a one-hour run.

Before any public commit, inspect the staged diff and run `python3 scripts/check_public_release.py`. Do not publish local configurations, bank files, traces, private question screenshots or private audit records.
