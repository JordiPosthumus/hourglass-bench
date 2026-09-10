# Native Pi baseline in Hourglass 3.0.0

New configurations use Pi’s native serializer, model declarations and selected thinking level. Pi computes request output space and uses normal compaction/retry/HTTP idle defaults. Existing Qwen configurations retain xhigh. Backend compatibility fields describe API differences; server launchers and model capacities are not changed. The historical explicit mappings below remain applicable to frozen explicit-v1 configurations.

# Server specifics guide

Last checked against this checkout: 2026-09-10. This is a guide to **Hourglass’s implemented request mappings**, not a promise about every release of each server. Read it before changing discovery, backend mappings, inference-profile validation or their UI explanations.

## Three different kinds of evidence

1. **Publisher recommendation:** what a model’s authors recommend. It does not establish what a server accepts or what a running deployment actually uses.
2. **Request mapping:** what Hourglass puts in the outgoing JSON. A server may reject, ignore or override a field, or require a compatible chat template.
3. **Effective behavior:** what the deployed server actually applies. Verify this separately from its live settings, resolved request observations and an appropriate exercise of the behavior.

“Not mapped” means Hourglass has no supported mapping for that control. It is not proof that every version of the server lacks it. “Not verified” means there is insufficient evidence about the running deployment; it does not mean disabled or broken. Never silently add a JSON field and assume that a successful response proves it was honored.

The implementation lives in [inference_profiles.py](../inference_profiles.py), particularly `BACKENDS`, `required_fields`, `request_settings` and `provenance`. The frontend consumes that catalog. Mapping version: `request-api-v1`. Existing unmarked profiles retain their legacy request behavior.

## Current mapping by backend

`template.*` below means `chat_template_kwargs.*`. “Unmapped” describes this Hourglass mapping. The source URLs in `BACKENDS` are the evidence references; a URL using `main` or `master` is mutable and needs a fresh check before extending support.

| Backend | Min p | Repetition penalty | Thinking enabled | Preserve thinking history | Reasoning effort |
|---|---|---|---|---|---|
| DS4 | `min_p` | Unmapped | `thinking` | Unmapped | `reasoning_effort`: none/high/max |
| oMLX | `min_p` | `repetition_penalty` | `template.enable_thinking` | `template.preserve_thinking` | `template.reasoning_effort` |
| vLLM | `min_p` | `repetition_penalty` | `template.enable_thinking` | `template.preserve_thinking` | `template.reasoning_effort` |
| SGLang | `min_p` | `repetition_penalty` | `template.enable_thinking` | `template.preserve_thinking` | `template.reasoning_effort` |
| MTPLX | No request override | No request override | `template.enable_thinking` | Server policy; no request override | Top-level `reasoning_effort` |
| LM Studio | Unmapped | `repeat_penalty` | Unmapped | Unmapped | Unmapped |
| llama.cpp | `min_p` | `repeat_penalty` | `template.enable_thinking` | `template.preserve_thinking` | `template.reasoning_effort` |
| Ollama | Unmapped | Unmapped | Encoded through `reasoning_effort` | Unmapped | Top-level `reasoning_effort`, model-dependent |

Temperature and top-p are mapped for all eight. Top-k is mapped for all except Ollama. Presence and frequency penalties are mapped for all except DS4. Seed is mapped for all eight. These are mappings, not measurements of effective behavior.

### MTPLX and Qwen3.8

The checked MTPLX request implementation exposes temperature, top-p, top-k, presence/frequency penalties, seed, thinking enablement and effort. It does not provide the three additional request overrides listed below. Allowing extra JSON keys is not evidence that those keys are consumed.

