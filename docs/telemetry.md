# Server telemetry

Hourglass reads existing logs or metrics without sending extra inference requests or changing server settings. It retains timing, numeric request metadata and source labels, not raw metric payloads, prompts or session bodies. The UI distinguishes measured speed, the model's current tool phase, active requests and queued requests where available.

## Coverage

| Source type | Passive source | Speed measurement | Request overlap |
|---|---|---|---|
| `mtplx` | `/v1/mtplx/snapshot` | Per-request decode-token change divided by decode time; request average shown separately | Active and queued requests on that MTPLX server |
| `omlx` | `/admin/api/activity` | Per-request activity counters and request average | Active and waiting requests on that oMLX server |
| `lmstudio` | Existing server log directory | Timestamped decode windows and request average | Observed logged requests; ambiguous interleaving is marked |
| `vllm` | `/metrics` | Generated-token counter change per polling interval, filtered by model label when present | Reported running and waiting requests across the observed server |
| `sglang` | `/metrics` | Generated-token counter change per polling interval, filtered by model label when present | Reported running and queued requests across the observed server |
| `llamacpp` | `/slots` | Per-slot decoded-token change per polling interval, after generation starts | Active slots; this source does not report queue depth or identify the requesting client |
| `dsg` | Dashboard `/api/status`, with an explicit worker ID | The selected worker's reported speed | Gateway load/queue for that worker; direct traffic outside DSG may be absent |
| Legacy DS4 log entry | Existing SSH server log | Logged decode chunk speed and request average | Unavailable from this legacy format |
| `ollama` | No suitable passive live counter in its OpenAI API | Unavailable | Unavailable |

Counter throughput includes scheduling gaps and may arrive in batches. It is not interchangeable with pure decode speed. A first cumulative counter reading cannot establish a rate. Missing fields, stale data, inaccessible metrics and unknown model attribution remain unknown. Request counts describe the observed source, not all GPU applications, and overlap alone does not prove a slowdown.

The MTPLX adapter was validated against an active MTPLX endpoint. Other adapters have format, freshness and attribution tests; deployments and server versions still need an actual connection check. No adapter turns on disabled server metrics or changes authentication policies automatically.

## Configure a source

Merge entries into an ignored local `telemetry-sources.json`; preserve existing entries. Match the inference endpoint and actual backend. Example format:

```json
{
  "_endpoints": {
    "http://127.0.0.1:8001/v1": {"type": "mtplx"},
    "http://127.0.0.1:1234/v1": {
      "type": "lmstudio",
      "log_dir": "~/.lmstudio/server-logs"
    }
  }
}
```

`localhost` and `127.0.0.1` are matched at the same port. A top-level model-alias entry overrides the endpoint entry. The model ID comes from the run's frozen configuration. A saved direct inference profile can identify a supported backend automatically; the explicit registry also works without a profile. Use `metrics_model_id` when the metrics label differs from the OpenAI model ID.

For `vllm`, `sglang`, `omlx` or `llamacpp`, choose that source type on the relevant endpoint. If metrics live at another address, explicitly set `base_url` in that source. The inference credential is reused only for the same origin. A separate metrics origin requires its own explicitly configured credential, if needed. Redirects are rejected. oMLX may authenticate using its existing admin login and an in-memory session cookie; the collector does not change server configuration.

For DSG, use a model-alias entry containing `type: "dsg"`, the dashboard `base_url` and the exact `worker_id` used by the inference route. Route-aware installations can use `_routes[endpoint][route-name]`. Do not point a gateway run at a guessed backend or substitute a fleet-wide speed. A legacy DS4 entry uses `ssh_host` and `log_path`; it continues to use the existing log reader.

Future runs read the saved source. A compatible active run can receive the new HTTP or LM Studio collector without a controller or model restart:

```sh
python3 live_tps.py --root . --job RUN_ID
```

This observer exits when the run stops. A per-run file lock prevents duplicate HTTP/LM Studio writers. The legacy SSH collector is started with its run by the controller; the standalone attachment command does not support that legacy format.

## What the backend cannot supply

Ollama's native completion response can include `eval_count` and `eval_duration`, which support a completed-request average. Those fields do not supply passive live decode speed or concurrent request counts for the current OpenAI-compatible run. Hourglass therefore reports live telemetry as unavailable instead of estimating tokens from words, SSE chunks or loaded-model counts. See [Ollama token usage](https://docs.ollama.com/api/usage).

The counter adapters follow the documented [vLLM metrics](https://docs.vllm.ai/en/latest/design/metrics/), [SGLang production metrics](https://docs.sglang.io/docs/references/production_metrics) and [llama.cpp server slots](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). Server upgrades can change these interfaces; verify a real active reading for your installation.
