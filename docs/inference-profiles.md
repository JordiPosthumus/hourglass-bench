# Inference profiles

New profiles use `pi-native-v1` in Hourglass 3.0.0. Pi receives a model declaration, an optional selected thinking level, and its normal session defaults. The model output and context capacities remain explicit; Pi calculates the output allowance per request. Sampling is declared in `pi_model.samplingParams`; reasoning/output payload overrides are rejected. Qwen migrations retain their xhigh selection and declared thinking levels, sampling values, capacities, routes, credentials and complete prior profile provenance. Historical evaluation snapshots are never migrated. Native handoffs contain a normal Pi model definition and the selected thinking level, without a payload-rewriting extension.

## Historical explicit profiles

Earlier reviewed profiles use `explicit-v1`. Existing unmarked profiles, exact copies and historical runs remain grandfathered, including their original request behavior. Converting a legacy copy is an explicit editor choice.

Pull from an explicitly selected Hugging Face publisher repository without choosing a thinking mode first. One download pins the source and prepares mode-specific proposals (Thinking and Non-thinking for Qwen3.8). Use the compact mode selector to review one proposal, then accept it to select the mode and populate the draft. Source details retain all candidate values. Recognized mode-specific model-card recommendations take precedence over general generation defaults; older saved sources are unchanged. You can compare or switch proposals without downloading again. Unsupported model-card formats are clearly marked for manual review; their mode support is not inferred. Resolve conflicts and select backend/build, connection, context capacity and output-budget behavior before saving. Pull/Refresh is the only network operation; validation, Start and resume use saved settings. A pull never rewrites a saved run.

Accepting a different proposal clears previously imported values absent from the new mode only when they are still equal to the previous suggestions. Edited values and unrelated manual settings are retained and remain subject to validation. Stored source records and explicit-lane API callers keep their existing format.

The importer pins one commit and records file hashes, retrieval time, parser version, candidates and reviewed choices. Unsupported prose requires manual review. Greedy `do_sample=false` configuration requires a manual profile because this adapter does not translate it. Custom values retain the original recommendations. Missing or unsupported request controls block new explicit profiles. MTPLX’s min-p, repetition penalty and thinking-history preservation can instead be explicitly recorded under `server_managed` when accepting a proposal: they are not sent or claimed as applied, their publisher recommendations remain in the source record, and their effective server values are unknown. This does not change MTPLX or DSG settings. Manually entered unsupported values still fail validation; thinking enablement and effort cannot be delegated this way.

## Request mappings

These are request API mappings, not proof of effective server/kernel values. The entered build is owner supplied; Hourglass does not discover or configure servers. Model templates must implement the named thinking controls.

