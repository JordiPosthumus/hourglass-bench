# The Hourglass workspace

Every new benchmark uses the complete installed question bank in the order defined by the benchmark rules. The Questions view is for inspection, not run selection. Searching, filtering and sorting it never changes what a run executes.

## Runs and Archived runs

**New run**, beside the saved-run picker, opens a right-side setup drawer. Closing it with Close, Escape or the backdrop preserves the current draft while the page remains open. The model and connection check stay visible; endpoint, hardware, inference details and benchmark rules are expandable. Review opens a confirmation dialog, and a successful start closes setup and focuses the queued run. With no saved runs, setup appears inline instead. The fixed bank is summarized by its question count, without sample question IDs.

Runs opens the current run and its recorded comparisons. The chart tabs offer points over time, score ranking, accuracy and efficiency, live throughput, and speed comparison. Graph labels use the run name without repeating its hardware or adding scoring-policy and deadline strings. Detailed execution metadata remains in the run record and report data.

Archive moves an idle run out of ordinary results and comparisons. Archived runs provides the restore action. Archiving does not delete answers, settings, logs or artifacts.

## Questions

Open **Questions** beside Runs and Archived runs. Click a title or **View** to inspect the prompt, answer options and public workspace files. Previews do not expose the answer key.

Click a column heading to sort; click again to reverse the direction. The arrow and accessible sort state identify the active column. **Restore bank order** returns the table to its default presentation. A model filter narrows the evidence without changing the bank.

| Column | Meaning |
|---|---|
| Tier | Authored or explicitly estimated scheduling tier; not a measured difficulty claim. |
| Points | Current authored reward for a correct answer. |
| Average answer time | Mean recorded duration of correct and wrong final answers with valid timing; excludes timeouts and execution errors. |
| Wrong answers | Wrong answers divided by answered attempts. |
| Timeouts | Timed-out attempts divided by counted attempts. |
| Errors | Execution-error attempts divided by counted attempts. |
| Attempts | Counted attempts in the matching saved-run evidence. |

Statistics include saved and archived runs matching the current question revision. Complete bundle hashes are preferred; legacy rows can match the task-JSON hash when no bundle hash was recorded. Unknown or mismatched revisions, standalone probes, inherited repair copies, unsupported-vision skips, abstentions and unattempted questions are excluded. Duplicate physical attempt records count once.

Sample counts accompany the rates and average. A dash means unavailable, not zero. Missing values sort last in either direction. These are pooled observations, not controlled cross-model comparisons: model settings, hardware and historical execution conditions may differ. The filter and counts help distinguish a useful pattern from sparse evidence.

## Start a benchmark

Choose a saved model and review the full bank. The server rejects subset requests, checks reviewed question revisions and derives execution order from the bank rather than browser order. If any installed question needs repair, resolve it before starting; Hourglass does not silently drop it. The first pass follows the deterministic scheduling rules; subsequent whole-bank rounds follow the recorded outcome-and-duration ordering within the original hour.

New targeted repair runs are disabled. Historical runs and repair evidence remain readable; resumes retain the saved evaluation's bank and clock. A fresh run always uses the full current bank.
