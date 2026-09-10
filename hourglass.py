#!/usr/bin/env python3
"""Hourglass — a personal, contamination-free agentic benchmark.

Seeded-defect challenges built from your own private repos. Models are served
locally (LM Studio / llama-server / MLX, all OpenAI-compatible) and driven
through one identical minimal tool API, so results measure the *model* on
*your hardware* — speed and accuracy together, i.e. a private frontier.

Commands:
  hourglass.py cert <task-id>                     certify a task (bug fails / clean passes)
  hourglass.py generate <task-id> --repo R --test T [--mutation f|find|replace] [flags]
  hourglass.py run <task-id> --model NAME [--repeat N] [--config models.json] [--no-sandbox]
  hourglass.py leaderboard                        per task×model aggregates
  hourglass.py frontier                           speed-vs-accuracy Pareto frontier on your hardware
"""
import scoring_policy
import argparse, base64, datetime as dt, hashlib, json, os, re, shlex, shutil, subprocess, sys, tempfile, time
import urllib.request
import urllib.parse
import uuid
import statistics
import calibration
import run_tracking
import hour_score
import question_deadline
import diagnostics
import task_identity
import option_layout
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS, RESULTS, SANDBOX = ROOT / "tasks", ROOT / "results", ROOT / "sandboxes"
REAL_HOME = str(Path.home())
BENCHMARK_VERSION = "3.0.0"

def requires_vision(task):
    return task.get("kind") == "chart-vqa" or bool(task.get("image") or task.get("assets"))

# ------------------------------------------------------------------- sandbox
def benchmark_worktrees():
    """Answer keys in this repository's linked worktrees are private too."""
    git=ROOT/'.git'
    try:
        if git.is_file():
            pointer=git.read_text().strip()
            if not pointer.startswith('gitdir: '):return []
            git=(ROOT/pointer[8:]).resolve()
        common=git/'commondir'
        if common.is_file():git=(git/common.read_text().strip()).resolve()
        if not git.is_dir():return []
        git=git.resolve()
        roots=[git.parent] if git.name=='.git' else []
        for marker in (git/'worktrees').glob('*/gitdir'):
            target=Path(marker.read_text().strip()).resolve()
            if target.name=='.git':roots.append(target.parent)
        return roots
    except (OSError,ValueError):return []


def sandbox_profile(workdir: str, sandboxed=True) -> str:
    if not sandboxed:
        controller_port=int(os.environ.get('HOURGLASS_PORT','4534'))
        if not 1<=controller_port<=65535:raise ValueError('Invalid benchmark controller port.')
        base=f'(version 1)\n(allow default)\n(deny network-outbound (remote ip "localhost:{controller_port}"))'
        return diagnostics.protected_profile(base, [ROOT,*benchmark_worktrees()], workdir,
            [os.environ.get('HOURGLASS_ATTEMPT_CHECKPOINT'),os.environ.get('HOURGLASS_TELEMETRY_PHASE')])
    deny = ["Library", ".ssh", ".pi", ".hermes", ".openclaw", ".config", ".aws",
            ".gnupg", ".zsh_history", ".netrc", ".npmrc", "Documents"]
    prof = ["(version 1)", "(allow default)", "(deny network*)"]
    for d in deny:
        prof.append(f'(deny file-read* (subpath "{REAL_HOME}/{d}"))')
    prof.append(f'(deny file-write* (subpath "{REAL_HOME}"))')
    prof.append(f'(allow file-write* (subpath "{workdir}"))')
    # enforce isolation: the benchmark repo (answer keys, generators, verifiers) is unreadable from tools
    private_roots=list(dict.fromkeys([ROOT,*benchmark_worktrees()]))
    for private_root in private_roots:
        escaped=str(private_root).replace('\\','\\\\').replace('"','\\"')
        prof.append(f'(deny file-read* (subpath "{escaped}"))')
    prof.append(f'(allow file-read* (subpath "{workdir}"))')
    # Node resolves the entrypoint by stat-ing each ancestor. Permit directory
    # metadata only; private file contents remain denied outside the workspace.
    for parent in Path(workdir).resolve().parents:
        if any(parent == root or parent.is_relative_to(root) for root in private_roots):
            prof.append(f'(allow file-read-metadata (literal "{parent}"))')
    return diagnostics.protected_profile("\n".join(prof), private_roots, workdir,
        [os.environ.get('HOURGLASS_ATTEMPT_CHECKPOINT'),os.environ.get('HOURGLASS_TELEMETRY_PHASE')])

def scrub_env(workdir) -> dict:
    return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(workdir), "TERM": "dumb", "LANG": "en_US.UTF-8"}

def run_bash(cmd, cwd, sandboxed=True):
    prof = sandbox_profile(str(cwd), sandboxed)
    wrapped = f"sandbox-exec -p {shlex.quote(prof)} bash -c {shlex.quote(cmd)}"
    env = scrub_env(cwd) if sandboxed else dict(os.environ, HOME=str(cwd))
    t0 = time.time()
    try:
        p = subprocess.run(["bash", "-c", wrapped], cwd=str(cwd), env=env,
                           capture_output=True, text=True)
        out = (p.stdout or "")[:20000]
        if p.stderr: out += ("\n[stderr]\n" + p.stderr[:4000])
        if p.returncode != 0: out += f"\n[exit {p.returncode}]"
        return out, time.time() - t0
    except subprocess.TimeoutExpired:
        return "[error: command timed out]", time.time() - t0

import os

def sha(p: Path):
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:
        return None

def workspace_path(workdir, rel):
    """Confine native file tools as strictly as the shell tool."""
    base = Path(workdir).resolve()
    p = (base / rel).resolve()
    if not p.is_relative_to(base):
        raise ValueError("path outside workspace")
    return p

def prune(workdir: Path, exclude):
    for pat in [".git", "**/.git"] + list(exclude or []):
        for p in workdir.glob(pat):
            shutil.rmtree(p, ignore_errors=True) or p.unlink(missing_ok=True)

