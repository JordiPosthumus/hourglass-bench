# Recording model improvements

I use private questions for my Hourglass evaluations. Public reports disclose aggregate measurements and explicitly recorded experiment labels, not question text, answers, images or model traces. Scores from different private banks are not interchangeable.

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

The headline metric is `linear-auc-100-v1`. Let W be the sum of the frozen question weights (one award per question, regardless of repeats). Let S(t) be accumulated net points after each final submission, with t measured in active minutes.

`Hourglass score = integral(S(t), t=0..60) / (0.3 × W)`

A reference machine earns weighted points continuously and linearly from zero to W over sixty minutes. Its triangular area is 30 × W, giving a score of exactly 100. This is linear **weighted-point progress**, not necessarily one question every equal interval. Real runs retain their exact step curves, without interpolation between answers.

Hourglass measures correct work and how soon it becomes available. Faster models remain distinguishable even when they solve the entire bank. A faster, less accurate run can outscore a slower, more accurate run; early mistakes also reduce the area for longer. Fixed bank, order, scoring rules, hardware and execution conditions matter. Normalization does not make different banks equally difficult or directly comparable.

100 is a reference, not a percentage or ceiling. Instant perfect completion would score 200. Negative net curves can produce negative scores. Once every planned attempt has finished, the final net points carry through the remainder of the hour. Live/partial scores contain only area accumulated so far, using the same full-hour denominator; they are labelled and never extrapolated. Unreliable clocks or reset results withhold the score. Pauses contribute no area; resumed attempts retain time already spent.

Raw weighted points, counts and `weighted-step-auc-v1` AUC stay in the data for audit. The UI and ranking use one headline Hourglass score. Reports save the metric version, total available points and denominator. Legacy published snapshots remain unchanged; missing normalized scores are not replaced with raw points or guessed denominators. Equivalent-repeat averages include the metric version and bank total in their grouping.

## Live prediction

The run panel shows **Predicted final Hourglass Score** after at least one correct or incorrect answer while the one-hour result is unfinished. For a paused/interrupted run, the label explains that the estimate assumes resuming. Before the first answer it shows the measured score with a waiting note; a final run shows **Hourglass Score**. All displays use one decimal.

This is a display-only forecast. Average active time per resolved question estimates future completion intervals. Observed correct and incorrect fractions estimate rewards, using the remaining questions’ total weight; timeouts and unsupported questions contribute zero reward while counting toward observed pace. Predicted submissions are evenly spaced steps, stop when the bank is exhausted, and only earn area through the sixty-minute deadline. Existing measured area is retained. The forecast is uncertain, especially after one question, and later difficulty or server speed can change it.

Rankings, exports and published scores remain measured AUC; no prediction replaces a saved result. The toolbar keeps New run, Resume/Stop, Run editor and Clear run. Duplicate record/publish shortcuts and repair/reset controls are removed. Logs remain available in Run activity. Run editor contains hardware and sampling details; older server-settings records remain readable there. Publishing uses its dedicated tab and the selected run.
