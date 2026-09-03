"""
Run harness for the SimSkill efficacy experiments (test/experiments.md §4, §6 item 2).

For one (condition, model) pair — one or many tasks (§9.2, or `--all-tasks`) and one or
many repeats (`--repeats`, §5 Statistical Concerns) — this script creates exactly ONE
worktree and runs everything requested inside it, since condition/model don't change
across tasks or repeats and worktree creation is the expensive part worth not repeating.


## Steps
  1. create a disposable git worktree (never the main repo checkout) — once, up front;
  2. apply the condition's memory manipulation (memory_ops.py, per conditions.yaml) —
     once, right after;
  3. write a per-worktree settings file for the chosen backbone LLM (models.yaml) — once;
  4. then, for every (repeat, task) pair in turn: invoke `claude -p` non-interactively
     and capture its JSON result;
  5. pick up whatever `infer` wrote to the worktree's own episodic-memory/ (self-reported
     success, attempts, skills_used, knowledge_used) for that (repeat, task) — see the note
     below on why this is *not* truncated to skip that write-back;
  6. independently verify that self-report (the `verify` skill, test/experiments.md-driven)
     via a SECOND, separate `claude -p` process run from its own dedicated worktree — never
     the worktree under test, never the main checkout — so the check shares no session/
     context with the run it's checking and stays reachable even under conditions that strip
     CLAUDE.md from their own worktree (e.g. `verification` condition). This verdict, not the
     self-report, becomes the authoritative `success` field (unless --no-verify);
     (Verification worktree only provides pure execution environment, zero durable state of 
     its own; outputs are written to the main project repo's `test/results/verify/` folder.
  7. run the §3.2 cost/time instrumentation (cost_time.py) for that (repeat, task);
  8. write test/results/<run_id>.json for that (repeat, task);
  9. once every repeat and task is done, tear both worktrees down (unless --keep-worktree).

On contamination control (test/experiments.md §2): a benchmark task must never pollute
real memory. This harness achieves that by construction — the worktree is disposable and
is never merged, pushed, or otherwise reconciled with the main checkout — rather than by
asking `infer` to skip its own steps 6-7. Letting `infer` run its natural, complete course
(including its own memory-ingest, into the worktree's own throwaway copy) is more faithful
to how `infer` actually behaves than truncating it, and costs nothing in contamination
safety since the whole worktree is discarded afterward.

This script deliberately runs unattended (no TTY to prompt on), so by default it passes
--dangerously-skip-permissions. Every run happens inside a disposable worktree, which is
the actual safety boundary here, not the permission prompt.


## Usage
```
# one task, one condition, one model, one repeat
python test/harness/run_experiment.py --condition full-ver\
    --model claude-opus-5 --verify-model claude-opus-5 \
    --task-id NG-T1 --keep-worktree

# same condition/model, multiple tasks in one resumed session (warm cache, §3.2.1):
python test/harness/run_experiment.py --condition full-ver\
    --model claude-opus-5 --verify-model claude-opus-5 \
    --task-ids NG-T1,NG-T2,NG-T3 --cache-mode warm --keep-worktree

# every task in test/benchmark_tasks.yaml, in file order:
python test/harness/run_experiment.py --condition full-ver --model claude-opus-5 \
    --all-tasks --keep-worktree

# every task, run 3 times each, all inside this one worktree (§5's n=3 repeats):
python test/harness/run_experiment.py --condition full-ver --model claude-opus-5 \
    --all-tasks --repeats 3 --keep-worktree

# inspect what would happen without spending anything or touching git:
python test/harness/run_experiment.py --condition full-ver --model claude-opus-5 \
    --task-id NG-T1 --dry-run
```    
    
    
## Agent running foreground vs background
NOTE: run subagents in the foreground when driven via `claude -p`.

"Foreground" vs "background" refers to the run_in_background parameter on the Agent tool call itself — it controls 
whether spawning action-agent blocks until it finishes, or returns immediately and lets the sub-agent keep working while 
the caller moves on.

- Background (the default): the Agent tool call returns right away, before action-agent has produced anything. The orchestrating 
model's turn ends there. Whenever action-agent eventually finishes, its result gets delivered 
as a separate, later turn — like a callback/notification — and the model has to be "woken up" again to see it and react.

- Foreground (run_in_background: false): the Agent tool call blocks — the orchestrator's turn doesn't complete until 
action-agent is fully done, and its result comes back as the direct return value of that same tool call, within the same turn. It 
behaves like an ordinary synchronous function call: call it, wait, get the value back, keep going.
Why it matters here: infer step 4 needs action-agent's actual output to invoke critic-agent. With background execution, that 
dependency has to be satisfied by the later-turn notification mechanism — which works fine in an interactive session (a human 
keeps things alive long enough for the notification to land and resume the model), but apparently doesn't get looped back into the 
model's reasoning at all inside a single non-interactive claude -p invocation. Foreground sidesteps that entirely: the orchestrator 
just doesn't proceed until it has the result in hand, so there's no "later turn" to depend on.

Affected skills:
 - infer: step 3
 - learn: step 3
 - memory-merge
 
 
## Naming Conventions
worktree_root: the root of the worktree where the task is being run
If automatically generated by `make_batch_id()`, format:
    f"{ts}_{condition}_{model}_{task_label_for_naming(task_ids)}_{uuid.uuid4().hex[:6]}"
But usually we assign them manually, like:
    "full-ver_claude-haiku-4-5"
In this case, to avoid repetitions, we should remove them before re-running.

run_id: a unique identifier for a task run
generated automatically by `make_run_id()`; format:
    f"{ts}_{condition}_{model}_{task_id}_r{repeat}_{uuid.uuid4().hex[:6]}"
This run id is used a lot.

session_id: claude code session id; generated by `uuid.uuid4()`

episode memory folder name: datetime like:
    "2026-07-21_18-35-42"

result json file: 
    f"{run_id}.json"

stdout file: 
    f"{run_id}.stdout.log"
    
stderr file: 
    f"{run_id}.stderr.log"
    
    
## Path Usage conventions
- For path variables, we pass absolution Path objects by default. 
    If we want to pass str, we "_str" suffix explicitly for the path variable name.
    If we want to pass relative path, we "_rel" suffix explicitly for the path variable name.
- For dictionary variables used for storage, like `results`, we store abs paths strings


## LLM Configuration
Note: spawn process will inherit the environment of the parent process!
Writing a worktree settings file is not sufficient isolation because it cannot unset
provider/model variables omitted by the selected configuration.  Every Claude subprocess
therefore receives a sanitized environment from `build_llm_subprocess_env`, plus the
selected models.yaml entry, and an explicit worktree settings file when that entry has
environment overrides.

    Main Claude Code session
      loads main repo .claude/settings.local.json
      exports ANTHROPIC_* variables for the session
            ↓ inherited by Bash subprocess
    python run_experiment_1.py / verify.py
            ↓ inherited by Python subprocess
    claude -p, with cwd=verify worktree

env values originally loaded from the main repository:
ANTHROPIC_BASE_URL
ANTHROPIC_AUTH_TOKEN
ANTHROPIC_MODEL
ANTHROPIC_DEFAULT_OPUS_MODEL
ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL
CLAUDE_CODE_SUBAGENT_MODEL
CLAUDE_CODE_EFFORT_LEVEL
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import json
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_time  # module to compute cost and time metrics from CLAUDE JSON output
import memory_ops  # module to manage memory operations in the worktree

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = Path(__file__).resolve().parent
DEFAULT_BENCHMARK = REPO_ROOT / "test" / "benchmark_tasks.yaml"
DEFAULT_RESULTS_DIR = REPO_ROOT / "test" / "results"  
# NOTE: default location to store the results
# NOTE: this is the repo's result folder; shared by all worktrees!
DEFAULT_WORKTREE_ROOT = REPO_ROOT.parent / f"{REPO_ROOT.name}-experiments"  # NOTE: all worktrees live at `../<repo-name>-experiments/`
VERIFY_CONDITION_NAME = "verification"
VERIFY_PROMPT_TEMPLATE = REPO_ROOT / "test" / "harness" / "verify_prompt_template.txt"

# Claude Code settings can inject provider/model values into the current process.  Any
# Python/Claude subprocess launched from that session inherits those values unless the
# harness removes them explicitly.  Keep unrelated environment variables (PATH, SUMO_HOME,
# etc.) while clearing only LLM selection/routing values before applying the selected
# models.yaml entry.
LLM_ENV_KEYS_TO_CLEAR = {
    "CLAUDE_CODE_EFFORT_LEVEL",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
    "CLAUDE_CODE_MAX_THINKING_TOKENS",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_VERTEX",
}

def load_yaml(path: Path) -> dict:
    """Load a YAML file"""
    with open(path) as f:
        return yaml.safe_load(f)


def find_task(benchmark: dict, task_id: str) -> dict:
    for task in benchmark["tasks"]:
        if task["id"] == task_id:
            return task
    raise KeyError(f"task_id '{task_id}' not found in {DEFAULT_BENCHMARK}")


def build_llm_subprocess_env(model_config: dict) -> dict[str, str]:
    """Return a child environment containing only the selected LLM configuration.

    Project ``settings.local.json`` values may already be present in ``os.environ`` when
    this harness is started from a Claude Code Bash process.  A worktree-local settings
    file cannot reliably *unset* inherited values that its model config omits, so remove
    all Anthropic provider/model variables and the known Claude Code model selectors first,
    then apply exactly ``model_config['env']``.
    """
    child_env = os.environ.copy()
    for key in list(child_env):
        if key.startswith("ANTHROPIC_") or key in LLM_ENV_KEYS_TO_CLEAR:
            child_env.pop(key, None)
    child_env.update({str(key): str(value) for key, value in (model_config.get("env") or {}).items()})
    return child_env


def redacted_model_config(model_config: dict) -> dict:
    """Return a display-safe model config for logs and dry-run output."""
    safe = dict(model_config)
    sensitive_fragments = ("KEY", "TOKEN", "SECRET", "PASSWORD")
    safe["env"] = {
        key: "<redacted>" if any(fragment in key.upper() for fragment in sensitive_fragments) else value
        for key, value in (model_config.get("env") or {}).items()
    }
    return safe


# ========== Run ID and Batch ID generation ==========
def make_run_id(condition: str, model: str, task_id: str, repeat: int) -> str:
    """A run is one invocation of `claude -p` on one task, inside one worktree. 
    This is the unique identifier for that invocation, and is used as the filename 
    for its JSON result.
    Each run will create some files, and they will have run id identifier; and 
    the whole project folder will have batch id identifier as name.
    Example:
    So for one worktree running --all-tasks --repeats 3 over the 40-task benchmark, you'd get:
    - 1 worktree folder, named by that pair's single batch_id
    - 120 result files in test/results/ (40 tasks × 3 repeats), each named by its own run_id
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{condition}_{model}_{task_id}_r{repeat}_{uuid.uuid4().hex[:6]}"