# ---------------------------------------------------------------------- build
def build(task, mutate=True) -> Path:
    workdir = SANDBOX / f"{task['id']}-{int(time.time()*1000)}"
    workdir.mkdir(parents=True)
    if task.get("source"):
        src = task["source"]["repo"]
        ref = task["source"].get("sha") or task["source"].get("ref", "HEAD")
        subprocess.run(f"git -C {shlex.quote(src)} archive {shlex.quote(ref)} | tar -x -C {workdir}",
                       shell=True, check=True)
    for rel, content in (task.get("files") or {}).items():
        f = workspace_path(workdir, rel)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    prune(workdir, task.get("exclude"))
    for rel in (task.get("assets") or []):
        dst = workspace_path(workdir, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(TASKS / task["id"] / rel, dst)
    if mutate:
        for m in as_mutations(task):
            f = workdir / m["file"]
            txt = f.read_text()
            if m["find"] not in txt:
                raise SystemExit(f"[mutation] pattern not found in {m['file']} — snapshot/ref stale")
            f.write_text(txt.replace(m["find"], m["replace"], m.get("count", 1)))
    manifest = {}
    for pat in task.get("verifier", {}).get("forbidden", []):
        for p in workdir.glob(pat):
            if p.is_file():
                manifest[str(p.relative_to(workdir))] = sha(p)
    (diagnostics.directory(ROOT, workdir, create=True) / "integrity.json").write_text(json.dumps(manifest))
    for c in (["init", "-q"], ["add", "-A"], ["-c", "user.email=hourglass@bench",
              "-c", "user.name=hourglass", "commit", "-qm", "snapshot"]):
        subprocess.run(["git", "-C", str(workdir)] + c, capture_output=True)
    return workdir

def as_mutations(task):
    m = task.get("mutation")
    return m if isinstance(m, list) else ([m] if m else [])

# ------------------------------------------------------------------- verify
def restore_hidden(task, workdir):
    hidden = TASKS / task["id"] / "verify"
    if hidden.is_dir():
        for p in hidden.rglob("*"):
            if p.is_file():
                dst = workdir / "tests_hidden" / p.relative_to(hidden)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(p.read_text())

def verify(task, workdir, sandboxed=True):
    restore_hidden(task, workdir)
    combined = ""
    for cmd in task.get("verifier", {}).get("commands", []):
        o, _ = run_bash(f"cd {shlex.quote(str(workdir))} && {cmd}", workdir,
                        sandboxed=sandboxed)
        combined += o
    ok = ("[exit " not in combined) and ("Traceback" not in combined) and ("error:" not in combined)
    manifest = json.loads(diagnostics.source(ROOT, workdir, "integrity.json").read_text())
    tampered = []
    for rel, h in manifest.items():
        if sha(workdir / rel) != h:
            tampered.append(rel + ("" if (workdir / rel).exists() else " (deleted)"))
    return ok, combined[-1500:], sorted(tampered)

def cert(args):
    task_id = args.task if hasattr(args, "task") else args
    task = json.loads((TASKS / task_id / "task.json").read_text())
    if task.get("kind") == "mcq":
        errors = validate_mcq(task)
        if errors:
            raise SystemExit("INVALID: " + "; ".join(errors))
        print(f"[{task_id}] MCQ schema and answer mapping valid; {len(task.get('options', []))} options.")
        print("This checks the runtime contract. Source truth certification belongs to the originating bundle.")
        return
    if task.get("kind") == "chart-vqa":
        print(f"[{task_id}] chart-vQA tasks certify via intake regen-check, not cert; skipping")
        return
    clean, mutated = build(task, False), build(task, True)
    ok_clean, out_clean, _ = verify(task, clean)
    ok_bug, out_bug, _ = verify(task, mutated)
    shutil.rmtree(clean, ignore_errors=True); shutil.rmtree(mutated, ignore_errors=True)
    good = ok_clean and not ok_bug
    print(f"[{task_id}] clean passes: {ok_clean} | bug fails: {not ok_bug}")
    print("CERTIFIED ✓ — safe to run" if good else "INVALID ✗ — fix mutation/test; do not run")
    print("-- clean tail:", out_clean[-240:].replace(chr(10), " "))
    print("-- bug tail:", out_bug[-240:].replace(chr(10), " "))

# --------------------------------------------------------------------- agent
SYSTEM_PROMPT = """You are working inside a sandboxed copy of a repository.

Rules:
- The workspace directory is your entire world. Read/edit/run only what lives there.
- There is NO network access; any fetch/install from the internet will fail.
- Grading tests live outside your workspace; you cannot see or run them.
  Fix the ROOT CAUSE honestly. Deleting/lying about tests gains nothing.
- When finished, call the `submit` tool with a one-line fix summary.
"""

TOOLS = [
    {"type": "function", "function": {"name": "read_file", "description": "Read a file.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Create/overwrite a file.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "Exact, unique-text replacement.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"},
            "oldText": {"type": "string"}, "newText": {"type": "string"}},
            "required": ["path", "oldText", "newText"]}}},
    {"type": "function", "function": {"name": "bash", "description": "Run shell command in workspace (sandboxed, no network).",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "submit", "description": "Declare task complete; one-line summary.",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}},
]

ANSWER_TOOL = {"type": "function", "function": {
    "name": "answer_question",
    "description": "FINAL answer for this single question. Option items: {\"option\":\"###\"}. Numeric items: {\"value\":N}.",
    "parameters": {"type": "object", "properties": {"option": {"type": "string"}, "value": {"type": "number"}}}}}
TOOLS_MCQ = [t for t in TOOLS if t["function"]["name"] != "submit"] + [ANSWER_TOOL]

def exec_tool(name, args, workdir, sandboxed):
    try:
        if name == "read_file":
            p = workspace_path(workdir, args["path"])
            return p.read_text(errors="replace")[:30000] or "(empty)"
        if name == "write_file":
            p = workspace_path(workdir, args["path"]); p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"]); return "ok"
        if name == "edit_file":
            p = workspace_path(workdir, args["path"])
            if not p.exists(): return "error: file does not exist"
            txt = p.read_text(); c = txt.count(args["oldText"])
            if c == 0: return "error: oldText not found"
            if c > 1: return "error: oldText not unique — add more context"
            p.write_text(txt.replace(args["oldText"], args["newText"])); return "ok"
        if name == "bash":
            out, _ = run_bash(args["command"], workdir, sandboxed=sandboxed)
            return out or "(no output)"
    except Exception as e:
        return f"error: {e}"
    return None

def chat(url, model, messages, cfg, use_tools=True, tools=None):
    body = {"model": model, "messages": messages,
           "max_tokens": cfg.get("max_tokens", 1024)}
    if use_tools: body["tools"] = tools if tools is not None else TOOLS
    if cfg.get("reasoning") is not None: body["reasoning"] = cfg["reasoning"]
    if cfg.get("extra"): body.update(cfg["extra"])
    body.pop("temperature", None)
    if cfg.get("output_budget") == "server":
        body.pop("max_tokens", None)
        body.pop("max_completion_tokens", None)
    req = urllib.request.Request(url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=None) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read(65536).decode("utf-8", errors="replace")
        if e.code in (400, 415, 422, 500) and any(
            isinstance(m.get("content"), list) and any(c.get("type") == "image_url" for c in m["content"] if isinstance(c, dict))
            for m in messages
        ) and vision_rejection(detail):
            raise UnsupportedVision(detail) from e
        raise RuntimeError(f"HTTP {e.code}: {detail or e.reason}") from e

from benchmark_errors import UnsupportedVision

def vision_rejection(detail):
    text = detail.lower()
    patterns = (
        r"(?:model|server|endpoint)[^\n]{0,100}(?:does not support|doesn't support|cannot process|can only process)[^\n]{0,40}(?:image|vision|multimodal|text)",
        r"(?:image|vision|multimodal)[^\n]{0,50}(?:not supported|unsupported|not available)",
        r"(?:does not support|doesn't support)[^\n]{0,30}(?:image|vision|multimodal)",
        r"(?:requires?|missing|no)[^\n]{0,30}(?:mmproj|vision encoder|vision model|multimodal projector)",
    )
    return any(re.search(pattern, text) for pattern in patterns)

