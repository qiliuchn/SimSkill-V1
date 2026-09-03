"""Driver for Experiment #1 (test/experiments.md §4 "Experiment #1 (Core)") - Parallel ver: 
the condition × LLM grid that answers RQ1 (Accuracy), RQ2 (LLM), RQ3 (Memory Ablation),
RQ4 (Efficiency), and RQ5 (Generalization).

This is a thin orchestration layer over `run_experiment.py`, not a reimplementation of
it: for every (condition, model) pair in the requested grid, it shells out to
`run_experiment.py --condition ... --model ... --all-tasks --repeats N --worktree-name
<condition>_<model>`, which is exactly one, predictably-named worktree per pair (§9.4)
running the full benchmark suite that many times. Pass --keep-worktree to keep them all
around afterward for inspection, browsable by name under --worktree-root. Note: because
the name is fixed per (condition, model), re-running the same grid with --keep-worktree
before clearing out the old worktrees will fail on every pair (run_experiment.py refuses
to reuse an existing worktree path) — clear them out or pass a different --worktree-root
for a second sweep over the same grid. Pass --continue to reuse existing worktrees and
skip already-completed tasks.

Unlike the sequential `run_experiment_1.py`, this version can run multiple (condition,
model) pairs concurrently via `--parallel N` (default 1). Because interleaving live
output from N concurrent subprocesses would be unreadable, each pair's stdout/stderr is
buffered and printed as an atomic block when that pair finishes.

After the whole grid finishes, it loads what got written to `test/results/` during this
sweep and prints the §5 "pre-registered primary comparisons" (`full-ver` vs `vanilla-cc`;
`full-ver` vs `proc-mem-ver`; `full-ver` vs `sem-mem-ver`) — whichever of those three
conditions were actually included in this run.

Usage:
# Phase 1.1 (test/experiments.md §8): the headline comparison, one primary LLM, n=1
python test/harness/run_experiment_1_parallel.py --conditions full-ver,vanilla-cc\
        --models deepseek-v4-pro --verify-model claude-opus-5\
        --repeats 1 --keep-worktree --parallel

# Continue a previous sweep
python test/harness/run_experiment_1_parallel.py --conditions full-ver,vanilla-cc\
    --models deepseek-v4-pro --verify-model claude-opus-5\
    --repeats 1 --keep-worktree --parallel --continue

# Run up to 4 pairs concurrently (e.g. 2 conditions × 2 models = 4 pairs):
python test/harness/run_experiment_1_parallel.py --parallel 4 \
    --conditions full-ver,vanilla-cc --models claude-haiku-4-5,claude-opus-5 \
    --repeats 1 --keep-worktree --parallel

# default (no flags): every condition in conditions.yaml x claude-opus-5, n=3 — the
# full Experiment #1 grid for one model, per §4's condition table
python test/harness/run_experiment_1_parallel.py

# dry-run the whole grid first — no worktrees, no claude calls, no cost:
python test/harness/run_experiment_1_parallel.py --dry-run

# choose the independent verifier model:
python test/harness/run_experiment_1_parallel.py \
    --conditions full-ver --models claude-opus-5 --verify-model claude-opus-5 --dry-run

# continue a previous run: reuse worktrees, skip done tasks, resume progress
python test/harness/run_experiment_1_parallel.py --continue --parallel 4 --keep-worktree

Every flag not listed above (--cache-mode, --benchmark, --ref, --keep-worktree,
--max-budget-usd, --no-skip-permissions, --verify-model, --no-verify, --worktree-root,
--results-dir, --conditions-file, --models-file, --price-table) is passed straight through
to each `run_experiment.py` invocation — see that script's --help for what they do.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
import json
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aggregate_results  # aggregate json results to a dataframe and get the Kaplan-Meier curve
import run_experiment as re1  # reuses its yaml loading + path constants


HARNESS_DIR = Path(__file__).resolve().parent
RUN_EXPERIMENT_SCRIPT = HARNESS_DIR / "run_experiment.py"
# NOTE: this is the main script to invoke
# we will run this script with `subprocess.run`

# The pairwise comparisons test/experiments.md §5 pre-registers as primary — reported
# here whenever both sides of a pair were actually included in this sweep.
PRIMARY_COMPARISONS = [
    ("full-ver", "vanilla-cc"),
    ("full-ver", "proc-mem-ver"),
    ("full-ver", "sem-mem-ver"),
]

# Lock for serializing print output from concurrent workers.
_print_lock = threading.Lock()



# ========== LLM config checking ==========
def find_todo_env_values(model_key: str, model_config: dict) -> list:
    """Check for TODO placeholders in model.yaml's env section"""
    hits = []
    for k, v in (model_config.get("env") or {}).items():
        if isinstance(v, str) and "todo" in v.lower():
            hits.append(f"{model_key}.env.{k}")
    return hits


