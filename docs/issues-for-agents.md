# Issue for Agents

## Large output allowances must preserve complete prompts

A client can send a generous `max_tokens` or `max_completion_tokens` value while
its exact prompt length is known only to the backend. Tool history, retained
reasoning, templates and vision tokens can make the server's input count larger
than the client's estimate. This can happen after compaction as well as during
ordinary conversation.

Two independent rejection points matter: an early renderer can reserve the
requested output space before reading the whole prompt, and a later custom
request validator can reject the correctly reduced generation allowance. Fixing
only the shared budget helper does not fix either surrounding check. An error
that says the prompt contains **“at least”** a boundary count can reflect an early
bounded tokenization check, not the complete prompt's true size.

### Required behavior

1. Render and process the complete model input, including tools, retained
   reasoning and supported image/audio inputs, then count its actual token IDs.
2. If the prompt fills or exceeds the serving context, return a clear error.
   Do not shorten it unless the client explicitly requested truncation.
3. Resolve the requested output upper bound, or the documented default when
   omitted. Fit it into the remaining context. Retain smaller intentional limits
   and any established server/platform limits with their existing precedence.
4. Carry that resolved allowance through final sampling and beam-search
   conversion. Every custom validator must accept this remaining-space policy.
5. If generation reaches the allowance, return an honest length-limit finish
   reason and accurate usage. Log requested/effective allowance as metadata;
   do not append explanatory text to the model's answer.

For example, a context of 1,000 tokens with a 700-token prompt and an output
request of 1,000 allows 300 output tokens. Requesting only 100 still allows 100.
The declared model output capability stays intact; available space differs on
each request. With its automatic compaction enabled, frozen Pi can compact and
retry some length-stopped turns. That recovery does not guarantee completion and
does not replace the backend's exact accounting.

Do not conceal the failure with a fixed small response cap, character-based
truncation, reduced thinking, altered tool results, missing output fields or a
smaller model definition. Keep the gateway transparent. Any unrelated reduction
of an established capability requires the owner's explicit approval.

### Rebuild and replay

Use the [versioned patch bundle](../backend-patches/output-space/README.md). It
contains standard diffs, exact before/after hashes, a check/apply/rollback helper,
and installed-source regression checks. Its manifest states the supported source
snapshots and the prerequisite local Qwen contracts. Unknown or changed source
must be reviewed and rebased, not overwritten. A newer runtime may already solve
this issue; inspect and validate it before applying anything.

For vLLM, inspect the early renderer, tokenization options, `with_kwargs`, the
shared `get_max_tokens` resolver, and final `to_sampling_params` and
`to_beam_search_params`, including custom Qwen guards. Preserve explicit
truncation/padding sentinels and any earlier patches. For oMLX, inspect the shared
Qwen budget resolver and both text and prepared vision callers. Generate from
the same processed multimodal inputs used to calculate the budget.

Record exact runtime/model pins, prerequisite patches, source hashes, final image
identity, launch arguments, effective settings, backups and rollback receipts in
private operational records. Include the patch in the normal image build or
editable source installation. A one-time change inside a running container does
not survive recreation. The helper does not restart services or modify settings;
operators must verify idle state and use their established launcher.

### Acceptance evidence

Check the complete request-to-generation path, not isolated arithmetic. Include:

- A fitting prompt with an oversized output request; a smaller intentional
  request; omission; both output-field aliases separately; invalid limits.
- One token remaining, exactly full and overfull input; preservation of every
  valid input token; explicit truncation/padding tested separately.
- Tool history and a real post-compaction continuation through the actual client,
  gateway and selected worker, in streaming and complete-response modes.
- Supported vision inputs counted after processing, without processing them twice
  or changing the inputs before generation.
- A fresh synthetic cold request followed by an identical prompt with a measured
  warm cache hit. Do not clear existing caches to manufacture the comparison.
- Live effective context/output settings and unchanged sampling, reasoning, MTP,
  concurrency, cache budgets, model files and launcher settings.

Keep receipts local. State exactly which checks passed and which remain open.
A successful startup, short answer, parser test or partial benchmark run alone
is insufficient. Preserve failed attempts and their errors; do not relabel a
run spanning server changes as a uniform configuration.