def make_batch_id(condition: str, model: str, task_ids: list) -> str:
    """batch_id is the unique identifier for a batch of runs, and is used as the
    directory name for the worktree they create — spans every task AND every
    repeat run inside it, so (unlike make_run_id) it deliberately carries no repeat
    number of its own."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{condition}_{model}_{task_label_for_naming(task_ids)}_{uuid.uuid4().hex[:6]}"


def task_label_for_naming(task_ids: list) -> str:
    """Utility to make a label for a task batch
    A worktree/batch directory name built from every task id is unreadable (and can
    hit path-length limits) once --all-tasks is in play — collapse to a count instead
    once there are more than a few."""
    if len(task_ids) <= 3:
        return "+".join(task_ids)
    return f"{len(task_ids)}tasks"



# ========== Worktree management ==========
def create_worktree(worktree_path: Path, ref: str = "HEAD") -> None:
    """Create a new git worktree at the specified path before running any tasks. 
    The worktree is detached at the given ref (default HEAD)."""
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree_path), ref],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

def remove_worktree(worktree_path: Path) -> None:
    """Remove a worktree after use if not --keep-worktree."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )



# ========== Write LLM settings for a worktree ==========
def write_worktree_settings(worktree_path: Path, model_config: dict) -> Optional[Path]:
    """Write the selected model environment as authoritative worktree settings.

    Remove a stale settings file when the selected model has no environment overrides;
    this matters when ``--continue`` reuses a worktree after configuration changes.
    """
    env = model_config.get("env") or {}
    settings_path = worktree_path / ".claude" / "settings.local.json"
    if not env:
        if settings_path.exists():
            settings_path.unlink()
        return None
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"env": env}, indent=2))
    return settings_path




# ========== Independent post-hoc verification (the `verify` skill) ==========
def build_verify_prompt(
    task_id: str,
    task_text: str,
    episodic_path_str: str,
    verify_result_path_str: str,
) -> str:
    """Builds the prompt for the verification session. Every path passed is absolute —
    this session's cwd is a *different* worktree than the one it's inspecting, so a
    relative path would be meaningless (or worse, silently resolve to the wrong file)."""
    verify_prompt_template = VERIFY_PROMPT_TEMPLATE.read_text(encoding="utf-8")
    verify_prompt = verify_prompt_template.format(
        task_id=task_id,
        task_text=task_text,
        episodic_path=episodic_path_str,
        verify_result_path=verify_result_path_str,
    )
    
    """alternative prompt: use /verify skill
    verify_prompt = (
        "(Use /verify) Independently verify whether one traffic-simulation task has been successfully accomplished. You are running "
        "in a separate, freshly-checked-out worktree with no session history from the run being checked — treat it that way."
        "\n\n"
        f"task_id: {task_id}\n"
        f"Task (verbatim): {task_text}\n"
        f"Episodic path: {episodic_path_str}\n"
        f"Verification result file: {verify_result_path_str}\n"
    )
    """
    return verify_prompt

def build_verify_command(
    prompt: str,
    verify_model_config: dict,
    verify_settings_path: Optional[Path],
    max_budget_usd: Optional[float],
    skip_permissions: bool,
) -> list:
    """Build the command to verify the simulation task execution result."""
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--no-session-persistence"]

    verify_model_flag = verify_model_config.get("claude_model_flag")
    if verify_model_flag:
        cmd += ["--model", verify_model_flag]
    if verify_settings_path is not None:
        cmd += ["--settings", str(verify_settings_path)]

    if max_budget_usd:
        cmd += ["--max-budget-usd", str(max_budget_usd)]
    if skip_permissions:
        cmd += ["--permission-mode", "bypassPermissions", "--dangerously-skip-permissions"]
    return cmd