def preflight_check(models: list, models_cfg: dict, dry_run: bool) -> None:
    """
    Check LLM configs before running experiment.

    Refuses to burn real API calls against an unconfigured third-party model —
    models.yaml ships several `chatgpt-*`/`deepseek-*`/`qwen-*` entries with literal
    "TODO" placeholders (test/experiments.md §7), and a real run against those would
    just fail on every single task after creating a worktree for nothing."""
    problems = []
    for model_key in models:
        problems += find_todo_env_values(model_key, models_cfg[model_key])
    if problems and not dry_run:
        print("Refusing to start a real run — these models.yaml fields are still TODO placeholders:")
        for p in problems:
            print(f"  - {p}")
        print("Fill them in, or pass --dry-run to inspect the grid without spending anything.")
        sys.exit(1)
    elif problems:
        print("[dry-run] note: the following models.yaml fields are still TODO placeholders "
              "(fine for --dry-run, but a real run would refuse to start until fixed):")
        for p in problems:
            print(f"  - {p}")



# ========== build argv for one (condition, model) pair ==========
def _build_pair_argv(condition: str, model: str, args: argparse.Namespace) -> list:
    """Build the full subprocess argument vector for one (condition, model) pair."""
    argv = [
        sys.executable,
        str(RUN_EXPERIMENT_SCRIPT),
        "--condition", condition,
        "--model", model,
        "--all-tasks",
        "--repeats", str(args.repeats),
        "--cache-mode", args.cache_mode,
        "--benchmark", str(args.benchmark),
        "--conditions-file", str(args.conditions_file),
        "--models-file", str(args.models_file),
        "--price-table", str(args.price_table),
        "--results-dir", str(args.results_dir),
        "--worktree-root", str(args.worktree_root),
        "--worktree-name", f"{condition}_{model}",
        "--ref", args.ref,
    ]
    if args.keep_worktree:
        argv.append("--keep-worktree")
    if args.max_budget_usd:
        argv += ["--max-budget-usd", str(args.max_budget_usd)]
    if args.no_skip_permissions:
        argv.append("--no-skip-permissions")
    argv += ["--verify-model", args.verify_model]
    if args.no_verify:
        argv.append("--no-verify")
    if args.dry_run:
        argv.append("--dry-run")
    if args.continue_mode:
        argv.append("--continue")
    return argv