def is_unsupported_vision(error):
    while error is not None:
        if isinstance(error, UnsupportedVision): return True
        error = error.__cause__
    return False

class AgentRunError(RuntimeError):
    def __init__(self, error, trace, pt, ct, calls, started):
        super().__init__(str(error))
        self.trace = trace
        self.metrics = {"prompt_tokens": pt, "completion_tokens": ct, "tool_calls": calls,
                        "duration_s": round(time.time()-started, 3)}

def shuffle_choices(task):
    letters = "ABCD"
    ch = task["choices"][:4]
    if not task.get("shuffle"):
        return "Choices:\n" + "\n".join(f"{L}. {c}" for L, c in zip(letters, ch)), {L: L for L in letters}
    key = hashlib.sha256(task["id"].encode()).hexdigest()
    order = sorted(range(len(ch)), key=lambda i: hashlib.sha256(f"{key}:{i}".encode()).hexdigest())
    disp = "Choices:\n" + "\n".join(f"{letters[j]}. {ch[order[j]]}" for j in range(len(ch)))
    return disp, {letters[j]: letters[order[j]] for j in range(len(ch))}

def parse_json_answer(content):
    m = re.search(r"\{[^{}]*\}", content or "", re.S)
    if m:
        try: return json.loads(m.group(0))
        except Exception: pass
    idx = re.search(r"answer", content or "", re.I)
    if idx:
        m2 = re.search(r"\b([A-Da-d])\b", (content or "")[idx.end():], re.I)
        if m2: return {"answer": m2.group(1).upper()}
    m3 = re.search(r"(?<![A-Za-z])\b([A-Da-d])\b(?![A-Za-z])", content or "")
    if m3: return {"answer": m3.group(1).upper()}
    m4 = re.search(r"-?\d+(\.\d+)?", content or "")
    return {"value": float(m4.group(0))} if m4 else {}

def run_chart(task, model_cfg, workdir):
    url, name = model_cfg["base_url"], model_cfg["model"]
    b64 = base64.b64encode((workdir / task["image"]).read_bytes()).decode()
    disp, disp_map = ("", None) if task.get("mode")=="numeric" else shuffle_choices(task)
    mode = task.get("mode", "letter")
    answer_hint = '{"answer":"<letter>"}' if mode == "letter" else '{"value": <number>}'
    q = task["prompt"] + "\n\n" + disp + "\n\nReply with JSON only: " + answer_hint + "\nNo other text."
    messages = [{"role": "system", "content": "You are careful and honest about visual charts. Answer exactly in the requested JSON."},
                {"role": "user", "content": [{"type": "text", "text": q},
                                             {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}]
    t0 = time.time()
    resp = chat(url, name, messages, model_cfg, use_tools=False)
    u = resp.get("usage") or {}
    content = resp["choices"][0]["message"].get("content") or ""
    metrics = {"prompt_tokens": u.get("prompt_tokens", 0),
               "completion_tokens": u.get("completion_tokens", 0), "tool_calls": 0,
               "duration_s": round(time.time() - t0, 1)}
    trace = [{"user_question": q[:500], "assistant": content}]
    return trace, metrics, parse_json_answer(content), disp_map

def score_chart(task, parsed, disp_map):
    if task.get("mode", "letter") == "numeric":
        truth = task.get("answer_value")
        got = parsed.get("value")
        tol = task.get("tolerance_pct", 5)
        band = abs(truth) * tol / 100 if truth else task.get("abs_tol", 0.5)
        ok = isinstance(got, (int, float)) and truth is not None and abs(got - truth) <= band
        return bool(ok), f"numeric truth={truth} got={got} tol={tol}%", []
    letter = str(parsed.get("answer", "")).strip().upper()[:1]
    orig = (disp_map or {}).get(letter, letter)
    return orig == task["answer"], f"choice truth={task['answer']} got={letter} -> orig={orig}", []

def mcq_display(task):
    opts = task["options"]
    key = hashlib.sha256(task["id"].encode()).hexdigest()
    order = (sorted(range(len(opts)), key=lambda i: hashlib.sha256(f"{key}:{opts[i]['id']}".encode()).hexdigest())
             if task.get("shuffle") else list(range(len(opts))))
    return "Options:\n" + "\n".join(f'{opts[i]["id"]} \u2014 {opts[i]["text"]}' for i in order)

MCQ_SYSTEM = """You are answering exactly ONE benchmark question, seriously and to the end.
- The workspace may contain a chart image; use tools (bash/python) as needed.
- Finish by calling `answer_question` exactly once: for option items {"option":"###"},
  for numeric items {"value": <number>}.
- Your answer is ONLY that tool-call content: no worked solution.
- There is no network access; everything needed is in the workspace or the question."""

def run_mcq(task, model_cfg, workdir, sandboxed=True):
    url, name = model_cfg["base_url"], model_cfg["model"]
    disp = mcq_display(task)
    txt = task["prompt"] + "\n\n" + disp + "\n\nCall answer_question with your final answer."
    if task.get("assets"):
        img = workdir / task["assets"][0]
        b64 = base64.b64encode(img.read_bytes()).decode()
        user_content = [{"type": "text", "text": txt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]
    else:
        user_content = txt
    messages = [{"role": "system", "content": MCQ_SYSTEM},
                {"role": "user", "content": user_content}]
    trace = []; pt = ct = calls = 0; t0 = time.time(); parsed = {}
    finished = False
    for _ in range(task.get("max_turns", 40)):
        print(f"MODEL turn {_+1}: waiting for response", flush=True)
        try:
            resp = chat(url, name, messages, model_cfg, tools=TOOLS_MCQ)
        except Exception as e:
            raise AgentRunError(e, trace, pt, ct, calls, t0) from e
        u = resp.get("usage") or {}
        pt += u.get("prompt_tokens", 0); ct += u.get("completion_tokens", 0)
        msg = resp["choices"][0]["message"]
        messages.append(msg)
        trace.append({"assistant": msg.get("content"),
                      "calls": [tc["function"] for tc in (msg.get("tool_calls") or [])]})
        if not msg.get("tool_calls"):
            messages.append({"role": "user", "content": "Continue working, or call answer_question."})
            continue
        finished = False
        for tc in msg["tool_calls"]:
            fn = tc["function"]["name"]
            print(f"TOOL {fn}", flush=True)
            try: args = json.loads(tc["function"]["arguments"] or "{}")
            except Exception: args = {}
            calls += 1
            if fn == "answer_question":
                parsed = args
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": "answer recorded"})
                trace.append({"answer": args}); finished = True; break
            result = exec_tool(fn, args, workdir, sandboxed)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result or ""})
            trace.append({"tool": fn, "args": {k: (v[:200] if isinstance(v, str) else v)
                          for k, v in args.items()}, "result": (result or "")[:1500]})
        if finished: break
    return trace, {"prompt_tokens": pt, "completion_tokens": ct, "tool_calls": calls,
                   "duration_s": round(time.time() - t0, 3),
                   "termination": "answered" if finished else "turn_limit"}, parsed, None

def score_mcq(task, parsed):
    import math as _m
    if task.get("mode") == "numeric":
        tgt, tol = task.get("target"), task.get("tolerance_abs")
        try:
            v = float(parsed.get("value"))
            if not _m.isfinite(v): raise ValueError
            err = abs(v - tgt); solved = err <= tol
        except Exception:
            v = None; err = None; solved = False
        extra = {"answer_value": v,
                 "abs_err": round(err, 8) if err is not None else None,
                 "rel_err": round(err / abs(tgt), 8) if (err is not None and tgt) else None,
                 "err_in_tols": round(err / tol, 3) if (err is not None and tol) else None,
                 "target": tgt, "tolerance_abs": tol}
        return bool(solved), f"numeric target={tgt} got={v} tol={tol}", [], extra
    cand = str(parsed.get("option", "")).strip()
    if cand.isdigit(): cand = cand.zfill(3)
    solved = cand == task.get("answer")
    return bool(solved), f"option truth={task.get('answer')} got={cand}", [], {"parsed_option": cand}

def validate_mcq(task):
    errors = []
    if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
        errors.append("missing prompt")
    if task.get("mode") == "numeric":
        import math
        if not all(isinstance(task.get(k), (int, float)) and math.isfinite(task[k]) for k in ("target", "tolerance_abs")):
            errors.append("numeric target/tolerance must be finite")
        elif task["tolerance_abs"] < 0:
            errors.append("negative tolerance")
    else:
        opts = task.get("options") or []
        ids = [o.get("id") for o in opts]
        texts = [o.get("text") for o in opts]
        if len(opts) < 2 or len(set(ids)) != len(ids) or len(set(texts)) != len(texts):
            errors.append("options must contain distinct IDs and text")
        if task.get("answer") not in ids:
            errors.append("answer is not an option")
    return errors

def legacy_run_agent(task, model_cfg, workdir, sandboxed=True):
    url, name = model_cfg["base_url"], model_cfg["model"]
    if task.get("kind") == "chart-vqa":
        return run_chart(task, model_cfg, workdir)
    if task.get("kind") == "mcq":
        return run_mcq(task, model_cfg, workdir, sandboxed)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": task["prompt"]}]
    trace = []
    pt = ct = calls = 0
    t0 = time.time()
    for _ in range(task.get("max_turns", 30)):
        print(f"MODEL turn {_+1}: waiting for response", flush=True)
        try:
            resp = chat(url, name, messages, model_cfg)
        except Exception as e:
            raise AgentRunError(e, trace, pt, ct, calls, t0) from e
        u = resp.get("usage") or {}
        pt += u.get("prompt_tokens", 0); ct += u.get("completion_tokens", 0)
        msg = resp["choices"][0]["message"]
        messages.append(msg)
        trace.append({"assistant": msg.get("content"),
                      "calls": [tc["function"] for tc in (msg.get("tool_calls") or [])]})
        if not msg.get("tool_calls"):
            messages.append({"role": "user", "content": "Continue with a tool call, or `submit` if done."})
            continue
        submitted = False
        for tc in msg["tool_calls"]:
            fn = tc["function"]["name"]
            try: args = json.loads(tc["function"]["arguments"] or "{}")
            except Exception: args = {}
            calls += 1
            if fn == "submit":
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": "ok"})
                trace.append({"submit": args.get("summary", "")}); submitted = True; break
            result = exec_tool(fn, args, workdir, sandboxed)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result or ""})
            trace.append({"tool": fn, "args": {k: v[:200] if isinstance(v, str) else v
                          for k, v in args.items()}, "result": (result or "")[:1500]})
        if submitted: break
    return trace, {"prompt_tokens": pt, "completion_tokens": ct, "tool_calls": calls,
                   "duration_s": round(time.time() - t0, 1)}, {}, None