def run_verification(
    *,
    run_id: str,
    results_dir: Path,  # results directory; absolute path; path obj
    task_id: str,  # verification prompt input
    task_text: str,  # verification prompt input
    episodic_path_str: str,  # episodic memory record folder; absolute path; str
    verify_result_path_str: str,  # file to store the verification result; absolute path; str
    verify_worktree_path: Path,  # worktree to do verification; absolute path; path obj
    verify_model_config: dict,
    verify_settings_path: Optional[Path],
    max_budget_usd: Optional[float],
    skip_permissions: bool,
    self_reported_success: bool,
) -> dict:
    """Launches a SECOND, independent `claude -p` process from a dedicated
    ``verification`` condition worktree — never the worktree that ran the task (which may have memory/skills stripped
    per condition, and whose model has every incentive to believe its own work), and never
    the main checkout (--dangerously-skip-permissions must never run against the user's real
    working tree). Returns the `verify` skill's own output dict, or a dict with
    verified_success=None plus a warning if that skill didn't produce one.

    Args:
        run_id: the run's id.
        results_dir: main repo results directory.
        task_id: this task's id.
        task_text: the original task text, verbatim — passed through so the verifier checks
            against the actual spec, not whatever a summary.md happened to record.
        episodic_path_str: the path of the task's episodic record.
        verify_result_path_str: the path to write the verification result to.
        verify_worktree_path: the dedicated ``verification`` condition worktree the verification
            session itself runs from — never target_worktree_path, never the main checkout.
        verify_model_config: resolved models.yaml entry selected by --verify-model,
            deliberately independent of the model under test.
        verify_settings_path: verifier worktree's settings.local.json, or None when the
            selected model has no environment overrides.
        max_budget_usd: optional per-call budget cap, forwarded to `claude -p --max-budget-usd`.
        skip_permissions: whether to pass --dangerously-skip-permissions (required for any
            non-interactive claude -p call; safe here since it's scoped to the disposable
            verify worktree, never the user's real checkout).
    """
    prompt = build_verify_prompt(
        task_id=task_id,
        task_text=task_text,
        episodic_path_str=episodic_path_str,
        verify_result_path_str=verify_result_path_str,
    )
    cmd = build_verify_command(
        prompt=prompt,
        verify_model_config=verify_model_config,
        verify_settings_path=verify_settings_path,
        max_budget_usd=max_budget_usd,
        skip_permissions=skip_permissions,
    )
    # --------------------------------------------
    # run the verification
    # --------------------------------------------
    if self_reported_success is not None:
        proc = subprocess.run(
            cmd,
            cwd=verify_worktree_path,
            env=build_llm_subprocess_env(verify_model_config),
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            verify_raw_result = json.loads(proc.stdout)
            print(
                "\n  [Verification LLM usage]",
                json.dumps(verify_raw_result.get("modelUsage", {}), indent=2),
            )
        except json.JSONDecodeError:
            print("\n  [Verification LLM usage] unavailable")
        
        # write raw output
        write_raw_output(f"{run_id}.verify", {"stdout": proc.stdout, "stderr": proc.stderr}, results_dir)
    else:
        print("\n  [Verification] task not successful executed; verification LLM call skipped")
        # task not successful executed
        # we still create an empty files
        write_raw_output(f"{run_id}.verify", {"stdout": "", "stderr": ""}, results_dir)
    
    # prepare empty verdict
    empty = {
        "verified_success": None,
        "self_reported_success": None,
        "agreement": None,
        "episodic_record_found": None,
        "critique": None,
    }
    
    # check verification output
    verify_result_path = Path(verify_result_path_str)
    if not verify_result_path.exists():
        if self_reported_success is not None:
            empty["warnings"] = [
                f"verify skill did not write {verify_result_path} — verification subprocess "
                f"returncode={proc.returncode}; see raw/{run_id}.verify.stdout.log"
            ]
        else:
            empty["warnings"] = [
                f"task execution unsuccessful; verification not performed"
            ]
        return empty
    try:
        #if verify_result_path.is_file():
        verdict = json.loads(verify_result_path.read_text())
        """deprecated
        elif verify_result_path.is_dir():
            # mkdir(parents=True) above turns the intended file path into a directory;
            # the verify skill may have written a file inside it. If there's exactly
            # one file, parse it; otherwise warn and return an empty verdict.
            entries = [p for p in verify_result_path.iterdir() if p.is_file()]
            if len(entries) == 1:
                verdict = json.loads(entries[0].read_text())
            else:
                empty["warnings"] = [
                    f"verify_result_path {verify_result_path} is a directory with "
                    f"{len(entries)} file(s); expected exactly 1 file"
                ]
                return empty
    
        else:
            empty["warnings"] = [
                f"check whether verify skill wrote {verify_result_path}; cannot parse this path"
            ]
            return empty
            """
    except Exception as exc:  # NOTE: catch any type of error
        empty["warnings"] = [f"verify output at {verify_result_path} is not valid JSON:\n{exc}"]
        return empty
    verdict.setdefault("warnings", [])
    
    return verdict



# ========== Handle episodic memory ==========
def parse_frontmatter(path: Path) -> dict:
    """Parse frontmatter from a file with YAML frontmatter into a dict."""
    text = path.read_text()
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    return yaml.safe_load(parts[1]) or {}


def find_new_episodic_record(worktree_path: Path, run_start: float) -> Optional[dict]:
    """
    We only make use of episodic memory's summary.md files, and we only care about the
    most recent one. And we only read the summary.md's frontmatter.
    
    NOTE: we get the episodic memory of a task run by finding the newest episodic memory.
    If we run multiple task within one worktree, this may results in error!!
    For parallel version of this script, we can only parallel in  worktree level!!
    
    Locates whichever episodic-memory/<timestamp>/summary.md was written *during*
    this invocation (mtime after run_start), and returns its parsed frontmatter — this
    is where infer's own success/attempts/skills_used/knowledge_used already live, per
    CLAUDE.md's episodic memory record format.
    
    Args:
        worktree_path: the worktree the task actually ran in — what the verifier inspects.
        run_start: the time this run started, used to find the most recent summary.md.
    
    Returns:
        newest: the newest summary.md's path.
        frontmatter (dict): A dict of the summary.md's frontmatter, or None if no summary.md was written
        during this run.
    """
    episodic_dir = worktree_path / "episodic-memory"
    if not episodic_dir.is_dir():
        print("No episodic memory found in worktree")
        return None, None
    candidates = []
    for summary_path in episodic_dir.glob("*/summary.md"):
        if summary_path.stat().st_mtime >= run_start - 1:  # 1s slack for fs clock granularity
            candidates.append(summary_path)
    if not candidates:
        # Distinguish "nothing happened" from "a record folder exists for this run but
        # summary.md never got written into it" — e.g. infer wrote attempts/attempt-1/...
        # then crashed/got cut off before the final summary write. A directory's mtime
        # updates when a child is added, so this catches folders touched during this run
        # even without summary.md landing in them.
        new_dirs_without_summary = [
            d for d in episodic_dir.iterdir()
            if d.is_dir() and d.stat().st_mtime >= run_start - 1 and not (d / "summary.md").exists()
        ]
        if new_dirs_without_summary:
            print(
                "episodic-memory record folder(s) created for this run, but summary.md is "
                f"missing from: {[str(d.relative_to(worktree_path)) for d in new_dirs_without_summary]}"
            )
        else:
            print("No new episodic memory found in worktree")
        return None, None
    newest = max(candidates, key=lambda p: p.stat().st_mtime)  # path to summary.md; absolute path; path obj
    frontmatter = parse_frontmatter(newest)
    frontmatter["_summary_path"] = str(newest)  # path to summary.md; absolute path; str
    # `frontmatter` is a dict
    # NOTE: the path of episodic memory summary
    # we add this new field to the frontmatter of episodic memory summary
    return newest, frontmatter




# ========== Run one task using claude code in the newly created worktree ==========
def build_claude_command(
    task_text: str,
    model_config: dict,
    condition: dict,
    settings_path: Optional[Path],
    session_id: Optional[str],
    resume: bool,
    max_budget_usd: Optional[float],
    skip_permissions: bool,
) -> list:
    # Deliberately NOT --no-session-persistence: that flag suppresses the session's JSONL
    # transcript entirely (confirmed empirically — a session run with it leaves zero trace
    # anywhere under ~/.claude/projects/, not even a directory), which both makes
    # agent_vs_simulation_split's transcript-based split permanently unavailable and almost
    # certainly breaks --cache-mode warm's --resume (nothing gets persisted to resume from).
    cmd = ["claude", "-p", task_text, "--output-format", "json"]
    if model_config.get("claude_model_flag"):
        cmd += ["--model", model_config["claude_model_flag"]]
    if settings_path is not None:
        cmd += ["--settings", str(settings_path)]
    if condition.get("safe_mode"):
        cmd += ["--safe-mode"]
    if session_id:
        if resume:
            cmd += ["--resume", session_id]
        else:
            cmd += ["--session-id", session_id]
    if max_budget_usd:
        cmd += ["--max-budget-usd", str(max_budget_usd)]
    if skip_permissions:
        cmd += ["--permission-mode", "bypassPermissions", "--dangerously-skip-permissions"]
    return cmd


def invoke_one_task(
    *,
    worktree_path: Path,
    task: dict,
    model_key: str,
    model_config: dict,
    condition: dict,
    settings_path: Optional[Path],
    session_id: str,
    resume: bool,
    max_budget_usd: Optional[float],
    skip_permissions: bool,
) -> dict:
    """Runs one task against an already-prepared worktree and returns a raw
    (not yet cost/time-annotated) result dict. Shared by single-task and batch modes.

    Args:
        worktree_path: the already-created, condition-applied worktree to run in; also
            `claude`'s cwd for this invocation.
        task: the task record from benchmark_tasks.yaml (id, task text, category, tier).
        model_key: key into models.yaml (e.g. "claude-haiku-4-5") — carried through to the
            returned dict for annotate_with_cost_time, not used to build the command itself
            (that's model_config's job).
        model_config: the resolved models.yaml entry for model_key — supplies
            claude_model_flag and whatever env overrides settings_path was written from.
        condition: the resolved conditions.yaml entry for this run — read here for
            strip_system_skills (decides whether to say "(use /infer in test mode)" or ask
            the task itself to save episodic memory) and safe_mode.
        settings_path: path to the worktree's .claude/settings.local.json if model_config
            needed one written (write_worktree_settings), else None.
        session_id: the UUID this call uses for --session-id/--resume — minted by the caller,
            not by Claude Code, so find_transcript_path can look it up afterward.
        resume: whether to pass session_id via --resume (warm cache, reusing an existing
            session) instead of --session-id (a fresh one).
        max_budget_usd: optional per-call budget cap, forwarded to --max-budget-usd.
        skip_permissions: whether to pass --permission-mode bypassPermissions
            --dangerously-skip-permissions (required for any non-interactive run).
    """
    # ===== Prepare the CLAUDE command =====
    task_text = task["task"]
    # NOTE: if you want to add some extra info to all tasks, you can do it here
    if condition['strip_system_skills'] is False:
        task_text = f"(use /infer in test mode) {task_text}"
        task_text += "\n\nSave this simulation experience to episodic memory following the episodic memory record format defined in `episodic-memory-record-format.md`."
        # here we explicitly invoke infer skill and run it in test mode, so that 
        # inference results will not be added to the procedural and semantic memory
        # NOTE: be careful about using ":" - it means input to the skill
        # you may get error like:
        # ⏺ Unknown command: /infer
        # ⏺ Args from unknown skill: in test mode: Build a single 4-legged intersection in SUMO with traffic-light control on all approaches, each approach 2 lanes wide with a 300 m link length.
    else:
        # else, we need to manually ask Claude code to save episodic memory
        task_text = f"{task_text}/n/nSave this simulation experience to episodic memory following the episodic memory record format defined in `episodic-memory-record-format.md`."
    
    cmd = build_claude_command(
        task_text=task_text,
        model_config=model_config,
        condition=condition,
        settings_path=settings_path,
        session_id=session_id,
        resume=resume,
        max_budget_usd=max_budget_usd,
        skip_permissions=skip_permissions,
    )

    run_start_wall = time.time()
    start_dt = datetime.now(timezone.utc)
    
    # ===== here we run the task, and then measure the wall-clock time it took =====
    # Note we need to change directory to worktree_path before running claude
    proc = subprocess.run(
        cmd,
        cwd=worktree_path,
        env=build_llm_subprocess_env(model_config),
        capture_output=True,
        text=True,
        check=False,
    )
    
    end_dt = datetime.now(timezone.utc)
    wall_ms_measured = int((time.time() - run_start_wall) * 1000)

    raw_result: dict = {}
    parse_error = None
    try:
        raw_result = json.loads(proc.stdout)
        print(
            "\n  [Task LLM usage]",
            json.dumps(raw_result.get("modelUsage", {}), indent=2),
        )
    except json.JSONDecodeError as exc:
        parse_error = str(exc)

    # ===== find the episodic record generated by CLAUDE =====
    episodic_summary, episodic = find_new_episodic_record(worktree_path, run_start_wall)
    if episodic_summary:
        episodic_path = episodic_summary.parent
        episodic_path_str = str(episodic_path)  # episodic memory record folder; absolute path; str
    else:
        episodic_path = None
        episodic_path_str = None

    # ===== return the raw result, plus some metadata about the run (timestamps, wall-clock time, return code, etc.) =====
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,  # full, untruncated — this is what --output-format json actually printed
        "stderr": proc.stderr,  # full, untruncated
        "raw_result": raw_result,
        "raw_stdout_parse_error": parse_error,
        "start_time_utc": start_dt.isoformat(),
        "end_time_utc": end_dt.isoformat(),
        "wall_clock_ms_measured": wall_ms_measured,
        "episodic_path": episodic_path_str,  # episodic memory record folder; absolute path; str
        "episodic_record": episodic,  # this is the episodic memory record content (by loading yaml; you can find episodic summary path here)
        "task": task,
        "model_key": model_key,
    }