# ========== run one (condition, model) pair (captured output) ==========
def run_one_pair_captured(condition: str, model: str, args: argparse.Namespace) -> dict:
    """Run one (condition, model) pair by shelling out to run_experiment.py with the
    right flags. Captures stdout/stderr rather than streaming live, so the caller can
    print them atomically when concurrent workers finish.

    Returns a dict with the pair, exit code, wall time, and captured output."""
    argv = _build_pair_argv(condition, model, args)

    label = f"condition={condition} model={model}"
    start = time.time()
    proc = subprocess.run(argv, capture_output=True, text=True)
    wall_s = round(time.time() - start, 1)

    return {
        "condition": condition,
        "model": model,
        "returncode": proc.returncode,
        "wall_s": wall_s,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def print_pair_block(result: dict) -> None:
    """Print one pair's captured output as an atomic block, holding the print lock so
    concurrent workers don't interleave."""
    with _print_lock:
        print(f"\n\n\n=== condition={result['condition']} model={result['model']} "
              f"(exit={result['returncode']}, {result['wall_s']}s) ===", flush=True)
        if result["stdout"]:
            sys.stdout.write(result["stdout"])
            if not result["stdout"].endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()
        if result["stderr"]:
            sys.stderr.write(result["stderr"])
            if not result["stderr"].endswith("\n"):
                sys.stderr.write("\n")
            sys.stderr.flush()


def print_pair_report(pairs_result: list) -> None:
    """Print per-pair status"""
    print("\n=== Experiment #1 grid: per-pair status ===")
    for r in pairs_result:
        status = "OK" if r["returncode"] == 0 else f"FAILED (exit {r['returncode']})"
        print(f"  {r['condition']:<18} {r['model']:<20} {status:<20} {r['wall_s']}s")




# ========== print comparison results==========
def print_primary_comparisons(df, conditions: list, model: str) -> None:
    # NOTE: input is results dataframe

    # ===== invoke aggregate_results to summarize the dataframe results =====
    # NOTE: for each task running, there would be a json file; we want to summarize them first
    summary = aggregate_results.summary_table(df[df["model"] == model]) if not df.empty else df
    if summary is None or summary.empty:
        print(f"  (no results yet for model={model})")
        return

    # ===== iterate over comparison pairs, and print comparison results =====
    by_condition = summary.set_index("condition")
    for a, b in PRIMARY_COMPARISONS:
        if a not in conditions or b not in conditions:
            continue
        if a not in by_condition.index or b not in by_condition.index:
            print(f"  {a} vs {b}: no results for one or both conditions under model={model} yet")
            continue

        # get the rows by index "condition"
        # ra, rb: the rows by index "condition"
        ra, rb = by_condition.loc[a], by_condition.loc[b]

        def fmt(v):
            """ format one metric value (success_rate, median_cost_usd, median_wall_clock_total_s) for the printed comparison"""
            return "n/a" if v is None or (isinstance(v, float) and v != v) else f"{v:.2f}"

        # print the rows for comparison
        print(
            f"  {a} vs {b}  (model={model}):  "
            f"success_rate {fmt(ra['success_rate'])} vs {fmt(rb['success_rate'])}  |  "
            f"median_cost_usd {fmt(ra['median_cost_usd'])} vs {fmt(rb['median_cost_usd'])}  |  "
            f"median_wall_clock_total_s {fmt(ra['median_wall_clock_total_s'])} vs {fmt(rb['median_wall_clock_total_s'])}"
        )



# ========== main function to run the whole experiment ==========
def main() -> None:

    # ===== parse command line args =====
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--conditions", help="comma-separated condition names (default: every condition in conditions.yaml)")
    parser.add_argument("--models", default="claude-opus-5", help="comma-separated model keys from models.yaml")
    parser.add_argument(
        "--repeats", type=int, default=1, help="independent repeats per task (§5: n=3 for the core grid)"
    )
    parser.add_argument(
        "--parallel", type=int, nargs="?", const=0, default=None,
        help="max concurrent (condition, model) pairs; pass just '--parallel' or omit for all-at-once, or '--parallel N' to cap at N",
    )
    parser.add_argument("--cache-mode", choices=["cold", "warm"], default="cold")
    parser.add_argument("--benchmark", type=Path, default=re1.DEFAULT_BENCHMARK)
    parser.add_argument("--conditions-file", type=Path, default=HARNESS_DIR / "conditions.yaml")
    parser.add_argument("--models-file", type=Path, default=HARNESS_DIR / "models.yaml")
    parser.add_argument("--price-table", type=Path, default=HARNESS_DIR / "price_table.yaml")
    parser.add_argument("--results-dir", type=Path, default=re1.DEFAULT_RESULTS_DIR)
    parser.add_argument("--worktree-root", type=Path, default=re1.DEFAULT_WORKTREE_ROOT)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--keep-worktree", action="store_true")
    parser.add_argument("--max-budget-usd", type=float, default=None)
    parser.add_argument("--no-skip-permissions", action="store_true")
    parser.add_argument(
        "--verify-model",
        default="claude-opus-5",
        metavar="VERIFY_MODEL",
        help=(
            "model key from --models-file used for independent verification "
            "(default: claude-opus-5); forwarded to every run_experiment.py invocation"
        ),
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="passed through to run_experiment.py — skip independent verification for the whole grid",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--continue",
        action="store_true",
        dest="continue_mode",
        help="continue running the experiment: reuse existing worktrees, do not re-initialize task logs, and skip already-completed tasks",
    )
    args = parser.parse_args()

    # ===== get condition and llm config =====
    # first load the config files
    # NOTE: each file contains all settings
    conditions_cfg = re1.load_yaml(args.conditions_file)["conditions"]
    models_cfg = re1.load_yaml(args.models_file)["models"]

    # get conditions and llms to test
    conditions = args.conditions.split(",") if args.conditions else list(conditions_cfg)
    models = args.models.split(",")

    # check if conditions and llms are valid
    for c in conditions:
        if c not in conditions_cfg:
            parser.error(f"unknown condition '{c}' — choices: {sorted(conditions_cfg)}")
    for m in models:
        if m not in models_cfg:
            parser.error(f"unknown model '{m}' — choices: {sorted(models_cfg)}")
    if not args.no_verify and args.verify_model not in models_cfg:
        parser.error(
            f"unknown verify model '{args.verify_model}' — choices: {sorted(models_cfg)}"
        )

    models_to_check = list(models)
    if not args.no_verify and args.verify_model not in models_to_check:
        models_to_check.append(args.verify_model)
    preflight_check(models_to_check, models_cfg, args.dry_run)


    # ===== run all (condition, model) pairs =====
    # first get a list of all (condition, model) pairs
    pairs = list(product(conditions, models))

    # Resolve --parallel: None (flag omitted) or 0 (flag passed without a value, via
    # const=0) both mean "one thread per pair" — all worktrees run concurrently.
    if args.parallel is None or args.parallel == 0:
        args.parallel = len(pairs)
    if args.parallel < 1:
        parser.error("--parallel must be >= 1")

    # print out the grid
    print(f"\nExperiment #1 grid: {len(conditions)} condition(s) x {len(models)} model(s) = {len(pairs)} pair(s)")
    print(f"conditions: {conditions}")
    print(f"models: {models}")
    print(f"repeats={args.repeats} cache_mode={args.cache_mode} parallel={args.parallel}"
          + (" [DRY RUN]" if args.dry_run else ""))

    # start the sweep
    sweep_start_iso = datetime.now(timezone.utc).isoformat()

    # initialize a log file
    # this task log file will be appended when tasks are executed during each worktree execution progress
    experiment_tasks_jsonl = re1.REPO_ROOT / "test" / "experiment_tasks.jsonl"
    if args.continue_mode:
        # Continue mode: do not clear the log — just ensure it exists so appends work.
        experiment_tasks_jsonl.touch()
    else:
        # Fresh run: clear/create the file.
        with experiment_tasks_jsonl.open("w", encoding="utf-8") as f:
            pass

    # Run all pairs concurrently (up to --parallel at a time).
    # Each worker runs run_experiment.py as a subprocess and captures its output;
    # when a worker finishes, we print its output as an atomic block so concurrent
    # output streams don't interleave.
    pairs_result = []
    with ThreadPoolExecutor(max_workers=args.parallel) as executor:
        future_map = {
            executor.submit(run_one_pair_captured, condition, model, args): (condition, model)
            for condition, model in pairs
        }

        for future in as_completed(future_map):
            result = future.result()
            pairs_result.append(result)
            print_pair_block(result)

    # Sort so the per-pair report is in a deterministic order regardless of completion order.
    pairs_result.sort(key=lambda r: (r["condition"], r["model"]))

    # print out pairs run status
    print_pair_report(pairs_result)

    n_failed = sum(1 for r in pairs_result if r["returncode"] != 0)
    if n_failed:
        print(f"\n{n_failed}/{len(pairs_result)} pair(s) failed — see output above.")

    if args.dry_run:
        return


    # ===== get results dataframe =====
    """
    NOTE: worktrees are only the execution sandbox, not where results live. So we can summarize all
    pairs' results at a time
    Results are not scattered per-worktree; every pair writes into one shared directory in the main checkout:
    DEFAULT_RESULTS_DIR = REPO_ROOT / "test" / "results" (run_experiment.py:76), and write_result()
    (run_experiment.py:369-376) writes each task/repeat's outcome there as:
        results_dir/<run_id>.json
    regardless of which worktree the task actually ran in.
    Note: there could be many history result files in the directory, we need to filter out the ones
    that are not part of this sweep. Check out the function `aggregate_results.load_results()`
    """
    # load experiment results
    experiment_tasks = []
    with experiment_tasks_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                experiment_tasks.append(json.loads(line)) 
                
    if not experiment_tasks:
        print(f"Experiment tasks log at {experiment_tasks_jsonl} is empty — nothing to print.")
        return

    df = aggregate_results.load_results_by_experiment_log(experiment_tasks)
    if df.empty:
        print(f"No valid result files loaded from {str(experiment_tasks_jsonl)} — nothing to print.")
        return

    # Filter out the ones that are not part of this sweep if you use `aggregate_results.load_results()`
    # no need to filter if you use `load_results_by_experiment_log`
    if False:
        # Note:
        # aggregate_results.load_results() loads all results in `results` directory;
        # if you use `aggregate_results.load_results()` instead of `aggregate_results.load_results_by_experiment_log()`,
        # you will get all results in the directory, regardless of which experiment sweep they belong to
        # in this case you need to filter out the ones that are not part of this sweep
        # by the sweep start time
        if not df.empty and "start_time_utc" in df.columns:
            df = df[df["start_time_utc"] >= sweep_start_iso]
        df = df[df["condition"].isin(conditions) & df["model"].isin(models)] if not df.empty else df

    print(f"\n=== This sweep's results: {len(df)} run(s) ===")
    print(aggregate_results.summary_table(df).to_string(index=False))


    # ===== print primary comparisons' results=====
    print("\n=== §5 pre-registered primary comparisons ===")
    for model in models:
        print_primary_comparisons(df, conditions, model)


if __name__ == "__main__":
    main()