def run_agent(task, model_cfg, workdir, sandboxed=True):
    from harness_runner import run
    return run(task, model_cfg, workdir, sandboxed)

# ------------------------------------------------------------------- provenance
def capture_provenance(cfg_path=None):
    def sh(cmd):
        try:
            return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                  timeout=30).stdout.strip() or "unknown"
        except Exception:
            return "unknown"
    prov = {"schema": 1, "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "node": os.environ.get("NODE_ID", "unknown"),
            "hostname": sh("hostname"), "os": sh("uname -sr"),
            "macos": sh("sw_vers -productVersion"), "macos_build": sh("sw_vers -buildVersion"),
            "chip": sh("sysctl -n machdep.cpu.brand_string"), "cores": sh("sysctl -n hw.ncpu"),
            "ram_bytes": sh("sysctl -n hw.memsize"),
            "sandbox_exec": "yes" if shutil.which("sandbox-exec") else "no",
            "python": sys.version.split()[0], "pi_version": sh("pi --version"),
            "hourglass_sha": (sha(ROOT / "hourglass.py") or "unknown")[:16],
            "idle_load_1m": sh("sysctl -n vm.loadavg"), "uptime": sh("uptime | sed 's/.*up /up /;s/,[^,]*load.*//'")}
    if cfg_path and Path(cfg_path).exists():
        servers = {}
        for m in json.loads(Path(cfg_path).read_text()).get("models", []):
            u = m["base_url"].rstrip("/")
            if u in servers: continue
            s = servers.setdefault(u, {})
            try:
                with urllib.request.urlopen(u + "/models", timeout=30) as r:
                    s["models"] = [d.get("id") for d in json.loads(r.read()).get("data", [])][:30]
            except Exception as e:
                s["models"] = f"unreachable: {str(e)[:60]}"
            try:
                root = u[:-3] if u.endswith("/v1") else u
                with urllib.request.urlopen(root + "/health", timeout=30) as r:
                    s["health"] = r.read().decode(errors="ignore")[:80]
            except Exception: pass
        prov["servers"] = servers
    return prov

def get_provenance(cfg_path, refresh_cache_s=86400):
    cache = ROOT / "provenance.json"
    try:
        if cache.exists() and time.time() - cache.stat().st_mtime < refresh_cache_s:
            doc = json.loads(cache.read_text())
            if doc.get("servers") and doc.get("captured_at"):
                return doc
    except Exception: pass
    prov = capture_provenance(cfg_path)
    cache.write_text(json.dumps(prov, indent=1))
    return prov

def cmd_probe(args):
    cfg = str(ROOT / "models.json")
    prov = capture_provenance(cfg if Path(cfg).exists() else None)
    (ROOT / "provenance.json").write_text(json.dumps(prov, indent=1))
    print(json.dumps(prov, indent=1))

# ------------------------------------------------------------------- commands
def load_models(path):
    doc = json.loads(Path(path).read_text())
    errors = validate_models(doc)
    if errors:
        raise ValueError("; ".join(errors))
    return {m["name"]: m for m in doc["models"]}