# ========== Annotate claude code raw result with cost/time information ==========
def _coerce_verification_verdict(value) -> Optional[bool]:
    """Convert a verifier verdict to a boolean without guessing from substrings.

    ``verified_success`` is specified to be a JSON boolean.  Some verifier models
    instead emit a short status string (occasionally under ``verdict``), so accept a
    small set of unambiguous aliases as a compatibility fallback.  Unknown or
    ambiguous statuses stay unverified rather than being silently counted as either
    success or failure.
    """
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None

    normalized = " ".join(
        value.strip().lower().replace("_", " ").replace("-", " ").split()
    )
    successful = {
        "success",
        "successful",
        "pass",
        "passed",
        "confirmed",
        "true",
        "accomplished",
        "complete",
        "completed",
        "accept",
        "accepted"
    }
    unsuccessful = {
        "failure",
        "failed",
        "fail",
        "false",
        "not confirmed",
        "unsuccessful",
        "not successful",
        "not accomplished",
        "incomplete",
        "partial success",
        "partially successful",
        "reject",
        "rejected"
    }
    if normalized in successful:
        return True
    if normalized in unsuccessful:
        return False
    return None


def resolve_verification_result(
    verify_result: dict, self_reported_success: Optional[bool]
) -> tuple[Optional[bool], Optional[bool], list]:
    """Resolve a verifier payload into success, agreement, and warnings.

    This is shared by the in-experiment and post-hoc verification paths so both
    interpret schema-compliant booleans and compatibility ``verdict`` strings in
    exactly the same way.
    """
    verify_warnings = list(verify_result.get("warnings") or [])

    # The schema-defined boolean is authoritative, including an explicit False.
    # A short textual verdict is only a compatibility fallback for verifier models
    # that did not follow the output schema.
    direct_value = verify_result.get("verified_success")
    direct_success = _coerce_verification_verdict(direct_value)
    verdict_value = verify_result.get("verdict")
    verdict_success = _coerce_verification_verdict(verdict_value)

    if direct_success is not None:
        verified_success = direct_success
        if not isinstance(direct_value, bool):
            verify_warnings.append(
                f"non-boolean verified_success={direct_value!r} was normalized to "
                f"{direct_success}"
            )
        if verdict_success is not None and verdict_success != direct_success:
            verify_warnings.append(
                f"ignoring conflicting textual verdict={verdict_value!r}; "
                "verified_success is authoritative"
            )
    elif verdict_success is not None:
        verified_success = verdict_success
        verify_warnings.append(
            "verification result omitted a boolean verified_success; "
            f"normalized fallback verdict={verdict_value!r} to {verdict_success}"
        )
    else:
        verified_success = None
        if "verified_success" not in verify_result and "verdict" not in verify_result:
            verify_warnings.append(
                "verification result omitted both verified_success and verdict"
            )
        elif direct_value is not None or verdict_value is not None:
            verify_warnings.append(
                "verification result has no recognizable success verdict: "
                f"verified_success={direct_value!r}, verdict={verdict_value!r}"
            )

    reported_agreement = verify_result.get("agreement")
    if isinstance(reported_agreement, bool):
        verification_agreement = reported_agreement
    elif verified_success is not None and isinstance(self_reported_success, bool):
        verification_agreement = self_reported_success == verified_success
    else:
        verification_agreement = None

    return verified_success, verification_agreement, verify_warnings


