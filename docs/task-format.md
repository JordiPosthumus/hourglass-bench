# Bring your own questions

This repository ships only an optional hello-world setup demo, not a benchmark bank. Store each locally authored task at `tasks/<id>/task.json`. The task's `id` must match its directory. Never place answers or private verifier files in the model-visible `files` or `assets` fields.

The [JSON Schema](../schemas/task.schema.json) documents the multiple-choice and numeric task shapes without supplying any question content.

## Core fields

| Field | Meaning |
|---|---|
| `id` | Local unique task identifier, matching its directory |
| `kind` | `mcq` for option-ID or numeric questions |
| `title` | Human-readable title you supply |
| `prompt` | Your actual question text |
| `section`, `family` | Labels for ordering and coverage |
| `tier` | Numeric authored difficulty; not an empirical difficulty claim |
| `repeat` | Default repeats; use 1 for the standard timed evaluation |
| `max_turns` | Historical metadata only; ignored by the current harness |
| `files` | Mapping of relative paths to model-visible text file contents |
| `assets` | Relative local asset paths to copy into the agent workspace |

## Multiple choice

Use `kind: "mcq"`, `mode: "option_id"`, an `options` array of distinct `{id, text}` objects, and an `answer` equal to the correct option ID. Use three-digit numeric option IDs. The agent submits its choice with `answer_question`. Optional `shuffle: true` changes display order deterministically while preserving option IDs.

The answer key stays in the host task definition and is not included in the model's question prompt. You are responsible for authoring and validating a single correct answer.

## Numeric

Use `kind: "mcq"`, `mode: "numeric"`, a finite numeric `target`, and a non-negative `tolerance_abs`. A submitted value is correct when its absolute error is at most the tolerance. Options are not required.

## Images

Place your own image files inside the task directory and list their relative names in `assets`. The harness sends supported image assets with the question. The live viewer serves only declared image assets dynamically; no generated static question archive is needed or committed.

## Code tasks

The runner also supports local code-repair tasks using `kind: "fix"`, a `source` repository/ref or embedded `files`, optional `mutation`, and a `verifier` command. Private verifier files belong under the task's `verify/` directory. The schema in this release covers the simpler MCQ/numeric forms; inspect `build`, `verify`, and `cmd_generate` in `hourglass.py` for the code-task contract before authoring this form.

## Keep your bank private

`tasks/`, imported banks, image caches, results, evaluations, sandboxes, logs, and backups are ignored by Git. Ignore rules are not a substitute for inspecting staged changes: do not force-add private files. Run `python3 scripts/check_public_release.py` before publishing a fork.
