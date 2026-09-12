# Recording model improvements

I use private questions for my Hourglass Bench evaluations. Public reports disclose aggregate measurements and explicitly recorded experiment labels, not question text, answers, images or model traces. Scores from different private banks are not interchangeable.

## Record a run

1. Run the benchmark with your chosen model configuration and record the inference hardware.
2. Open **Score preview**. Under **Public experiment labels**, give related releases the same **Model family** (for example `Qwen Flash`).
3. Record **Model revision** (release, weights revision or commit), **Configuration** (a short distinguishing name), **Quantization**, **Inference engine**, **Harness revision**, and **Parameters**. These are user-reported public labels; they do not change server settings. Keep credentials and private text out of these fields.
4. Save the labels, inspect the report and charts, then publish to your GitHub repository.

Use the configuration label to distinguish experiments such as `Q2 baseline`, `Q4 updated engine`, or `temperature 0.6`. Unknown fields stay unrecorded. A report date is the evaluation start date, not its publication date.

## Repository layout

- `reports/<snapshot>/`: immutable reviewed report, configuration labels and comparison charts.
- `reports/catalog.json`: aggregate catalog, one entry per evaluation. Republishing a run updates its catalog entry while retaining its previous snapshot folder.
- `reports/README.md`: human-readable Results index, run tables and model-family histories.
- `reports/models/<family-hash>.svg`: a series of dated score charts for each model family.

The publisher updates the snapshot, catalog and charts in one non-forced Git commit. Existing published runs survive clearing local history. It reads the catalog at the current branch head and refuses publication if it cannot safely read it; a concurrent branch update requires retrying.

## Fair comparisons

History panels separate question-bank fingerprints, difficulty scoring, time policy, benchmark versions, repeat/stop policy and hardware. Record a changed agent harness explicitly; treat it as a configuration change, not evidence of model-only improvement. Full protocol changes produce separate panels. Partial snapshots remain visible in separate panels, without a connecting improvement line or extrapolation. Adjusted clocks remain disclosed in the aggregate catalog.

The x-axis orders dated evaluations; numbered points map to the configuration rows. Results can improve or regress. Run multiple repetitions to assess variability before attributing a change to a model revision or setting. A faster inference engine, different quantization, hardware contention and stochastic sampling can all affect the result.

The JSON catalog supports future views such as per-configuration histories, speed versus accuracy, or confidence intervals without changing the private question bank or losing previous runs. The catalog intentionally does not contain task identifiers or raw inference settings scraped from an endpoint.

## Hourglass score

Current metric: `total-points-v1`. The score is the running total of awards minus penalties, not an area or forecast. Under `net-hour-v3`, every new-round attempt is scored independently; a later correct answer does not erase an earlier wrong-answer penalty.

The points-over-time graph remains a step chart of recorded submissions. Timing affects how many attempts fit inside the hour, not the value of earlier versus later points. Archived runs are omitted from normal local comparisons but remain viewable and restorable. Already published snapshots remain unchanged.

Historical evaluations keep their original execution and once-per-question award rules. New reports identify their recorded policy; reports from different policies are not averaged. Previously published metric versions remain in their separate history cohorts.