def annotate_with_cost_time(
    raw: dict, worktree_path: Path, model_key: str, price_table: dict, verify_result: Optional[dict] = None
) -> dict:
    """
    Annotates the raw result dict from invoke_one_task() with cost/time information, returning a new dict suitable for writing to test/results/<run_id>.json. This includes:
    - cost_usd: the USD cost of the run, computed from the CLAUDE JSON output
    - cost_warnings: any warnings from the cost computation
    - total_ms: the total wall-clock time of the run, computed from the CLAUDE JSON output or the wall-clock time measured by the script
    - time_split: a TimeSplit object indicating the breakdown of time spent in the agent and simulation

    Args:
        raw (dict): The raw result dict from invoke_one_task()
        worktree_path (Path): The path to the worktree where the run was performed
        model_key (str): The model key used for the run
        price_table (dict): The price table used for the run
        verify_result (dict, optional): output of run_verification() for this run, or None
            if --no-verify was passed. When present, its `verified_success` — not the run's
            own self-report — becomes the authoritative `success` field (see module docstring
            step 6): a task-running session has every incentive to believe it already
            succeeded, so "finished" is defined by the independent check, not the self-report.
    """
    usage = cost_time.parse_claude_json_result(raw["raw_result"]) if raw["raw_result"] else cost_time.RunUsage()
    cost_usd, cost_warnings = cost_time.compute_dollar_cost(usage, model_key, price_table)

    transcript_path = None
    if usage.session_id:
        transcript_path = cost_time.find_transcript_path(worktree_path, usage.session_id)
    total_ms = usage.duration_ms if usage.duration_ms is not None else raw["wall_clock_ms_measured"]
    time_split = cost_time.agent_vs_simulation_split(transcript_path, total_ms)

    episodic = raw.get("episodic_record") or {}
    self_reported_success = episodic.get("success")
    episodic_summary_path = episodic.get("_summary_path")

    if verify_result is not None:
        verified_success, verification_agreement, verify_warnings = (
            resolve_verification_result(verify_result, self_reported_success)
        )
    else:
        verified_success = None 
        # if we didn't verify, we don't know whether it succeeded
        # we leave it as None here;
        # when doing summary statistics, we will not use this task result to compute the "success_rate"; 
        # and there will be a column counting the total number of unverified tasks;
        # let `n` be the total number of tasks,
        # `n_verified_success`: the number of tasks verified as successful
        # `n_verified_failure`: the number of tasks verified as failed
        # `n_unverified`: the number of tasks unverified
        # success_rate = n_verified_success / (n_verified_success + n_verified_failure)
        verify_warnings = ["verification skipped (--no-verify) — 'success' falls back to the run's own unverified self-report"]

    # No print here — this function only builds the result dict (no I/O), same as the rest
    # of it; the caller (main()'s loop) is what actually prints, using episodic_summary_path
    # below to show the record's path when found, or this warning when it wasn't.
    episodic_warnings = [] if episodic_summary_path else ["no episodic-memory record found for this run"]

    return {
        "run_id": None,  # filled by caller
        "task_id": raw["task"]["id"],
        "category": raw["task"].get("category"),
        "tier": raw["task"].get("tier"),
        "model": model_key,
        "start_time_utc": raw["start_time_utc"],
        "end_time_utc": raw["end_time_utc"],
        "returncode": raw["returncode"],
        "claude_json_parse_error": raw["raw_stdout_parse_error"],
        "session_id": usage.session_id,
        "self_reported_success": self_reported_success,
        "verified_success": verified_success,
        "verification_agreement": verification_agreement,
        "verification_critique": (verify_result or {}).get("critique"),
        "attempts": episodic.get("attempts"),
        "skills_used": episodic.get("skills_used", []),
        "knowledge_used": episodic.get("knowledge_used", []),
        "episodic_path": raw["episodic_path"],  # episodic memory record folder; absolute path; str
        "episodic_summary_path": episodic_summary_path,  # episodic memory record summary.md; absolute path; str
        "transcript_path": str(transcript_path),  # claude code transcript path; absolute path; str
        "wall_clock_ms": {
            "total": total_ms,
            "total_measured_by_harness": raw["wall_clock_ms_measured"],
            "agent": time_split.agent_ms,
            "simulation": time_split.simulation_ms,
            "duration_api_ms": usage.duration_api_ms,
        },
        "tokens": {
            "input": usage.input_tokens,
            "output": usage.output_tokens,
            "cache_creation": usage.cache_creation_input_tokens,
            "cache_read": usage.cache_read_input_tokens,
        },
        "cost_usd": cost_usd,
        "cost_accounting": {
            "usage_source": usage.usage_source,
            "price_table_date": price_table.get("price_table_date"),
            "pricing_basis": price_table.get("pricing_basis"),
            # Claude Code computes this client-side from its bundled Anthropic
            # price registry.  Preserve it for diagnostics, but never use it as
            # the bill for an Anthropic-compatible third-party endpoint.
            "raw_cli_estimate_usd": usage.total_cost_usd,
        },
        "num_turns": usage.num_turns,
        "is_error": usage.is_error,
        "subtype": usage.subtype,
        "warnings": list(usage.warnings) + list(cost_warnings) + list(time_split.warnings) + verify_warnings + episodic_warnings,
    }



# ========== Persist raw claude stdout/stderr, for debugging failed/errored runs ==========
def write_raw_output(run_id: str, raw: dict, results_dir: Path) -> dict:
    """Writes `raw`'s full, untruncated stdout/stderr from the `claude -p` invocation to
    `results_dir/raw/<run_id>.{stdout,stderr}.log`, so a failed or malformed run can still
    be inspected after the fact — the result JSON only keeps derived fields, so without
    this the actual claude output is lost the moment the process exits.

    Returns {"stdout": <path relative to results_dir>, "stderr": <path or None>} — stderr
    is only written (and only referenced) when non-empty, since most successful runs have
    none and an empty file would just be clutter."""
    raw_dir = results_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = raw_dir / f"{run_id}.stdout.log"
    stdout_path.write_text(raw.get("stdout") or "")
    print(f"\n  [Stdout] Wrote stdout to {stdout_path}")
    paths = {"stdout": str(stdout_path)}  # stdout path; absolute path; str

    stderr = raw.get("stderr") or ""
    if stderr:
        stderr_path = raw_dir / f"{run_id}.stderr.log"
        stderr_path.write_text(stderr)
        print(f"\n  [Stderr] Wrote stderr to {stderr_path}")
        paths["stderr"] = str(stderr_path)  # stderr path; absolute path; str
    else:
        paths["stderr"] = None

    return paths


