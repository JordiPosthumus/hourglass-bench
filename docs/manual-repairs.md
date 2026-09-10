# Manual repairs with retained evidence

Use **Repair this run** on a finished original run. Select the affected questions, review their recorded cost, and start only after loading the original model and configuring its server. The next repair never starts automatically. Active or queued work and an existing CLI run lock block repair creation.

The original evaluation, raw results and traces stay intact. A separate reconstructed evaluation retains unaffected results and their recorded time, replaces selected questions with newly measured work, then spends any remaining budget on the original question order. It stops at 3,600 reconstructed active seconds. This is labeled **Repaired run**, not an uninterrupted hour. Recorded affected-question time is an explicit reconstruction choice; it is not a measured causal estimate of time lost to the issue.

Repairs preserve the frozen model configuration, scoring rules, repeat policy and existing question deadlines. They require verified original task definitions, using the saved evaluation bundle or a matching archive in `backups/*/original-bank`. The current bank is not rewritten. The repair freezes its own full bundles and rejects changes after review. If the original version cannot be verified, repair creation fails before model work starts.

Trace or integrity-metadata exposure caveats preserve scores and identify the observed issue without inventing its timing impact. Repaired or caveated runs are excluded from ordinary repeat averages. Reconstructed hours cannot be calibration references. Clearing or resetting an original is blocked while linked repairs depend on it; clear the linked repair first using the backed-up application workflow.

Public reports include aggregate repair provenance and caveats, excluding question IDs, retained answer records, private traces and local backup paths. Publishing remains an explicit separate action.
