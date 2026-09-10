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

## Score curves and AUC

The graph stays flat between completions and steps up when points are earned. The AUC companion integrates this exact step function. Its version is `weighted-step-auc-v1`.

`AUC (weighted point-minutes) = integral(score(t), t=0..60 active minutes)`

There is no assumed maximum score. Raw AUC is uncapped. Dividing AUC by 60 gives the mean weighted score during the hour, also uncapped.

AUC rewards solving questions earlier. It remains a companion to the primary score (weighted points after one hour), because it adds an extra preference for early throughput and question order. An official full-hour AUC is withheld for partial runs; accumulated raw area remains in the data. If every planned question has already finished, the earned score is fixed for the rest of the hour.

Reference models do not currently set this scale. Any future scale based on pinned models should freeze the reference runs, bank, protocol and calibration revision; adding or changing a reference must not silently rewrite old reported scores. Raw score and raw AUC should always remain available.
