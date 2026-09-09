# Model-facing prompt contract

Version 2.5.0 restores the question wrapper and simple final-answer schema used before the v2.4.0 scoring-prompt addition. Scoring is performed by the benchmark, without instructions to the model about rewards, penalties or abstention.

The unchanged, frozen Pi 0.85.1 harness supplies its standard system prompt and workspace tool definitions. It is configured without project context files, skills, external extensions or prompt templates. The benchmark appends exactly:

> Work on exactly this benchmark question. Use the workspace tools as needed. Network access is unavailable. Finish by calling answer_question.

Code-repair questions use `submit` instead of `answer_question`. The user message contains the question, its answer choices when applicable, and `Call answer_question when finished.` (or `submit`). Question images are attached when present. The final tool requires the existing answer field: `option`, `answer`, `value`, or `summary`, depending on question type. It has no abstention field under the new policy.

These are question-delivery instructions, not scoring strategy. The underlying native Pi prompt, tool access, reasoning defaults and configured context/output capacities are preserved. Historical `net-hour-v1` runs keep their recorded behavior and are not relabeled as new-policy runs.

Integration validation uses the real frozen Pi with a synthetic endpoint, checks the absence of score/abstention instructions, exercises workspace tools, verifies answer submission and retains the 262,144-token context/output fixture settings.