def validate_models(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("models"), list):
        return ["Expected an object containing a models array"]
    errors, seen = [], set()
    for i, m in enumerate(doc["models"]):
        if not isinstance(m, dict):
            errors.append(f"Model {i+1} must be an object"); continue
        for k in ("name", "base_url", "model"):
            if not isinstance(m.get(k), str) or not m[k].strip():
                errors.append(f"Model {i+1}: {k} is required")
        name = m.get("name")
        if isinstance(name, str):
            if name in seen: errors.append(f"Duplicate model name: {name}")
            seen.add(name)
        if isinstance(m.get("base_url"), str):
            u = urllib.parse.urlparse(m["base_url"])
            if u.scheme not in ("http", "https") or not u.netloc:
                errors.append(f"Model {i+1}: base_url must be an HTTP(S) URL")
        if m.get("output_budget", "explicit") not in ("explicit", "server", "pi"):
            errors.append(f"Model {i+1}: output_budget must be pi, explicit or server")
        if "supports_vision" in m and type(m["supports_vision"]) is not bool:
            errors.append(f"Model {i+1}: supports_vision must be true or false")
        if "hardware" in m and (not isinstance(m["hardware"], str) or len(m["hardware"])>160 or any(ord(c)<32 for c in m["hardware"])):
            errors.append(f"Model {i+1}: hardware must be a single line of text (up to 160 characters)")
        if "extra" in m and not isinstance(m["extra"], dict):
            errors.append(f"Model {i+1}: extra must be an object")
        try:__import__('inference_profiles').request_settings(m)
        except ValueError as exc:errors.append(f'Model {i+1}: {exc}')
    return errors