| Backend | Canonical → wire mapping | Evidence and limits |
|---|---|---|
| DS4 | `temperature`, `top_p`, `top_k`, `min_p`, `seed`, `reasoning_effort`, `enable_thinking` → `thinking` | [API source](https://github.com/antirez/ds4/blob/21e98c129ce20ebb9e5d2de1a1bbf5f991d3795d/ds4_server.c). DS4 request parser at 21e98c1. Only none/high/max have distinct effort semantics. Think Max requires at least 384K context. Penalties and preserved-thinking control are not mapped. |
| oMLX | `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`, `seed`, `top_k`, `min_p`, `repetition_penalty`, `enable_thinking` → `chat_template_kwargs.enable_thinking`, `preserve_thinking` → `chat_template_kwargs.preserve_thinking`, `reasoning_effort` → `chat_template_kwargs.reasoning_effort` | [API source](https://github.com/jundot/omlx/blob/94530d8d49541ede9e99ef04a4431ee4953117a6/omlx/api/openai_models.py). API at 94530d8. The model template must support these thinking controls. Server force_sampling or forced template keys can override requests; server configuration remains the backend owner’s responsibility. |
| vLLM | `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`, `seed`, `top_k`, `min_p`, `repetition_penalty`, `enable_thinking` → `chat_template_kwargs.enable_thinking`, `preserve_thinking` → `chat_template_kwargs.preserve_thinking`, `reasoning_effort` → `chat_template_kwargs.reasoning_effort` | [API source](https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/openai/chat_completion/protocol.py). Chat-completions schema checked 2026-09-10. Thinking controls require the matching model chat template; use the deployed version, not generic OpenAI compatibility, to assess support. |
| SGLang | `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`, `seed`, `top_k`, `min_p`, `repetition_penalty`, `enable_thinking` → `chat_template_kwargs.enable_thinking`, `preserve_thinking` → `chat_template_kwargs.preserve_thinking`, `reasoning_effort` → `chat_template_kwargs.reasoning_effort` | [API source](https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/entrypoints/openai/protocol.py). Chat-completions schema checked 2026-09-10. Thinking controls require the matching model chat template; harmony models have different reasoning behavior. |
| MTPLX | `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`, `seed`, `top_k`, `enable_thinking` → `chat_template_kwargs.enable_thinking`, `reasoning_effort` | [API source](https://github.com/youssofal/MTPLX/blob/21be78b3f51820eecef020e5e4855c0715eaf9a5/mtplx/server/openai.py). Request parser at 21be78b. Fields outside this mapping need a verified adapter before an explicit lane can use them. |
| LM Studio | `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`, `seed`, `top_k`, `repetition_penalty` → `repeat_penalty` | [API source](https://lmstudio.ai/docs/developer/openai-compat/chat-completions). Documented /v1/chat/completions fields checked 2026-09-10. Native /api/v1/chat parameters are a different API. Unverified thinking/min-p extensions are not mapped. |
| llama.cpp | `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`, `seed`, `top_k`, `min_p`, `repetition_penalty` → `repeat_penalty`, `enable_thinking` → `chat_template_kwargs.enable_thinking`, `preserve_thinking` → `chat_template_kwargs.preserve_thinking`, `reasoning_effort` → `chat_template_kwargs.reasoning_effort` | [API source](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). Server API checked 2026-09-10. Thinking/history kwargs need a compatible Jinja template. Repetition uses repeat_penalty, not repetition_penalty. |
| Ollama | `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`, `seed`, `reasoning_effort`; thinking off → `reasoning_effort=none`, on → chosen effort | [API source](https://docs.ollama.com/api/openai-compatibility). OpenAI-compatible chat API checked 2026-09-10. Native options such as top_k are not advertised on this API. Reasoning effort depends on the served model. |

All mappings send `max_tokens` for an explicit combined output limit, or deliberately omit output-limit fields for server-controlled output. Recorded context capacity is a constraint, not a server mutation. DSG uses `x-dsg-model`; the configured route must already select the intended backend.

## Importer coverage checked 2026-09-10

Qwen3.8 imports the named thinking/non-thinking Best Practices sampling controls plus documented thinking/history defaults. Recognized mode-specific temperature/top-p values take precedence over general generation defaults; equal-priority conflicts still require review. DeepSeek-V4 imports temperature/top-p; mode and effort remain explicit owner choices. Think Max requires recorded context of at least 384K. Unknown publishers support structured generation values only; arbitrary model-card prose is not automatically interpreted.

- `Qwen/Qwen3.8-Flash-Next` revision `de4b8e4d43b917e7706784d8bb445c9af86a3540`.
  generation_config.json SHA-256: `e70c136c1b78ddc1fb0905bac8e733a4dc448d4f852a5dd75143fffc70be550e`.
  README.md SHA-256: `35ca37ccc366f1ba478dab33841a2c0c18ce53fd62f291ca05341f7728b225b2`.
- `Qwen/Qwen3.8-27B` revision `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`.
  generation_config.json SHA-256: `e70c136c1b78ddc1fb0905bac8e733a4dc448d4f852a5dd75143fffc70be550e`.
  README.md SHA-256: `57e4bdb258ee1a7d2635c5174ebd4e56abe392505cdb5f8bbb356b0dc4293641`.
- `deepseek-ai/DeepSeek-V4-Flash` revision `60d8d70770c6776ff598c94bb586a859a38244f1`.
  generation_config.json SHA-256: `5fccff80f55a4d455bbe516bdd552edf3e9623df95e99fbf2a3c3389fdf91af0`.
  README.md SHA-256: `c4d714818a4d3333542edc7d38ea065825a0cf7aa8fea3605bbd1d1c18e4a610`.

## Evidence and export

Runs retain the existing frozen model snapshot/hash and adapter hashes. Capture observes allowlisted final serialized settings without altering request bytes; failures are recorded and request counts expose missing observations. Exports use that snapshot and captured evidence, redact endpoints/credentials/private payloads, and distinguish incomplete evidence from a complete requested-settings match.

The standalone Markdown handoff includes a native Pi 0.85.1 model declaration for native profiles, or provider and extension snippets for historical explicit profiles. Native mock-provider tests cover streaming, complete responses, tool continuations, retries, unchanged legacy bytes and exported-extension parity. Other Pi versions require another serializer check. This does not establish production deployment, effective server settings or equivalent task quality. No production Pi installation occurs.
