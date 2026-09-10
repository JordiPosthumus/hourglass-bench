# Create a private question bank with your agent

Start with 12 well-checked questions, then expand. A useful bank reflects your work, has independently defensible answers and stays fixed during a model comparison. Twenty plausible options can make a multiple-choice question demanding; twenty arbitrary options make it noisy.

## Ideas

| Work you care about | Material to prepare | Question to ask |
|---|---|---|
| Repository handoffs | A small frozen repository and a synthetic conversation | Which complete proposal satisfies the owner's latest request and the existing constraints? |
| Debugging | Synthetic logs, relevant code and a reproducible failure | Which root cause explains every observation? |
| Data interpretation | A generated chart plus precise units and definitions | Which conclusion or numerical result follows? |
| Conflicting requirements | Versioned specifications and dated decisions | Which implementation respects the authoritative requirements? |
| Calculations | Synthetic invoices, resource tables or schedules | What exact total, allocation or feasible outcome follows? |
| Code repair | A small fixture with one intentional fault and hidden behavioral checks | Repair the behavior and submit the change. |

Use synthetic data or material you own and may send to your configured model endpoint. Remove personal details, credentials, private customer data and unnecessary history. A repository snapshot needs the relevant evidence, not unrelated home-directory files or a live `.git` checkout containing secrets.

## Exact recipe

1. **Write the blueprint.** Create an ignored `backups/question-authoring/<bank-version>/` audit folder. Define the intended skill, sources, allowed tools, answer form, coverage and acceptance criteria for each question. Plan a mixture of difficulty and subjects. Treat initial difficulty labels as hypotheses.
2. **Freeze the evidence.** Copy only required source files into a staging folder under that private audit directory. Record source revisions or generation seeds and SHA-256 hashes. Synthetic conversations should be clearly identified in the private audit. Preserve source licenses. Each question must be answerable using the files and prompt it actually supplies.
3. **Establish the answer before writing distractors.** Solve the problem explicitly and save the derivation outside the model-visible task files. Check it by an independent method: a separate calculation, executable invariant, second implementation or a fresh reviewer that derives the result before seeing the proposed key. For judgment questions, state the decisive criteria and demonstrate why exactly one proposal meets all of them. Rewrite or reject an ambiguous question.
4. **Write the prompt and files.** State the objective, units, rounding, scope and any tie-break rule. Give all necessary context. For an MCQ, use `kind: "mcq"` and `mode: "option_id"`; for a numerical answer, use `kind: "mcq"`, `mode: "numeric"`, a finite `target` and an explicit non-negative `tolerance_abs`. See [the task format](task-format.md).
5. **Construct plausible alternatives.** For a twenty-option MCQ, use original IDs `001` through `020`, one correct option and nineteen distinct alternatives. Give each wrong option a specific, plausible mistake, such as omitting a constraint, using the wrong units or fixing a symptom. Keep style and length reasonably balanced. Record why each alternative fails in the private audit. Avoid overlapping choices, duplicate meanings, obvious joke answers, “all of the above” and an answer that stands out through wording. Use fewer options or a numeric answer when twenty distinct alternatives cannot be justified.
6. **Separate public inputs from the key.** Keep `answer`, `target`, the derivation, private audit and grader files out of `files`, `assets`, previews and source archives supplied to the model. Hidden code verifiers belong under `verify/`, not in embedded workspace files. Inspect filenames, comments, metadata and generated images for accidental answer clues. The task definition holds the key on the host; the harness constructs the model-visible prompt separately.
7. **Validate the contract.** Put the finished task at `tasks/<id>/task.json`, with a matching `id`. Run `python3 hourglass.py cert <id>` for every MCQ/numeric task. This checks shape and answer mapping only; it does **not** validate source truth, uniqueness or difficulty. For code-repair tasks, certification must visibly show that the clean source passes and the intentional fault fails. Exercise hidden checks against plausible wrong repairs too; `cert` currently reports code-task failure in its output, so inspect the result rather than trusting exit status alone.
8. **Do a blind solve.** Use a fresh solver context that receives only the exact prompt and workspace files. Keep the answer, author notes and earlier feedback inaccessible. Obtain its answer and reasoning before comparing with the key. Investigate disagreements using the frozen evidence; never change a key merely to match the solver. Save the review and any correction history privately. Self-consistency from the author model is not independent validation.
9. **Exercise the real runner.** Run a small pilot through Hourglass with one repeat. Confirm files and images are delivered, the final-answer tool works, displayed option IDs match the recorded presentation, and grading maps shuffled IDs correctly. The current policy gives each new run a fresh private seed and a derived layout per question/repeat. Resuming preserves that layout. Keep original authoring IDs in the bank; do not manually rewrite keys to match a run's displayed IDs.
10. **Freeze a bank release.** Record the final question and asset hashes, source provenance, audit conclusions, selected order, repeats, harness version and scoring policy. Keep this in a separate private Git repository and verify a restorable backup using [the bank backup workflow](private-question-bank.md). Do not edit questions mid-comparison. A correction creates a new bank release; retain the earlier evidence and identify affected runs.
11. **Separate pilots from evaluation.** Retire exposed pilot material from a holdout intended to measure unseen performance. Compare models using the same released bank and relevant execution conditions. Do not tune questions to make a preferred model win. Record errors and timeouts separately from submitted wrong answers.
12. **Review evidence before expanding.** Review correctness, ambiguity, coverage, solving time and repeated failure modes. The runtime stores attempts and timing, but a durable per-question evidence ledger surviving all run deletion is not implemented. Archive the evidence you need privately. Do not claim calibrated difficulty or silently change score weights from a small pilot.

## Copy this instruction to your agent

```text
Create a private 12-question Hourglass pilot using the repository's
README.md, docs/question-authoring-recipe.md, docs/task-format.md and
schemas/task.schema.json. Follow all twelve recipe steps in order.

Begin with a written coverage blueprint using synthetic material or files
I explicitly identify as suitable. Use varied topics and difficulty. Prefer
multiple-choice questions with twenty distinct plausible options only when
exactly one answer can be defended; otherwise use an appropriate numeric
form or a smaller option set. Use an independent derivation/check for every
answer and record why every distractor is wrong.

Stage sources, answer derivations, reviewer notes and hashes privately under
backups/question-authoring/. Final task directories go under tasks/. Keep
keys, verifier files, audit material and private metadata out of all files,
assets and previews given to the model. Inspect for accidental clues.

Run cert for each applicable task and inspect its actual output. Arrange a
blind solve with a fresh context receiving only model-visible inputs. Run a
small pilot through the frozen Pi harness, verify option-ID mapping, and
investigate disagreements. Do not call schema validation truth certification.

Preserve my current bank, running evaluations, model settings and launchers.
Create a versioned private bank snapshot and a verified backup. Deliver the
coverage table, per-question validation evidence, unresolved issues and
exact steps to start a comparable one-repeat timed evaluation. Publish no
private questions, keys, source bundles, traces or audit files to GitHub.
```

If an independent reviewer or solver is unavailable, report that step as pending. Keep the bank a draft until its agreed acceptance criteria are met.
