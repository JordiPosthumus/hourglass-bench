# Run names, hardware groups and historical records

Run names use the compact pattern `hardware-server/recipe-model-quant`, for example:

`DGXSP-BlazuxBF16KVC1-Qwen3.8-NVFP4`

The server/recipe field is free text: include meaningful settings such as cache precision and concurrency there. A separate server version is optional and appears in parentheses. The start review shows the saved configuration as a read-only summary. It has no duplicate naming inputs. Existing saved details include the backend and version recorded in an inference profile; use Run editor to correct labels. Missing components display `XXX`; they do not prevent a configured model from starting. Unknown quantization is not inferred from a model alias. Execution configuration checks still apply, and any start error appears inside the review dialog.

Use **Run editor** to edit the components or the complete generated name. **Reset to generated name** removes the override. Naming corrections apply to past and future runs with the same saved execution configuration and recorded hardware. Other reported settings retain their own per-run history. Original manifests, result rows and prior revisions remain intact.

Common hardware and quantization spellings are normalized. Display abbreviations include `DGXSP` and `M3Ultra512GB`. GB and GiB are not automatically converted or treated as equal. A hardware label alone does not establish that two runs used the same physical machine.

## Compare history and repeats

**All runs · all versions** includes historical runs even when the question bank changed. Same-bank and same-hardware filters remain available. Graph labels use run names without repeating hardware or scoring/deadline strings. Detailed rules remain in the run records and report data; showing history together does not make different banks equivalent.

Completed equivalent repeats appear as an arithmetic mean with the number of measurements. Equivalence requires the same execution configuration, hardware, full benchmark version, question bank/order/repeats, scoring, and timing rules. Live and partial runs stay individual. Mean curves average the recorded step values at every completion time; finalized scores remain flat through the end of the hour. Nothing is extrapolated from unfinished runs.

Expand an averaged row to inspect its members, or select **Every individual run**. Accuracy/token-efficiency plots retain individual observations. Public result snapshots continue to include the selected individual result, while comparison exports include the selected comparison view.

## Configure hardware for your installation

Record the inference machine in Model settings. An HTTP endpoint on localhost can be an SSH tunnel, so unconfigured loopback endpoints no longer silently inherit the controller's hardware. To explicitly capture this computer for a direct local endpoint, use `"inference_location": "local"` in that model's configuration or the endpoint hardware API's explicit local choice. Otherwise provide `hardware` or a saved endpoint profile. This changes metadata only; it does not change the inference request or server.

Open **Model settings → Hardware comparison groups** to give equivalent historical labels one canonical name. Each group has a name and a list of equivalent labels. You may intentionally group multiple interchangeable machines. Leave them separate when their differences matter. Aliases may belong to only one group, and edits are revision checked and backed up.

Groups are stored locally in ignored `hardware-groups.json`. A fresh GitHub checkout starts with no groups and no assumptions about the owner's machines. Original physical machine keys and labels remain in the run records; reports use the explicitly configured comparison group where present. Model configuration, task results and scores are not rewritten.

## Existing runs

Names and groups apply when existing runs are displayed. Existing free-text names are preserved as editable overrides and remain in revision history. Existing public snapshots remain unchanged until explicitly republished. Unknown historical versions or quantizations need a user-reported correction; the current server version is not proof of the version used earlier.

Review the backward display conversion without changing run records:

```sh
python3 migrate_run_names.py
```

Add `--audit` to save the preview under `backups/`. Each entry records the original manifest hash, canonical name, legacy label, missing/invalid fields, original machine key and comparison key. This command does not start a benchmark, query a model or publish anything.

## Question identity and randomized presentation (2.6.0)

New queued runs copy each complete task directory into private evaluation storage. Identity covers the task JSON, images, fixtures and hidden verifier files; referenced Git source trees also contribute. Each copy is verified before execution, and reviewed task/configuration revisions are checked when enqueuing. Model configuration remains frozen for the evaluation.

Option-ID questions use a fresh private evaluation seed and deterministic per-question/per-repeat permutations. Option IDs are reassigned after shuffling, with the answer key remapped internally. The seed and ID mapping are retained for audit and resume. The randomized presentation policy contributes to comparison identity; the random draw itself does not split otherwise equivalent cohorts. Numeric questions are not shown irrelevant letter choices.

Historical runs retain their existing hashes and scores. They are not relabeled as having complete bundle integrity or randomized presentation. A changed question bank or presentation policy creates a different comparison cohort. Do not compare the old and revised bank as though their conditions were identical.

## Isolation and its limits

Task tools cannot read the benchmark checkout, linked worktrees, answer bank, saved runs, diagnostics, or known assistant-history and diagnostic export locations. The OS applies this boundary to bash and the file-tool worker. Ordinary task file operations continue to work. Relaxed mode also blocks the configured benchmark HTTP port so its private state cannot be fetched over loopback; normal benchmark mode remains offline. Relaxed mode otherwise retains its existing network behavior and should not be used to establish offline benchmark comparability.

Keep all new raw exports and debugging material inside `runtime-diagnostics/` or `backups/`. The policy cannot recognize arbitrary copies that someone puts elsewhere or publishes on another service. Public reports deliberately contain aggregates only. Never publish the private task bank, traces, model configuration or migration audits.

Public installations choose their own publication repository in the preview. Set `HOURGLASS_REPORT_REPO` to supply an optional default.
