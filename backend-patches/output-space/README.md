# Complete prompts and remaining output space

This bundle fixes a backend compatibility failure with clients that send a large
output upper bound. Read [Issue for Agents](../../docs/issues-for-agents.md) first.
It changes request processing only. It does not change model files, declared
context/output capacity, sampling, thinking, concurrency, kernels, speculative
decoding, caches, launch arguments or the Hourglass harness.

## Scope and prerequisites

The manifest names the tested runtime snapshots and exact before/after source
hashes. **These are source-specific patches, not a universal runtime upgrade.**
A version string alone does not establish compatibility. Unknown source is refused
before any source file is written. Already patched files are recognized.

- `vllm`: two shared runtime files plus the Qwen output validator when that local
  contract exists. The validator is an installation-specific addition, not an
  assertion about every upstream vLLM installation. Its absence is reported and
  that file is skipped. Inspect any other custom validators in the new stack.
- `omlx`: the Qwen output-budget contract used by both text and prepared vision
  paths in the tested installation. A stock checkout may not contain this file;
  the helper deliberately refuses that case. Inspect the native resolver and its
  callers before deciding whether to port the same behavior. Do not add a new
  strict contract merely to make this patch apply.

Keep earlier patches and the runtime/model pins that your deployment depends on.
These diffs do not install those prerequisites. Record the base image/source
revision, all prerequisite patches, exact final image identity, effective launch
settings and validation receipts in private deployment records. Preserve the last
working image and model. Source files retain their upstream licensing; the vLLM
changes are against its Apache-2.0 source.

## Check and apply

Run from the Hourglass root. The source root is the Python **package directory**,
for example the directory containing `vllm/renderers/` or `omlx/qwen_contract.py`.
Set these example variables to your own verified paths. `patch` and Python 3.10+
are required. The check uses temporary copies and does not load a model.

```sh
python3 backend-patches/output-space/replay.py \
  --backend vllm --source-root "$VLLM_SOURCE_ROOT" --check
```

Review the diff and inspect live settings. Wait for active and queued requests to
finish, or patch an offline image/source tree. Make a separate timestamped copy
of the launcher and settings. Then apply:

```sh
python3 backend-patches/output-space/replay.py \
  --backend vllm --source-root "$VLLM_SOURCE_ROOT" \
  --apply --idle-confirmed --backup-dir "$PATCH_BACKUPS"
```

For oMLX, use `--backend omlx --source-root "$OMLX_SOURCE_ROOT"`. The helper
prepares and verifies every changed file before writing, creates a private
backup and receipt, replaces files atomically, and retains originals. It does
not inspect the live queue itself: `--idle-confirmed` is an operator assertion.
It never restarts a server, changes its launcher, installs packages or deletes a
cache. A second apply is a no-op when all expected files are already patched.

## Make container recreation retain the change

For a container deployment, include this directory in the build context and run
the same helper against the installed package during the image build. Start from
the exact established base image, including prerequisite patches. For example,
substitute the verified image and package path into this Dockerfile recipe:

```dockerfile
FROM YOUR_ESTABLISHED_PINNED_IMAGE
COPY backend-patches/output-space /opt/hourglass-output-space
RUN python3 /opt/hourglass-output-space/replay.py \
    --backend vllm --source-root /VERIFIED/site-packages/vllm \
    --apply --idle-confirmed --backup-dir /opt/hourglass-patch-backups
```

Build a new image tag and preserve the old tag. Change only the normal launcher's
image reference after its backup and review. Preserve every other argument,
environment setting, volume and cache directory. A writable-container patch by
itself is lost on recreation. Restart only when idle, using the established
launcher. Verify the running files match the manifest's final hashes and inspect
the effective settings again.

For a source installation such as editable oMLX, apply to the source used by its
existing environment, then restart with its established launcher. A reinstall
may replace those sources; rerun `--check` and review applicability after every
upgrade.

## Roll back

Use the receipt path printed by `--apply`, with the service idle or stopped:

```sh
python3 backend-patches/output-space/replay.py \
  --rollback "$PATCH_RECEIPT" --idle-confirmed
```

Rollback verifies the backup and current source hashes before restoring. It
accepts unchanged originals and recognized patched files, including an interrupted
apply; it refuses unrelated subsequent edits. Restore the backed-up launcher or
previous image reference separately when applicable, then restart while idle.
Keep rollback receipts private because they contain local paths.

## Validate the actual installed path

Run `checks.py` with the server's own Python environment after applying. For vLLM,
this covers rendered-token validation, budget resolution, request parsing and
final sampling **and beam-search** conversion. The oMLX check covers the shared
budget resolver. These checks do not load a model or establish live readiness.

```sh
python3 backend-patches/output-space/checks.py --backend vllm
```

Then perform the live acceptance checks in the linked issue guide through the
actual client/gateway/backend route. Include both response modes, a large fitting
prompt with a large output request, tool history, a post-compaction continuation,
and supported vision inputs. Prove a cold-to-warm hit with fresh synthetic input
and an identical prompt; preserve existing caches. Record limits, input and
output usage, finish reasons, route identity, errors and unresolved gaps. A short
successful request or a passing parser alone does not clear the issue.