- **Min p:** a probability threshold relative to the most likely next token. The publisher’s recommended `0` means no extra min-p filtering. There is no verified request override in this adapter; do not imply a configurable server switch exists.
- **Repetition penalty:** a multiplicative adjustment for tokens already seen. `1` is neutral. It is distinct from presence/frequency penalties, and those must not be substituted for it. There is no verified request override in this adapter.
- **Preserve thinking history:** determines whether prior reasoning blocks remain in the model’s conversation context. This is not the setting that turns new thinking on or off. The local MTPLX implementation `_reasoning_history_mode` uses server policy (`auto`, `on`, `off`, `scoped`). Its `auto` path explicitly preserves history for Qwen3.8 unless an overriding policy applies. This source observation is not a verification of the deployed server.

Hourglass records these three names under `inference_profile.server_managed` when the user accepts the MTPLX proposal. They are absent from requested `values`, remain present in the publisher source record, and are exported with effective value `null` and an unverified status. The internal property name does **not** imply all three are adjustable server settings. UI wording should say **“Not overridden by Hourglass”** and explain each separately. Manual values that conflict with this declaration remain validation errors. Thinking enablement and reasoning effort cannot be silently delegated this way.

References:

- [MTPLX request implementation at the adapter’s recorded revision](https://github.com/youssofal/MTPLX/blob/21be78b3f51820eecef020e5e4855c0715eaf9a5/mtplx/server/openai.py).
- Local inspection additionally used `mtplx/server/openai.py` in the owner’s MTPLX checkout: `ChatCompletionRequest`, `_request_chat_template_kwargs`, `_thinking_enabled_for_request` and `_reasoning_history_mode`. The local checkout may differ from that pinned upstream revision.
- [Qwen3.8-27B model card used during browser verification](https://huggingface.co/Qwen/Qwen3.8-27B/blob/1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0/README.md).

### Other backend qualifications

- **LM Studio:** this adapter targets `/v1/chat/completions`. Native `/api/v1/chat` is a different API. The current gaps in min-p and thinking controls must not be described as universal LM Studio limitations. Check the actual deployed version and endpoint before changing them. [Reference](https://lmstudio.ai/docs/developer/openai-compat/chat-completions).
- **oMLX:** forced sampling or template settings can override client requests. A mapped field is not proof that it wins. [Recorded API source](https://github.com/jundot/omlx/blob/94530d8d49541ede9e99ef04a4431ee4953117a6/omlx/api/openai_models.py).
- **vLLM / SGLang / llama.cpp:** thinking and history options require a model chat template that implements those options. Generic OpenAI compatibility alone does not establish this. [vLLM](https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/openai/chat_completion/protocol.py), [SGLang](https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/entrypoints/openai/protocol.py), [llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
- **DS4:** the current validator distinguishes none/high/max, requires explicit Think Max selection for max, and requires at least 384 × 1024 tokens of context for that lane. Do not silently downgrade effort or alter context to make a profile pass. [Recorded source](https://github.com/antirez/ds4/blob/21e98c129ce20ebb9e5d2de1a1bbf5f991d3795d/ds4_server.c).
- **Ollama:** native API options are not automatically valid OpenAI-compatible request fields. The adapter translates disabled thinking to effort `none`; model support for effort still matters. [Reference](https://docs.ollama.com/api/openai-compatibility).

## Hourglass → DSG → server

Hourglass authenticates to DSG using the **DSG ingress key**. DSG selects the worker and applies that worker’s separate backend credential; the client key is not the backend key. Do not bypass DSG to work around discovery problems without an explicit decision to use a direct endpoint.

Use the base URL documented for your DSG deployment. A direct worker tunnel is a different connection path; verify routing before sending benchmark content.

The profile’s `route.name` is sent as `x-dsg-model`; the body’s `model` selects the native model or configured alias. A model ID alone does not pin a worker. The route must already be configured in DSG to select the intended backend. Testing mode uses the same forwarding and authentication path; Hourglass does not toggle it. The harness records `x-ds4-node` when available. See [harness/inference-settings.mjs](../harness/inference-settings.mjs).

Model discovery sends metadata GETs only. A 401/403 is an authentication/access failure, not an empty model list. A DSG model list can describe one selected worker rather than the entire fleet. Inspect currently does not send the profile’s `x-dsg-model` route header; do not assume discovered metadata was verified against the eventual pinned route.

### Pi request compatibility

For explicit vLLM profiles, the generated Pi model definition sets `compat.supportsStore: false`. Pi otherwise adds `store: false` because Hourglass uses the generic provider name `benchmark`; the checked deployment rejects even that false value with HTTP 400 before inference. The declaration omits this unsupported request field. It does not change sampling, thinking, limits, tools, routing or server storage settings. Other backends and legacy profiles retain their existing serialization. The pinned Pi package remains unchanged. Native integration tests compare the full requests in streaming and complete modes, including a tool continuation, and require the omitted `store` field to be the only difference.

The wrapper retains the latest assistant `message_end` event when Pi attempts context recovery. Pi can remove a failed overflow message from its active conversation before recovery; if recovery does not succeed, that removal must not make Hourglass inject more `Continue` prompts. Successful native recovery replaces the observed failure with its successful assistant response. Pi compaction and retries remain enabled.

## Context and output are different

- `context_window` records serving context capacity, typically shared by input and output. Selecting a model fills it from reported `context_length`; unknown serving capacity stays blank. A model’s theoretical maximum is not proof of its loaded capacity.
- `max_tokens` is the requested output limit when output behavior is explicit. The current UI may suggest a reported output maximum, or a reported context as a visible starting value; review it before saving.
- Server-controlled output deliberately omits the output-limit field. It does not change the server’s own limit.
- A single chat output limit is not equivalent to independent reasoning and final-answer budgets.

The prompt and output share the serving context. Treat the requested output as an upper bound and let the backend fit it to the space after the complete processed prompt, retaining smaller intentional requests and existing default/override/platform precedence. Earlier inspected vLLM paths rejected an oversized explicit request before inference; both the early renderer and a later custom Qwen validator required correction. Omitting the output field or reducing the model definition conceals that problem and can change behavior. See [Issue for Agents](issues-for-agents.md) and the [replayable patch bundle](../backend-patches/output-space/README.md) for the complete contract, prerequisites and acceptance checks.

## Recommendations, evidence and maintenance

`hf-settings-v2` gives recognized mode-specific model-card recommendations precedence over general generation defaults. It retains both source candidates and file hashes. For the checked Qwen3.8 source, non-thinking uses temperature 0.7 and top-p 0.8 rather than treating general defaults 1 and 0.95 as unresolved conflicts. Genuine equal-priority conflicts remain unresolved. Existing `hf-settings-v1` source records stay valid and are not rewritten.

Before an inference-related change: read the current mapping and deployed server code, inspect relevant settings/history, make a timestamped backup, and name the exact delta. Preserve unrelated settings. Changes that reduce an established capability require the owner’s explicit approval. Never turn a diagnostic limit or compatibility fallback into a production setting. Restart only when authorized and idle.

Validation must match the claim:

- Parser/schema checks establish request syntax only.
- Browser tests establish the form’s behavior, including save/reopen and source visibility.
- Mock forwarding tests establish transport behavior, not real model quality or effective sampling.
- Verify actual server-resolved behavior separately before claiming a deployed setting is honored. Capacity, concurrency and cache claims need direct boundary or cold-to-warm exercises.

The 2026-09-10 UI checks used the real pinned publisher card and a temporary mock model endpoint, including authenticated discovery, context fill, both modes, save/reopen, DSG route preservation in saved profiles, and outgoing request mapping. They did not prove the effective values of the three omitted MTPLX controls on the deployed server.

Relevant checks: `tests/test_inference_profiles.py`, `tests/test_inference_profile_editor.js`, `tests/test_inference_settings.mjs`, `tests/test_model_catalog.py`, and `tests/test_model_picker.js`. Also read [inference profiles](inference-profiles.md).