def cmd_run(args):
    global TASKS
    evaluation_id=os.environ.get('HOURGLASS_EVALUATION_ID')
    if evaluation_id:
        manifest=json.loads((ROOT/'evaluations'/(evaluation_id+'.json')).read_text())
        if manifest.get('task_snapshot'):TASKS=ROOT/manifest['task_snapshot']
    task = json.loads((TASKS / args.task / "task.json").read_text())
    cfg_path = args.config or str(ROOT / "models.json")
    models = load_models(cfg_path)
    if args.model not in models:
        raise SystemExit(f"model '{args.model}' not in {cfg_path} (have: {', '.join(models)})")
    mcfg = models[args.model]
    repeat = args.repeat if args.repeat is not None else task.get("repeat", 3)
    if not isinstance(repeat, int) or repeat < 1:
        raise ValueError("Repeat count must be a positive integer")
    if task.get("kind") == "mcq" and (errors := validate_mcq(task)):
        raise ValueError("Invalid task: " + "; ".join(errors))
    prov = get_provenance(cfg_path)
    task_sha = (sha(TASKS / args.task / "task.json") or "")[:16]
    task_bundle_sha=task_identity.identity(TASKS/args.task)
    evaluation_id=os.environ.get('HOURGLASS_EVALUATION_ID')
    if evaluation_id:
        manifest=json.loads((ROOT/'evaluations'/(evaluation_id+'.json')).read_text())
        expected=next(t for t in manifest['expected'] if t['task']==args.task)
        task_identity.verify(TASKS/args.task,expected)
    original_task=task
    presentation_seed=manifest.get('presentation_seed','') if evaluation_id else uuid.uuid4().hex
    sandboxed = not args.no_sandbox
    chart = task.get("kind") == "chart-vqa"
    early_stop = os.environ.get("HOURGLASS_SKIP_REASON") in ("five_wrong_in_row", "wrong_streak_limit")
    stop_limit = int(os.environ.get("HOURGLASS_STOP_AFTER_WRONG", run_tracking.STOP_AFTER_WRONG))
    unsupported_vision = requires_vision(task) and mcfg.get("supports_vision") is False
    had_error = False
    indices = getattr(args, "repeat_indices", None)
    runs = [int(i) for i in indices.split(",")] if indices else list(range(1, repeat + 1))
    if len(set(runs)) != len(runs) or any(i < 1 or i > repeat for i in runs):
        raise ValueError("Repeat indices must be distinct and within the saved repeat count")
    for run in runs:
        task_identity.verify(TASKS/args.task,{'task_sha':task_sha,'task_bundle_sha':task_bundle_sha})
        task,option_presentation=option_layout.prepare(original_task,run,task_bundle_sha,presentation_seed) if not evaluation_id or manifest.get('option_layout_policy')==option_layout.POLICY else (original_task,None)
        run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
        print(f"START {args.task} · {args.model} · repeat {run}/{repeat}", flush=True)
        started = time.time()
        checkpoint_path = os.environ.get('HOURGLASS_ATTEMPT_CHECKPOINT')
        attempt_state = {'task': args.task, 'run': run, 'run_id': run_id, 'started': started,
                         'workdir': None, 'provenance': {k: prov.get(k) for k in ('node', 'pi_version')}}
        question_deadline.checkpoint(checkpoint_path, attempt_state)
        workdir = None if unsupported_vision or early_stop else build(task)
        attempt_state['workdir'] = str(workdir) if workdir is not None else None
        if workdir is not None:attempt_state.update(diagnostics.descriptor(ROOT,workdir))
        question_deadline.checkpoint(checkpoint_path, attempt_state)
        if chart and not unsupported_vision and not early_stop:
            dst = workspace_path(workdir, task["image"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(TASKS / args.task / task["image"], dst)
        task_identity.verify(TASKS/args.task,{'task_sha':task_sha,'task_bundle_sha':task_bundle_sha})
        try:
            if unsupported_vision or early_stop:
                trace, parsed, disp_map = [], {}, None
                metrics = {"prompt_tokens": 0, "completion_tokens": 0, "tool_calls": 0, "duration_s": 0,
                           "score_reason": os.environ.get("HOURGLASS_SKIP_REASON") if early_stop else "unsupported_vision",
                           "termination": "not_attempted"}
            else:
                trace, metrics, parsed, disp_map = run_agent(task, mcfg, workdir, sandboxed)
        except Exception as e:
            trace = getattr(e, "trace", []) + [{"error": str(e)}]
            metrics = getattr(e, "metrics", {"prompt_tokens": 0, "completion_tokens": 0,
                         "tool_calls": 0, "duration_s": round(time.time()-started, 3)})
            if requires_vision(task) and is_unsupported_vision(e):
                unsupported_vision = True
                metrics["score_reason"] = "unsupported_vision"
                metrics["vision_detection"] = "endpoint_rejection"
            else:
                metrics["error"] = str(e)
            parsed, disp_map = {}, None
        extra = {}
        if metrics.get("error"):
            solved, vout, tampered = False, metrics["error"], []
            had_error = True
        elif early_stop:
            solved, vout, tampered = False, f"Not attempted: stopped after {stop_limit} consecutive incorrect questions; scored zero.", []
        elif unsupported_vision:
            solved, vout, tampered = False, "Vision unsupported: scored zero. " + ("Detected from endpoint rejection." if metrics.get("vision_detection") else "No model request needed."), []
        elif os.environ.get('HOURGLASS_SCORING_POLICY') == scoring_policy.WITH_ABSTENTION and parsed.get('abstain') is True:
            solved, vout, tampered = False, 'Explicit abstention: zero points.', []
            metrics.update(termination='abstained',score_reason='abstained')
        elif chart:
            solved, vout, tampered = score_chart(task, parsed, disp_map)
        elif task.get("kind") == "mcq":
            solved, vout, tampered, extra = score_mcq(task, parsed)
        else:
            solved, vout, tampered = verify(task, workdir, sandboxed)
        patch = "" if unsupported_vision or early_stop else subprocess.run(["git", "-C", str(workdir), "diff", "HEAD"],
                               capture_output=True, text=True).stdout
        rdir = RESULTS / args.task / urllib.parse.quote(args.model, safe="") / f"run-{run_id}"
        rdir.mkdir(parents=True, exist_ok=False)
        (rdir / "trace.json").write_text(json.dumps(trace, indent=1))
        if workdir is not None:diagnostics.publish(ROOT,workdir,rdir)
        (rdir / "patch.diff").write_text(patch)
        question_deadline_at = float(os.environ.get('HOURGLASS_QUESTION_DEADLINE_AT') or 0)
        if question_deadline_at and time.monotonic() >= float(os.environ['HOURGLASS_QUESTION_DEADLINE_MONOTONIC']) and not early_stop:
            metrics.pop('error', None)
            metrics.update(termination='question_timeout', score_reason='question_timeout', timeout_at=question_deadline_at)
            solved, vout = False, f"Question exceeded {float(os.environ['HOURGLASS_QUESTION_TIMEOUT_S']):g} seconds; zero points; continuing to the next question."
            had_error = False
        if question_deadline_at:
            metrics.update(question_timeout_s=float(os.environ['HOURGLASS_QUESTION_TIMEOUT_S']),
                           question_timeout_policy=question_deadline.POLICY,
                           question_started_at=float(os.environ['HOURGLASS_QUESTION_STARTED_AT']),
                           question_deadline_at=question_deadline_at)
        rec = {"task": args.task, "model": args.model, "run": run, "run_id": run_id,
               "evaluation_id": os.environ.get("HOURGLASS_EVALUATION_ID"), "stop_after_wrong": stop_limit, "model_config_hash": calibration.digest(mcfg),
               "benchmark_version": BENCHMARK_VERSION, "diagnostic_isolation": diagnostics.POLICY, "scoring_policy": os.environ.get('HOURGLASS_SCORING_POLICY',scoring_policy.LEGACY), "supports_vision": mcfg.get("supports_vision"),
               "artifact_dir": str(rdir.relative_to(ROOT)), "tier": task.get("tier", 1),
               "status": "timeout" if metrics.get("termination") == "question_timeout" else "error" if metrics.get("error") else "completed",
               "section": task.get("section"), "family": task.get("family"), "mode": task.get("mode"),
               "opt_n": len(task.get("options") or task.get("choices") or []) or None,
               "solved": solved, "tampered": tampered, "sandboxed": sandboxed,
               "kind": task.get("kind", "fix"), "node": prov.get("node"),
               "pi_version": prov.get("pi_version"), "task_sha": task_sha,
               "task_bundle_sha":task_bundle_sha,"option_presentation":option_presentation,
               "combo_hash": hashlib.sha256(f"{prov.get('node')}|{args.model}|{args.task}|{run_id}".encode()).hexdigest()[:12],
               "parsed_answer": parsed, "verified_output": vout,
               "patch_lines": patch.count(chr(10)), **metrics,
               "tok_per_s": round(metrics["completion_tokens"] / max(metrics["duration_s"], 0.001), 1),
               "ts": dt.datetime.now(dt.timezone.utc).isoformat()}
        rec.update(extra)
        if metrics.get("termination")=="turn_limit":rec["score_reason"]="turn_limit"
        import result_store
        result_store.commit(ROOT, rdir, rec)
        print(f"[{args.task} | {args.model} | repeat {run}] status={rec['status']} solved={solved} "
              f"time={metrics['duration_s']}s tools={metrics['tool_calls']} "
              f"tokens={metrics['prompt_tokens']}+{metrics['completion_tokens']}", flush=True)
        if metrics.get("error"):
            print("ERROR: " + metrics["error"], flush=True)
        if workdir is not None: shutil.rmtree(workdir, ignore_errors=True)
        if rec['status'] == 'timeout': break
    cmd_leaderboard(None,emit=not bool(os.environ.get('HOURGLASS_EVALUATION_ID')))
    cmd_frontier(None,emit=not bool(os.environ.get('HOURGLASS_EVALUATION_ID')))
    if had_error:
        raise SystemExit(1)

def _rows():
    path = RESULTS / "results.jsonl"
    if not path.exists(): return []
    out = []
    with path.open() as f:
        for line in f:
            try: out.append(json.loads(line))
            except Exception: pass
    return out

def cmd_leaderboard(_, rows=None, root=None, emit=True):
    rows = _rows() if rows is None else rows
    agg = {}
    for r in rows:
        if r.get("status") != "completed": continue
        a = agg.setdefault((r.get("benchmark_version", "unversioned"), r["task"], r["model"]),
                           {"n": 0, "solved": 0, "times": [], "tok": [], "tamp": 0, "skipped": 0, "temperatures": set()})
        a["n"] += 1; a["solved"] += bool(r["solved"])
        a["skipped"] += run_tracking.is_early_stop(r)
        a["times"].append(r.get("duration_s", 0)); a["tok"].append(r.get("completion_tokens", 0))
        a["tamp"] += len(r.get("tampered") or [])
        a["temperatures"].add(str(r["temperature"]) if r.get("temperature") is not None else ("server default (not reported)" if r.get("harness")=="pi" else "not recorded"))
    med = lambda xs: statistics.median(xs) if xs else 0
    lines = ["| version | task | model | runs | solved | early-stop skips | all recorded repeats pass (policy) | tamper | median time | median tok | temperature |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for (version, task, model), a in sorted(agg.items()):
        lines.append(f"| {version} | {task} | {model} | {a['n']} | {a['solved']} | "
                     f"{a['skipped']} | {'not fully observed' if a['skipped'] else ('✓' if a['solved'] == a['n'] else '✗')} | {a['tamp']} | "
                     f"{med(a['times'])}s | {med(a['tok'])} | {', '.join(sorted(a['temperatures']))} |")
    doc = "# Hourglass leaderboard\n\n" + hour_score.leaderboard(root or ROOT,rows) + ("## Full-run attempt diagnostics\n\n"
           "Early-stop skips are policy-defined zeros, not observed incorrect answers. "
           "The all-repeats indicator is withheld when skips are present; it is not a statistical pass^k estimate.\n\n") + "\n".join(lines) + "\n"
    ((root or ROOT) / "leaderboard.md").write_text(doc)
    if emit: print(doc)

def cmd_frontier(_, rows=None, root=None, emit=True):
    rows = [r for r in (_rows() if rows is None else rows) if r.get("status") == "completed"]
    if not rows:
        ((root or ROOT) / "frontier.md").write_text("# Hourglass frontier\n\nNo completed, scored runs yet.\n")
        if emit: print("No completed, scored runs yet.")
        return
    per_model = {}
    for r in rows:
        a = per_model.setdefault((r.get("benchmark_version", "unversioned"), r["model"]), {"solved": 0, "n": 0, "times": [], "tps": [],
                                              "tamp": 0, "tier_pts": 0, "tier_max": 0})
        a["n"] += 1; a["solved"] += bool(r["solved"])
        a["times"].append(r.get("duration_s", 0) or 0)
        a["tps"].append(r.get("tok_per_s", 0))
        a["tamp"] += len(r.get("tampered") or [])
        tier = r.get("tier", 1)
        if isinstance(tier, (int, float)) and not isinstance(tier, bool) and 0 <= tier < float("inf"):
            a["tier_pts"] += tier if r["solved"] else 0
            a["tier_max"] += tier
    stats = {}
    for model, a in per_model.items():
        times = [t for t in a["times"] if t]
        acc = a["solved"] / a["n"] if a["n"] else 0
        med_t = statistics.median(times) if times else 0
        tps = statistics.median(a["tps"]) if a["tps"] else 0
        thr = 3600 / med_t * acc if med_t else 0
        stats[model] = dict(acc=acc, med_t=med_t, tps=tps, thr=thr, n=a["n"],
                           solved=a["solved"], tamp=a["tamp"],
                           tier_yield=a["tier_pts"] / a["tier_max"] if a["tier_max"] else None)
    def dominates(x, y):   # x dominates y if >= on both axes and strictly better on one
        return (stats[x]["acc"] >= stats[y]["acc"] and stats[x]["thr"] >= stats[y]["thr"]
                and (stats[x]["acc"] > stats[y]["acc"] or stats[x]["thr"] > stats[y]["thr"]))
    for m in stats:
        stats[m]["frontier"] = not any(o[0] == m[0] and dominates(o, m) and o != m for o in stats)
    lines = ["| model | accuracy | median attempt time | output tokens / wall second | estimated solves/h | tier-yield | tamper | frontier |",
             "|---|---|---|---|---|---|---|---|"]
    for m, s in sorted(stats.items(), key=lambda kv: (-kv[1]["acc"], kv[1]["med_t"])):
        tier_label = f"{s['tier_yield']:.2f}" if s["tier_yield"] is not None else "—"
        lines.append(f"| {m[0]} · {m[1]} | {s['acc']:.2f} | {s['med_t']:.0f}s | {s['tps']} | {s['thr']:.2f} | "
                     f"{tier_label} | {s['tamp']} | {'★' if s['frontier'] else ''} |")
    doc = ("# Hourglass frontier — speed × accuracy on my hardware\n\n"
           "Pareto-optimal models (★) are non-dominated: no other model is both more accurate\n"
           "and faster (solved-tasks/hour). Your frontier is the answer to 'which model should run\nhere'.\n\n"
           "Tier-yield uses authored numeric tiers only; untiered questions still count in accuracy and timing.\n\n" + "\n".join(lines) + "\n")
    ((root or ROOT) / "frontier.md").write_text(doc)
    if not emit: return
    print(doc)
    # ascii scatter
    print("\naccuracy ↑ by median solve-time ↓:")
    for m, s in sorted(stats.items(), key=lambda kv: kv[1]["med_t"]):
        bar = "█" * int(round(s["acc"] * 30))
        print(f"{s['med_t']:>7.0f}s  {bar:<30}  {m} ({s['acc']:.0%})")

def cmd_intake_bundle(args):
    d = Path(args.dir).resolve()
    questions = [json.loads(l) for l in (d / "public" / "questions.jsonl").read_text().splitlines() if l.strip()]
    keys = json.loads((d / "private" / "answer-key.json").read_text())
    rep = {"intake": str(d), "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
           "errors": [], "ingested": 0}
    for q in questions:
        qid = q.get("id", "?")
        try:
            k = keys[qid]
        except Exception:
            rep["errors"].append(f"{qid}: no key"); continue
        mode = q.get("mode") or "option_id"
        tdir = TASKS / qid; (tdir / "verify").mkdir(parents=True, exist_ok=True)
        assets = []
        if q.get("image"):
            src = d / "public" / q["image"]
            if not src.exists(): rep["errors"].append(f"{qid}: image {q['image']} missing"); continue
            shutil.copy(src, tdir / "chart.png"); assets = ["chart.png"]
        task = {"id": qid, "kind": "mcq", "section": q.get("section"), "family": q.get("family"),
                "tier": q.get("tier"), "level": q.get("intended_level"), "title": q.get("title"),
                "mode": mode, "prompt": q["question"], "options": q.get("options") or [],
                "max_turns": 40, "repeat": 3, "shuffle": "order", "assets": assets,
                "provenance": {"bundle": str(d), "seeded": True},
                "verifier": {"commands": [], "forbidden": []}}
        if mode == "option_id":
            aid = str(k.get("answer"))
            ids = {o["id"] for o in task["options"]}
            if aid not in ids: rep["errors"].append(f"{qid}: answer {aid} not in options"); continue
            if len(task["options"]) < 2: rep["errors"].append(f"{qid}: <2 options"); continue
            texts = [o["text"] for o in task["options"]]
            if len(set(texts)) < len(texts): rep["errors"].append(f"{qid}: duplicate option texts")
            task["answer"] = aid
        else:
            tgt, tol = k.get("answer_value"), k.get("absolute_tolerance")
            if tgt is None or tol is None: rep["errors"].append(f"{qid}: numeric key incomplete"); continue
            task["target"], task["tolerance_abs"] = float(tgt), float(tol)
        (tdir / "task.json").write_text(json.dumps(task, indent=1))
        rep["ingested"] += 1
    (ROOT / "intake-report-bundle.json").write_text(json.dumps(rep, indent=1))
    print(f"ingested {rep['ingested']}/{len(questions)}; errors {len(rep['errors'])}")
    for e in rep["errors"][:12]: print(" ", e)

def cmd_escapetest(args):
    task = json.loads((TASKS / args.task / "task.json").read_text())
    wd = build(task)
    targets = [str(ROOT / "incoming/codex-charts/benchmark-200-v1/private/answer-key.json"),
               str(TASKS / "C001" / "task.json"), str(ROOT / "intake-report-bundle.json")]
    probes = []
    for t in targets:
        out, _ = run_bash(f"cat {shlex.quote(t)} 2>&1 | head -c 200", wd, sandboxed=True)
        blocked = (out.strip() == "" or "deny" in out.lower()
                   or "operation not permitted" in out.lower() or "permission" in out.lower())
        probes.append({"target": t, "blocked": bool(blocked), "sample": out[:140]})
    out, _ = run_bash("curl -s http://127.0.0.1:1234/v1/models 2>&1 | head -c 140", wd, sandboxed=True)
    probes.append({"target": "localhost inference API", "blocked":
                   (out.strip() == "" or "denied" in out.lower() or "err" in out.lower() or "fatal" in out.lower()),
                   "sample": out[:140]})
    shutil.rmtree(wd, ignore_errors=True)
    print(json.dumps(probes, indent=1))
    ok = all(p["blocked"] for p in probes)
    print("ISOLATION:", "PASS — private keys/generators/results unreadable, network denied" if ok else "FAIL — see sample fields")

def cmd_generate(args):
    tdir, vdir = TASKS / args.id, TASKS / args.id / "verify"
    tdir.mkdir(parents=True, exist_ok=True); vdir.mkdir(parents=True, exist_ok=True)
    repo = str(Path(args.repo).resolve())
    sha_ref = subprocess.run(["git", "-C", repo, "rev-parse", args.ref],
                             capture_output=True, text=True).stdout.strip()
    if not sha_ref: sys.exit(f"cannot resolve {args.ref} in {repo}")
    for t in (args.test or []):
        (vdir / Path(t).name).write_text((Path(repo) / t).read_text())
    muts = []
    for spec in (args.mutation or []):
        parts = spec.split("|", 2)
        if len(parts) != 3: sys.exit("--mutation must be file|find|replace")
        muts.append({"file": parts[0], "find": parts[1], "replace": parts[2]})
    task = {"id": args.id, "title": args.title or f"seeded defect {args.id}", "tier": args.tier,
            "repeat": args.repeat, "max_turns": args.max_turns,
            "source": {"repo": repo, "ref": args.ref, "sha": sha_ref},
            "exclude": args.exclude or [],
            "prompt": args.prompt or "A bug was introduced into this repository. Reproduce it, find the root cause, fix it properly, then call submit.",
            "mutation": muts or None,
            "verifier": {"commands": args.verify or ["python3 -m pytest -q tests_hidden"],
                         "forbidden": ["tests_hidden", ".hourglass-integrity.json"]}}
    (tdir / "task.json").write_text(json.dumps(task, indent=1))
    print(f"created tasks/{args.id}/task.json + hidden verify/{', '.join(Path(t).name for t in (args.test or [])) or '(none)'})")
    print(f"next: python3 hourglass.py cert {args.id}")

def cmd_intake(args):
    d = Path(args.dir).resolve()
    man = json.loads((d / "manifest.json").read_text())
    if man.get("bundle") != "chart-vqa": sys.exit(f"manifest bundle={man.get('bundle')} not chart-vqa")
    rows = [json.loads(l) for l in (d / "challenges.jsonl").read_text().splitlines() if l.strip()]
    certified = 0
    for ch in rows:
        tid, tdir = ch["id"], TASKS / ch["id"]
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "verify").mkdir(exist_ok=True)
        (tdir / "chart.png").write_bytes((d / ch["chart"]).read_bytes())
        # re-certify: re-run the deterministic gen script; truth must agree with the claimed answer
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, HOURGLASS_PNG_OUT=str(Path(td) / "o.png"),
                       HOURGLASS_TRUTH_OUT=str(Path(td) / "t.json"))
            subprocess.run(["python3", str(d / ch["gen"])], env=env, capture_output=True, text=True)
            tp, truth = Path(td) / "t.json", {}
            if tp.exists(): truth = json.loads(tp.read_text())
        mode = ch.get("mode", "letter")
        if mode == "numeric":
            tval, aval = truth.get("value"), ch.get("answer_value")
            cert_ok = tval is not None and aval is not None and abs(tval - aval) <= abs(aval) * 1e-3 + 1e-9
        else:
            cert_ok = truth.get("answer") == ch.get("answer")
        shutil.copy(d / ch["gen"], tdir / "verify" / Path(ch["gen"]).name)
        (tdir / "verify" / "truth.json").write_text(json.dumps(
            {"answer": ch.get("answer"), "value": ch.get("answer_value"), "question": ch["question"]}))
        task = {"id": tid, "kind": "chart-vqa", "title": f"{ch.get('family','chart')} t{ch.get('tier')}",
                "tier": ch.get("tier", 1), "repeat": 3, "image": "chart.png",
                "prompt": ch["question"], "choices": ch["choices"], "answer": ch.get("answer"),
                "answer_value": ch.get("answer_value"), "tolerance_pct": ch.get("tolerance_pct", 5),
                "mode": mode, "shuffle": True, "family": ch.get("family"),
                "provenance": {"generator": "codex", "bundle": str(d), "seeded": True},
                "verifier": {"commands": [], "forbidden": []}}
        (tdir / "task.json").write_text(json.dumps(task, indent=1))
        certified += int(cert_ok)
        print(f"[{tid}] tier{ch.get('tier')} {ch.get('family')}: regen-cert={'OK' if cert_ok else 'MISMATCH — excluded from scoring'}")
    print(f"intake: {len(rows)} challenges ingested, {certified} certified")
    print("run e.g.  python3 hourglass.py run chart-001 --model <name> --config models.json")

def main():
    ap = argparse.ArgumentParser(prog="hourglass")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("cert"); p.add_argument("task"); p.set_defaults(fn=cert)
    g = sub.add_parser("generate")
    g.add_argument("id"); g.add_argument("--repo", required=True); g.add_argument("--ref", default="HEAD")
    g.add_argument("--test", nargs="+"); g.add_argument("--mutation", action="append")
    g.add_argument("--exclude", nargs="*"); g.add_argument("--verify", nargs="+")
    g.add_argument("--tier", type=int, default=2); g.add_argument("--repeat", type=int, default=3)
    g.add_argument("--max-turns", type=int, default=40)
    g.add_argument("--title"); g.add_argument("--prompt")
    g.set_defaults(fn=cmd_generate)
    r = sub.add_parser("run"); r.add_argument("task"); r.add_argument("--model", required=True)
    r.add_argument("--repeat", type=int); r.add_argument("--config"); r.add_argument("--no-sandbox", action="store_true")
    r.add_argument("--repeat-indices", help=argparse.SUPPRESS)
    r.set_defaults(fn=cmd_run)
    i = sub.add_parser("intake"); i.add_argument("dir"); i.set_defaults(fn=cmd_intake)
    b = sub.add_parser("intake-bundle"); b.add_argument("dir"); b.set_defaults(fn=cmd_intake_bundle)
    e = sub.add_parser("escapetest"); e.add_argument("task"); e.set_defaults(fn=cmd_escapetest)
    sub.add_parser("probe", help="capture machine/servers/pi provenature").set_defaults(fn=cmd_probe)
    sub.add_parser("leaderboard").set_defaults(fn=cmd_leaderboard)
    sub.add_parser("frontier").set_defaults(fn=cmd_frontier)
    args = ap.parse_args()
    if args.cmd == "run":
        import fcntl
        with (ROOT / ".run.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit("Another Hourglass run is active. Wait for it to finish; single-stream execution is enforced.")
            from run_guard import WorkerGuard
            with WorkerGuard(ROOT):
                args.fn(args)
    else:
        args.fn(args)

if __name__ == "__main__":
    import os  # noqa: E402 (used by run_bash fallback path)
    main()