# ========== Run the experiment and write results ==========
def write_result(result: dict, results_dir: Path) -> Path:
    """Return result output path.
    `result` is the result from one task run.
    `results_dir` is the directory to write all result to.
    `out_path` is the path to write this result to, which is `results_dir/<run_id>.json`.
    
    NOTE: worktrees are only the execution sandbox, not where results live. 
    All worktrees share the same result folder in original repo
    Results are not scattered per-worktree; every pair writes into one shared directory in the main checkout: 
    DEFAULT_RESULTS_DIR regardless of which worktree the task actually ran in.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{result['run_id']}.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    return out_path  # result output path; absolute path; Path obj


def main() -> None:
    # ===== Parse command line arguments and configuration =====
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--model", required=True, help="key in test/harness/models.yaml")
    task_group = parser.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task-id", help="single task id from benchmark_tasks.yaml")
    task_group.add_argument("--task-ids", help="comma-separated task ids to run as one batch")
    task_group.add_argument(
        "--all-tasks", action="store_true", help="run every task in --benchmark, in file order, as one batch"
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="independent repeats per task (§5 Statistical Concerns), all run inside this same worktree",
    )
    parser.add_argument("--cache-mode", choices=["cold", "warm"], default="cold")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--conditions-file", type=Path, default=HARNESS_DIR / "conditions.yaml")
    parser.add_argument("--models-file", type=Path, default=HARNESS_DIR / "models.yaml")
    parser.add_argument("--price-table", type=Path, default=HARNESS_DIR / "price_table.yaml")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--worktree-root", type=Path, default=DEFAULT_WORKTREE_ROOT)
    parser.add_argument(
        "--worktree-name",
        default=None,
        help=(
            "directory name to use under --worktree-root, instead of the auto-generated "
            "timestamp+condition+model+task-label id. Useful with --keep-worktree so kept "
            "worktrees are easy to browse by eye (e.g. 'full-ver_claude-opus-5'). Must be "
            "unique — this script refuses to reuse an existing path rather than silently "
            "overwriting or merging into it."
        ),
    )
    parser.add_argument("--ref", default="HEAD", help="git ref to check the worktree out from")
    parser.add_argument("--keep-worktree", action="store_true")
    parser.add_argument("--max-budget-usd", type=float, default=None)
    parser.add_argument("--no-skip-permissions", action="store_true", help="disable --dangerously-skip-permissions")
    parser.add_argument(
        "--verify-model",
        default="claude-opus-5",
        help=(
            "model key from --models-file used for independent post-hoc verification (the `verify` skill), "
            "run as a second, separate `claude -p` process after each task. Deliberately decoupled "
            "from --model, so verification quality stays constant while the model under test varies."
        ),
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip independent verification; 'success' falls back to the run's own self-reported success, which is not independently checked",
    )
    parser.add_argument("--dry-run", action="store_true", help="print planned actions; touch neither git nor claude")
    parser.add_argument(
        "--continue",
        action="store_true",
        dest="continue_mode",
        help="continue running: reuse existing worktrees, do not re-initialize task logs, and skip already-completed (task, repeat) pairs",
    )
    args = parser.parse_args()

    benchmark = load_yaml(args.benchmark)  # load task details given task args
    conditions = load_yaml(args.conditions_file)["conditions"]  # load condition config given args
    models = load_yaml(args.models_file)["models"]  # load model config given args
    price_table = load_yaml(args.price_table)  # load price table for cost computation

    if args.condition not in conditions:
        parser.error(f"unknown condition '{args.condition}' — choices: {sorted(conditions)}")
    if args.model not in models:
        parser.error(f"unknown model '{args.model}' — choices: {sorted(models)}")
    if not args.no_verify and args.verify_model not in models:
        parser.error(f"unknown verify model '{args.verify_model}' — choices: {sorted(models)}")

    condition = conditions[args.condition]  # load condition config given condition args
    model_config = models[args.model]  # load llm config given model args
    verify_model_config = models[args.verify_model] if not args.no_verify else None
    verify_condition = conditions.get(VERIFY_CONDITION_NAME)
    if not args.no_verify and verify_condition is None:
        parser.error(
            f"verification requires condition '{VERIFY_CONDITION_NAME}' in "
            f"{args.conditions_file}"
        )

    if args.all_tasks:
        task_ids = [t["id"] for t in benchmark["tasks"]]
    elif args.task_id:
        task_ids = [args.task_id]
    else:
        task_ids = [t.strip() for t in args.task_ids.split(",")]
    tasks = [find_task(benchmark, tid) for tid in task_ids]

    batch_run_id = args.worktree_name or make_batch_id(args.condition, args.model, task_ids)
    worktree_path = args.worktree_root / batch_run_id

    if args.worktree_name and worktree_path.exists() and not args.dry_run and not args.continue_mode:
        parser.error(
            f"--worktree-name '{args.worktree_name}' already exists at {worktree_path} — "
            "pick a different name (this script refuses to overwrite or reuse an existing worktree); "
            "pass --continue to reuse it"
        )


    # ===== Dry-run mode: print what would happen, but don't touch git or claude =====
    if args.dry_run:
        """ 
        `--dry-run` mode does exactly two things: **it runs every step of the script that involves reading/deciding, 
        and it skips every step that involves doing something to the filesystem, git, or the network.** Concretely:

        What it still does / checks (real code path, not mocked):
        - Full argparse validation — required args, mutually-exclusive --task-id/--task-ids/--all-tasks group, etc.
        - Actually loads and parses benchmark_tasks.yaml, conditions.yaml, models.yaml, price_table.yaml (:370-373).
        - Validates --condition exists in conditions.yaml and --model exists in models.yaml, erroring out via parser.error if not (:375-378).
        - Resolves the requested task IDs to real task records via find_task (:389) — a typo'd task ID fails here, dry-run or not.
        - Computes the real batch_run_id/worktree_path that would be used (:391-392).
        - For each (repeat, task) pair, calls the actual build_claude_command() — the same function the real run uses — 
        so what gets printed is the literal claude -p ... argv, including real generated session-id UUIDs, the correct 
        --resume vs --session-id choice for the chosen --cache-mode, --model/--safe-mode/--max-budget-usd/--permission-mode flags, etc. (:409-424 in the selection). 
        This is the main value of dry-run: you get to eyeball the exact command before it touches your API usage.
        - To keep output readable, it only expands repeat 1 in full and just notes "same pattern, fresh session id(s)" for 
        repeats 2+ (:409-410) — it does still generate (but discard) a shared_session_id for those, just doesn't print each task line.
        """
        print("[dry-run] would create worktree:", worktree_path, "from ref", args.ref)
        print("[dry-run] would apply condition:", args.condition, "->", condition)
        print("[dry-run] would use model:", args.model, "->", redacted_model_config(model_config))
        if not args.no_verify:
            print(
                "[dry-run] would apply filesystem removals from verification condition:",
                VERIFY_CONDITION_NAME,
            )
            print(
                "[dry-run] would use verification model:",
                args.verify_model,
                "->",
                redacted_model_config(verify_model_config),
            )
        print(f"[dry-run] {args.repeats} repeat(s) of {len(tasks)} task(s): {', '.join(t['id'] for t in tasks)}")
        for repeat_idx in range(1, args.repeats + 1):
            shared_session_id = str(uuid.uuid4())
            if repeat_idx > 1:
                print(f"[dry-run] repeat {repeat_idx}/{args.repeats}: same pattern, fresh session id(s), omitted for brevity")
                continue
            for i, t in enumerate(tasks):
                resume = args.cache_mode == "warm" and i > 0
                # Mirrors the real run loop below: warm mode shares one session id across
                # the batch (via --resume); cold mode gives every task its own fresh id.
                session_id = shared_session_id if args.cache_mode == "warm" else str(uuid.uuid4())
                cmd_preview = build_claude_command(
                    task_text=t["task"],
                    model_config=model_config,
                    condition=condition,
                    settings_path=worktree_path / ".claude" / "settings.local.json" if model_config.get("env") else None,
                    session_id=session_id,
                    resume=resume,
                    max_budget_usd=args.max_budget_usd,
                    skip_permissions=not args.no_skip_permissions,
                )
                print(
                    f"[dry-run] repeat {repeat_idx}/{args.repeats}, task {t['id']} (resume={resume}):",
                    " ".join(json.dumps(c) if " " in c else c for c in cmd_preview),
                )
                if not args.no_verify:
                    verify_prompt_preview = build_verify_prompt(
                        task_id=t["id"],
                        task_text=t["task"],
                        episodic_path_str="<episodic_path>",
                        verify_result_path_str=str(
                            args.results_dir / "verify" / "<run_id>.json"
                        ),
                    )
                    verify_cmd_preview = build_verify_command(
                        prompt=verify_prompt_preview,
                        verify_model_config=verify_model_config,
                        verify_settings_path=(
                            args.worktree_root
                            / f"{batch_run_id}-verify"
                            / ".claude"
                            / "settings.local.json"
                            if verify_model_config.get("env")
                            else None
                        ),
                        max_budget_usd=args.max_budget_usd,
                        skip_permissions=not args.no_skip_permissions,
                    )
                    print(
                        f"[dry-run] repeat {repeat_idx}/{args.repeats}, task {t['id']} verify:",
                        " ".join(json.dumps(c) if " " in c else c for c in verify_cmd_preview),
                    )
        if not args.no_verify:
            print(
                "[dry-run] would also create a dedicated verify worktree (always auto-removed, "
                "ignores --keep-worktree — it's pure execution environment, nothing to inspect):",
                args.worktree_root / f"{batch_run_id}-verify",
            )
        print("[dry-run] no worktree created, no claude invocation made, no results written.")
        return


    # ===== Real mode: touch git, make worktree, apply condition, write settings, run, write results =====
    # ----- create a disposable worktree for this batch of runs (one worktree per condition/model/task batch) -----
    worktree_exists = worktree_path.exists()
    if args.continue_mode and worktree_exists:
        print(f"[continue] reusing existing worktree at {worktree_path}")
    else:
        create_worktree(worktree_path, ref=args.ref)
    if args.keep_worktree:
        # --keep-worktree means this worktree won't self-clean — print the exact removal
        # command now, right when it's created, so it's not lost/forgotten. Printing a
        # manually-deleted directory instead of using this leaves stale, `prunable`
        # git worktree metadata behind (git worktree prune fixes that after the fact).
        print(
            "\n"
            + "-" * 30
            + "\n"
            f"  --keep-worktree: this worktree will NOT be auto-removed.\n"
            f"  To remove it later, run:\n"
            f"    git worktree remove --force {worktree_path}\n"
            + "-" * 30
            + "\n",
            flush=True,
        )
    
    # ----- create a second worktree dedicated to independent verification -----
    # Deliberately never the worktree under test (which may have memory/skills stripped per
    # condition, and whose model has every incentive to believe its own work) and never the
    # main checkout (--dangerously-skip-permissions must never run against the user's real
    # working tree). One verify worktree is created per batch and reused across every
    # (repeat, task) pair in it, same as the main worktree.
    verify_worktree_path = None
    verify_settings_path = None
    if not args.no_verify:
        verify_worktree_path = args.worktree_root / f"{batch_run_id}-verify"
        if args.continue_mode and verify_worktree_path.exists():
            print(f"[continue] reusing existing verify worktree at {verify_worktree_path}")
        else:
            create_worktree(verify_worktree_path, ref=args.ref)

    # ----- apply condition setting and llm settings once per worktree, before any tasks or repeats -----
    settings_path = None  # may be set below; stays None when model_config has no env overrides
    if args.continue_mode and worktree_exists:
        print("[continue] skipping condition application — worktree already set up")
        settings_path = write_worktree_settings(worktree_path, model_config)
    else:
        memory_ops.apply_condition(worktree_path, condition)  # apply condition
        settings_path = write_worktree_settings(worktree_path, model_config)
    
    # ----- apply conditions for verify worktree -----
    # verify worktree always has condition="verification"
    # has llm: "claude-opus-5" by default, but can be overridden with --verify-model commandline flag
    if verify_worktree_path is not None:
        # ``apply_condition`` is idempotent, so also apply it when --continue reuses
        # a verifier worktree. removes SimSkill's CLAUDE.md
        memory_ops.apply_condition(verify_worktree_path, verify_condition)
        verify_settings_path = write_worktree_settings(verify_worktree_path, verify_model_config)

    # create a worktree tasks log file (jsonl)
    worktree_tasks_jsonl = worktree_path / 'test' / "worktree_tasks.jsonl"
    worktree_tasks = []  # list of task dicts; to be returned to caller of this script
    if args.continue_mode and worktree_tasks_jsonl.exists():
        # Continue mode: load existing records so we can skip already-completed tasks.
        with worktree_tasks_jsonl.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        worktree_tasks.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        print(f"[continue] loaded {len(worktree_tasks)} existing task record(s) from {worktree_tasks_jsonl}")
    else:
        # Fresh run: clear/create the file.
        with worktree_tasks_jsonl.open("w", encoding="utf-8") as f:
            pass
    # also manage the log file
    worktree_tasks_log = worktree_path / 'test' / "worktree_tasks.log"
    if args.continue_mode and worktree_tasks_log.exists():
        print(f"[continue] appending to existing log at {worktree_tasks_log}")
    else:
        worktree_tasks_log.write_text("")
    
    # ----- for each repeat, run each task -----
    # When continuing, build a set of (task_id, repeat) already completed so they can be skipped.
    already_done: set = set()
    if args.continue_mode:
        for rec in worktree_tasks:
            already_done.add((rec.get("task_id"), rec.get("task_repeat")))
        if already_done:
            print(f"[continue] {len(already_done)} (task, repeat) pair(s) already done — will skip them")

    written_paths = []
    for repeat_idx in range(1, args.repeats + 1):
        shared_session_id = str(uuid.uuid4())
        for i, task in enumerate(tasks):

            task_id = task["id"]
            print(f"\n-----[Task ID]: {task_id}-----")
            # --- when continuing, skip already-completed (task, repeat) pairs ---
            if args.continue_mode and (task_id, repeat_idx) in already_done:
                print(f"  [continue] skip — (task_id={task_id}, repeat={repeat_idx}) already done")
                continue
            # --- determine whether to resume a previous session ---
            resume = args.cache_mode == "warm" and i > 0
            # Warm mode deliberately reuses one session id across a repeat's whole
            # task batch (that's the point — --resume keeps the prompt cache warm).
            # Cold mode must NOT reuse it: each task gets its own fresh, independent
            # session id, since cold mode's whole premise is a genuinely blank session
            # every time. Either way, each repeat starts its own fresh session chain —
            # repeats measure stochasticity, not cache warmth, so they must never
            # --resume across each other regardless of --cache-mode.
            session_id = shared_session_id if args.cache_mode == "warm" else str(uuid.uuid4())
            # PS: uuid.uuid4() generates a random UUID
            
            
            # Try one task
            # we add try except here to catch any errors for each task
            # so if one task fails, we can still continue with the next task
            try:
                # --- invoke claude -p on this task, capture its raw result ---
                infer_start_time = datetime.now()
                print("\n  Invoking claude code to execute this task; current time:", infer_start_time)
                raw = invoke_one_task(
                    worktree_path=worktree_path,
                    task=task,
                    model_key=args.model,
                    model_config=model_config,
                    condition=condition,
                    settings_path=settings_path,
                    session_id=session_id,
                    resume=resume,
                    max_budget_usd=args.max_budget_usd,
                    skip_permissions=not args.no_skip_permissions,
                )
                infer_end_time = datetime.now()
                print("\n  Raw result obtained; current time:", infer_end_time)
                print("\n  Time spent on task execution:", infer_end_time - infer_start_time)
                
                # --- annotate with cost/time, annotate with run_id, write to results dir ---
                run_id = make_run_id(args.condition, args.model, task["id"], repeat_idx)
                raw_paths = write_raw_output(run_id, raw, args.results_dir)

                # --- independently verify the run before deciding whether it "succeeded" ---
                verify_result = None
                verify_result_path = args.results_dir / "verify" / f"{run_id}.json"  # file to save the verification result
                verify_result_path.parent.mkdir(parents=True, exist_ok=True)  # Note: make sure parent dir exists
                verify_result_path_str = str(verify_result_path)  
                
                if not args.no_verify:
                    verify_start_time = datetime.now()
                    print("\n  Verification starts; current time:", verify_start_time)
                    
                    # If the task is not executed successfully, we cannot verify it
                    # we pass it to the verification function as a parameter
                    episodic = raw.get("episodic_record") or {}
                    self_reported_success = episodic.get("success")
                    
                    verify_result = run_verification(
                        run_id=run_id,
                        results_dir=args.results_dir,  # path to the results directory; absolute path; Path obj
                        task_id=task_id,
                        task_text=task["task"],
                        episodic_path_str = raw["episodic_path"],  # path to the episodic memory record folder; absolute path; str
                        verify_result_path_str=verify_result_path_str,  # file to save the verification result; absolute path; str
                        verify_worktree_path=verify_worktree_path,  # path to the verify worktree; absolute path; path obj
                        verify_model_config=verify_model_config,
                        verify_settings_path=verify_settings_path,
                        max_budget_usd=args.max_budget_usd,
                        skip_permissions=not args.no_skip_permissions,
                        self_reported_success=self_reported_success,
                    )
                    verify_end_time = datetime.now()
                    print("\n  Verification finishes; current time:", verify_end_time)
                    print("\n  Time spent on verification:", verify_end_time - verify_start_time)
                    
                result = annotate_with_cost_time(raw, worktree_path, args.model, price_table, verify_result=verify_result)
                # add more fields to result
                result["run_id"] = run_id
                result["raw_stdout_path"] = raw_paths["stdout"]  # path to the stdout file; absolute path; str
                result["raw_stderr_path"] = raw_paths["stderr"]  # path to the stderr file; absolute path; str
                result["condition"] = args.condition
                result["repeat"] = repeat_idx
                result["repeats_requested"] = args.repeats
                result["cache_mode"] = args.cache_mode
                result["worktree_path"] = str(worktree_path)  # path to the worktree; absolute path; str
                result["git_ref"] = args.ref
                result["batch_session_id"] = session_id
                result["batch_position"] = i
                result["batch_size"] = len(tasks)
                
                # write result to results dir
                out_path = write_result(result, args.results_dir)
                written_paths.append(out_path)
                print(
                    f"\n  [Results] wrote {out_path} (repeat={repeat_idx}/{args.repeats}, "
                    f"success={result['verified_success']} [self-reported={result['self_reported_success']}], "
                    f"cost_usd={result['cost_usd']})"
                )
                
                if result["episodic_summary_path"]:
                    print(f"\n  [Episodic memory record] summary path: {result['episodic_summary_path']}")
                else:
                    print(f"\n  [Episodic memory record] Summary not found")
                
                if result["verification_agreement"] is False:
                    print(f"\n  [DISAGREEMENT] self-report and independent verification disagree for {run_id}")
                elif result["verification_agreement"] is True:
                    print(
                        f"\n  [AGREEMENT] self-report and independent verification agree for {run_id}")
                
                if result["verified_success"] is None:
                    print(f"\n  [Verification] No verification performed for {run_id}")
                    
                for w in result["warnings"]:
                    print(f"\n  [Warning] {w}", file=sys.stderr)
                    
                # Append task info to worktree tasks log 
                worktree_tasks_item = {
                    "task_id": task["id"],  # task id in accordance with the benchmark task list
                    "task_condition": args.condition,  # task condition, e.g. "full-ver"
                    "task_model": args.model,  # task model, e.g. "claude-opus-5"
                    "task_repeat": repeat_idx,  # task repeat index
                    "worktree_path": str(worktree_path),  # worktree path to run the task; absolute path; str
                    "session_id": session_id,  # session id to run the task
                    "run_id": run_id,  # run id of the task
                    "episodic_path": result["episodic_path"],  # episodic memory path of the task; absolute path; str
                    "result_path": str(out_path),  # task result file path; absolute path; str
                    "self_reported_success": result["self_reported_success"],  # task self-reported success"
                    "verified_success": result["verified_success"],
                    "verification_agreement": result["verification_agreement"],  # task verification agreement"
                    "raw_stdout_path": raw_paths["stdout"],  # task raw stdout file path; absolute path; str
                    "raw_stderr_path": raw_paths["stderr"],  # task raw stderr file path; absolute path; str
                    "verify_result_path":  str(args.results_dir / "verify" / f"{run_id}.json"),  # task verification result file path; absolute path; str
                    "verify_stdout_path": str(args.results_dir / "raw" / f"{run_id}.verify.stdout.log"),  # task verification raw stdout file path; absolute path; str
                    "verify_stderr_path": str(args.results_dir / "raw" / f"{run_id}.verify.stderr.log"),  # task verification raw stderr file path; absolute path; str
                    "transcript_path": result["transcript_path"]  # claude code transcript path; absolute path; str
                }
                worktree_tasks.append(worktree_tasks_item)
                # append task info to worktree tasks jsonl file
                with worktree_tasks_jsonl.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(worktree_tasks_item) + "\n")
                    
                # Append worktree tasks log to the main repo's experiment tasks log
                # Note: `run_experiment.py` script does not care which experiment is running
                # it just keep appending items to the "experiment_tasks.jsonl" file
                # it's caller's responsibility to initialize the "experiment_tasks.jsonl" file
                # when a new experiment is started
                experiment_tasks_jsonl = REPO_ROOT / "test"  / "experiment_tasks.jsonl"
                with experiment_tasks_jsonl.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(worktree_tasks_item) + "\n")
                    
            except Exception as e:
                print(f"\n  [Error] Task {task_id} encounters error: {e}", file=sys.stderr)
                # also log error message for later review
                with worktree_tasks_log.open("a", encoding="utf-8") as f:
                    f.write(f"Task id: {task_id} error:\n{e}\n\n")
                
    # ----- Cleanup -----           
    # The verify worktree is always removed here, regardless of --keep-worktree: it's
    # pure execution environment (see run_verification's docstring) — every actual
    # output goes to results_dir, never into the worktree itself — so there's nothing
    # in it a user would ever want to inspect after the fact, unlike the main worktree.
    if verify_worktree_path is not None:
        remove_worktree(verify_worktree_path)

    if args.keep_worktree:
        print(
            f"\n  worktree kept at {worktree_path} — remove later with:\n"
            f"      git worktree remove --force {worktree_path}"
        )
    else:
        remove_worktree(worktree_path)


if __name__ == "__main__":
    main()
