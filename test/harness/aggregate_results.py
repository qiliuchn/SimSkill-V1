#!/usr/bin/env python3
"""Loads test/results/*.json into a table and reports the comparisons
test/experiments.md actually asks for (§5 Statistical Concerns, §3.2.4/§3.2.5
empirical success-at-budget curves) — not just a naive mean.

Usage:
    python test/harness/aggregate_results.py
    python test/harness/aggregate_results.py --metric cost_usd --budgets 0.1,0.5,2,10
    python test/harness/aggregate_results.py --metric wall_clock_total_s --budgets 60,300,900,3600
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Optional, List, Dict

import pandas as pd

import cost_time

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = REPO_ROOT / "test" / "results"
DEFAULT_PRICE_TABLE = REPO_ROOT / "test" / "harness" / "price_table.yaml"


def _raw_stdout_candidates(result: dict, result_path: Path) -> list[Path]:
    """Return possible raw Claude-result paths, most authoritative first.

    An interactive run has no captured process stdout — ``run_experiment`` writes
    a human-readable placeholder there instead. Such runs carry their whole-tree
    ``modelUsage`` in a ``<run_id>.claude_result.json`` sidecar written by
    ``add_interactive_task_execution_result.py``, so that sidecar is checked
    first; otherwise repricing would fail on exactly the runs whose usage was
    reconstructed rather than captured.
    """
    candidates = []

    def add(value) -> None:
        if not value:
            return
        path = Path(value)
        candidates.append(path if path.is_absolute() else result_path.parent / path)

    add(result.get("raw_claude_result_path"))
    run_id = result.get("run_id")
    if run_id:
        candidates.append(result_path.parent / "raw" / f"{run_id}.claude_result.json")
    add(result.get("raw_stdout_path"))
    if run_id:
        candidates.append(result_path.parent / "raw" / f"{run_id}.stdout.log")

    unique = []
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _reprice_from_stored_tokens(
    repriced: dict, result: dict, result_path: Path, price_table: dict, reason: str,
) -> tuple[dict, list[str]]:
    """Last-resort repricing from the token counters frozen in the result JSON.

    The raw Claude result is the preferred basis because it carries the per-model
    ``modelUsage`` split. When it is unreadable, the result's own ``tokens`` block
    still holds the same whole-tree totals (``annotate_with_cost_time`` derives it
    from ``modelUsage`` when that was present), so the run can be repriced with the
    current price table at the run's own model rate. Only the per-model split is
    lost, which matters solely for sessions that mixed models.
    """
    tokens = result.get("tokens")
    model_key = result.get("model")
    if not isinstance(tokens, dict) or not model_key:
        repriced["cost_usd"] = None
        return repriced, [f"cannot reprice {result_path}: {reason}"]

    usage = cost_time.RunUsage(
        input_tokens=cost_time._as_nonnegative_int(tokens.get("input")),
        output_tokens=cost_time._as_nonnegative_int(tokens.get("output")),
        cache_creation_input_tokens=cost_time._as_nonnegative_int(
            tokens.get("cache_creation")
        ),
        cache_read_input_tokens=cost_time._as_nonnegative_int(tokens.get("cache_read")),
        usage_source="stored_tokens",
    )
    recalculated_cost, cost_warnings = cost_time.compute_dollar_cost(
        usage, str(model_key), price_table
    )
    repriced["cost_usd"] = recalculated_cost
    repriced["cost_accounting"] = {
        "usage_source": usage.usage_source,
        "price_table_date": price_table.get("price_table_date"),
        "pricing_basis": price_table.get("pricing_basis"),
        "raw_cli_estimate_usd": result.get("cost_usd"),
        "repriced_from": str(result_path),
    }
    warnings = [
        f"{result_path}: {reason}; repriced from the token counters stored in the "
        "result JSON instead (whole-tree totals, but no per-model split)",
        *cost_warnings,
    ]
    if recalculated_cost is None:
        warnings.append(f"cannot reprice {result_path}: {reason}")
    return repriced, warnings


def reprice_result(
    result: dict, result_path: Path, price_table: dict,
) -> tuple[dict, list[str]]:
    """Recompute one saved run from its raw whole-tree Claude usage.

    Historical result JSONs contain a derived ``cost_usd`` that was frozen when
    the run completed. Repricing must go back to the raw CLI result because only
    its ``modelUsage`` block includes subagent tokens. This returns an in-memory
    copy and never mutates the experiment artifact on disk.
    """
    repriced = copy.deepcopy(result)
    raw_path = next(
        (path for path in _raw_stdout_candidates(result, result_path) if path.is_file()),
        None,
    )
    if raw_path is None:
        return _reprice_from_stored_tokens(
            repriced, result, result_path, price_table,
            "raw Claude result is unavailable",
        )

    try:
        raw_result = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _reprice_from_stored_tokens(
            repriced, result, result_path, price_table,
            f"raw Claude result at {raw_path} is unreadable ({exc})",
        )

    if not isinstance(raw_result, dict):
        return _reprice_from_stored_tokens(
            repriced, result, result_path, price_table,
            f"{raw_path} is not a JSON object",
        )

    usage = cost_time.parse_claude_json_result(raw_result)
    model_key = result.get("model")
    if not model_key:
        repriced["cost_usd"] = None
        return repriced, [f"cannot reprice {result_path}: result has no model key"]

    recalculated_cost, cost_warnings = cost_time.compute_dollar_cost(
        usage, str(model_key), price_table
    )
    repriced["cost_usd"] = recalculated_cost
    repriced["tokens"] = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "cache_creation": usage.cache_creation_input_tokens,
        "cache_read": usage.cache_read_input_tokens,
    }
    repriced["cost_accounting"] = {
        "usage_source": usage.usage_source,
        "price_table_date": price_table.get("price_table_date"),
        "pricing_basis": price_table.get("pricing_basis"),
        "raw_cli_estimate_usd": usage.total_cost_usd,
        "repriced_from": str(raw_path),
    }
    return repriced, [*usage.warnings, *cost_warnings]



def load_results(results_dir: Path) -> pd.DataFrame:
    """Load ALL json result files from `results_dir` into a flat table, with 
    wall-clock times converted to seconds."""
    rows = []
    for path in sorted(results_dir.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            print(f"[warn] skipping unparseable result file: {path}")
    if not rows:
        return pd.DataFrame()

    df = pd.json_normalize(rows, sep=".")
    if "wall_clock_ms.total" in df.columns:
        df["wall_clock_total_s"] = df["wall_clock_ms.total"] / 1000.0
    if "wall_clock_ms.agent" in df.columns:
        df["wall_clock_agent_s"] = df["wall_clock_ms.agent"] / 1000.0
    if "wall_clock_ms.simulation" in df.columns:
        df["wall_clock_simulation_s"] = df["wall_clock_ms.simulation"] / 1000.0
    return df


def load_results_by_experiment_log(
    experiment_tasks: List[Dict], *, price_table: Optional[dict] = None,
    reprice: bool = False,
) -> pd.DataFrame:
    """Load only the result files that belong to this sweep into a flat table,
    with wall-clock times converted to seconds.

    Instead of blindly globbing every .json in the results directory (which may
    contain stale runs from earlier sweeps), this reads exactly the
    ``result_path`` from each item in the experiment-tasks log — one per
    (task, repeat) that was actually run.

    Args:
        experiment_tasks: list of tasks info; one dict per task executed
            in this sweep. Each dict matches the ``worktree_tasks_item`` shape
            written by ``run_experiment.py``, and must contain at least the key
            ``result_path`` (an absolute or relative path to its result JSON file).
        price_table: loaded pricing configuration used for in-memory repricing.
        reprice: when true, ignore each saved derived ``cost_usd`` and recompute
            it from the raw Claude result's whole-tree ``modelUsage`` counters.
    """
    if reprice and price_table is None:
        raise ValueError("price_table is required when reprice=True")

    rows = []
    repricing_warnings = []
    repriced_count = 0
    for item in experiment_tasks:
        path = Path(item["result_path"])
        if not path.exists():
            print(f"[warn] result file not found, skipping: {path}")
            continue
        try:
            result = json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"[warn] skipping unparseable result file: {path}")
            continue
        if reprice:
            result, result_warnings = reprice_result(result, path, price_table or {})
            repricing_warnings.extend(result_warnings)
            if result.get("cost_usd") is not None:
                repriced_count += 1
        rows.append(result)
    if not rows:
        return pd.DataFrame()

    df = pd.json_normalize(rows, sep=".")
    if "wall_clock_ms.total" in df.columns:
        df["wall_clock_total_s"] = df["wall_clock_ms.total"] / 1000.0
    if "wall_clock_ms.agent" in df.columns:
        df["wall_clock_agent_s"] = df["wall_clock_ms.agent"] / 1000.0
    if "wall_clock_ms.simulation" in df.columns:
        df["wall_clock_simulation_s"] = df["wall_clock_ms.simulation"] / 1000.0
    df.attrs["cost_repricing"] = {
        "enabled": reprice,
        "repriced_count": repriced_count,
        "warning_count": len(repricing_warnings),
        "warnings": repricing_warnings,
        "price_table_date": (price_table or {}).get("price_table_date"),
        "pricing_basis": (price_table or {}).get("pricing_basis"),
    }
    return df


def summary_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (condition, model): n, success rate, median cost/time — the
    plain descriptive view. NOT the primary reporting format for cost/time per
    §5 ("don't run a plain paired test on raw dollar-cost or wall-clock" — use
    success_at_budget_curve below instead), but useful as a quick sanity check.
    
    It checks which of the two grouping columns (condition, model) actually exist 
    in the data, and groups by whichever are present. This makes the function robust — 
    it still works if, say, only one model was run and the model column is absent.
    
    **Aggregation**
    For each (condition, model) group, it computes summary statistics:
    Col                         What it measures
    n                           Number of runs (count of run_id); namely number of tasks executed
    n_verified_success          Number of tasks verified as successful
    n_verified_failure          Number of tasks verified as failed
    n_unverified                Number of tasks unverified
    disagreements	            Number of tasks with disagreement between the raw task execution result and the verification result
    success_rate	            success_rate = n_verified_success / (n_verified_success + n_verified_failure)
    median_cost_usd	            Median dollar cost across all runs
    median_wall_clock_total_s	Median total wall-clock time in seconds
    median_attempts	            Median number of attempts per run
    
    Medians are used instead of means because cost and time distributions are typically skewed — 
    a few very expensive/slow runs would pull a mean upward, but the median is robust to outliers.
    """
    if df.empty:
        return df

    group_cols = [c for c in ("condition", "model") if c in df.columns]

    # Per the docstring: success can be True, False, or None (unverified).
    # success_rate excludes unverified tasks from the denominator.
    agg = df.groupby(group_cols).agg(
        n=("run_id", "count"),
        n_verified_success=("verified_success", lambda s: int((s == True).sum())),
        n_verified_failure=("verified_success", lambda s: int((s == False).sum())),
        n_unverified=("verified_success", lambda s: int(s.isna().sum())),
        n_costed=("cost_usd", "count"),
        median_cost_usd=("cost_usd", "median"),
        total_cost_usd=("cost_usd", lambda s: s.sum(min_count=1)),
        median_wall_clock_total_s=("wall_clock_total_s", "median"),
        median_attempts=("attempts", "median"),
    )

    # Count explicit disagreements (verification_agreement == False, not None)
    if "verification_agreement" in df.columns:
        disagree_agg = (
            df.groupby(group_cols)["verification_agreement"]
            .apply(lambda s: int((s == False).sum()))
            .rename("disagreements")
        )
        agg = agg.join(disagree_agg)
    else:
        agg["disagreements"] = 0

    # success_rate = n_verified_success / (n_verified_success + n_verified_failure)
    denom = agg["n_verified_success"] + agg["n_verified_failure"]
    agg["success_rate"] = (agg["n_verified_success"] / denom).where(denom > 0, other=None)

    return agg.reset_index()


def empirical_success_step_curve(
    df: pd.DataFrame, metric: str, end: Optional[float] = None,
) -> tuple[list[float], list[float], int, int]:
    """Build a fixed-denominator empirical fraction-solved step curve.

    Only runs with both a metric value and a verified boolean outcome are eligible.
    Every verified success raises the curve by ``1 / n`` at its observed metric
    value. Verified failures remain in ``n`` forever and never raise the curve, so
    the final plateau is the observed verified success rate rather than 1.0.

    Returns ``(x, y, n, n_success_by_end)``. When ``end`` is provided, events
    after that plotting horizon are omitted and the curve terminates exactly at
    ``end``. This keeps the visible endpoint consistent with point estimates at
    the same budget.
    """
    if df.empty or metric not in df.columns or "verified_success" not in df.columns:
        return [], [], 0, 0

    eligible = df[df[metric].notna() & df["verified_success"].notna()]
    n = len(eligible)
    if n == 0:
        return [], [], 0, 0

    observed_end = float(eligible[metric].max())
    curve_end = float(end) if end is not None else observed_end
    success_times = (
        eligible.loc[
            eligible["verified_success"].eq(True)
            & eligible[metric].le(curve_end),
            metric,
        ]
        .astype(float)
        .value_counts()
        .sort_index()
    )
    xs = [0.0]
    ys = [0.0]
    solved = 0
    for value, count in success_times.items():
        solved += int(count)
        xs.append(float(value))
        ys.append(solved / n)

    if curve_end > xs[-1]:
        xs.append(curve_end)
        ys.append(solved / n)

    return xs, ys, n, solved


def success_at_budget_curve(
    df: pd.DataFrame,
    metric: str,
    budgets: list[float],
    ceiling: Optional[float] = None,
) -> pd.DataFrame:
    """Empirical fraction of verified runs solved within each budget.

    The denominator is fixed within each (condition, model) group and includes
    verified failures. A failure is never solved, so it contributes zero at every
    budget and the curve plateaus at the observed verified success rate. Runs with
    no verification outcome or no metric value are excluded from ``n``.

    ``ceiling`` is retained for API compatibility but is intentionally ignored;
    fixed-denominator empirical curves do not censor verified failures.
    """
    _ = ceiling
    if (
        df.empty
        or metric not in df.columns
        or "verified_success" not in df.columns
    ):
        return pd.DataFrame()

    # ===== loop over (condition, model) groups =====
    rows = []
    group_cols = [c for c in ("condition", "model") if c in df.columns]
    for keys, group in df.groupby(group_cols):
        
        # ----- keep only runs with an observed metric and verified outcome -----
        keys = keys if isinstance(keys, tuple) else (keys,)
        eligible = group[group[metric].notna() & group["verified_success"].notna()]
        if eligible.empty:
            continue

        successes = eligible[eligible["verified_success"].eq(True)]
        
        # ----- build output row for plot -----
        # first two columns are the (condition, model)
        row = dict(zip(group_cols, keys))
        
        # `n` is the fixed denominator: all verified runs with this metric.
        row["n"] = len(eligible)
        
        # add multiple col values (for each budget) for current row
        # each col has name `solved_by_<b>`
        for b in budgets:
            row[f"solved_by_{b}"] = float((successes[metric] <= b).sum()) / len(eligible)
            
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--metric", default="cost_usd", help="e.g. cost_usd, wall_clock_total_s")
    parser.add_argument("--budgets", default="0.1,0.5,2,10")
    parser.add_argument(
        "--ceiling", type=float, default=None,
        help="deprecated compatibility option; ignored by empirical curves",
    )
    args = parser.parse_args()

    # ====== Load the experiment-tasks log and pass it to load_results ======
    experiment_tasks_path = args.results_dir / "experiment_tasks.jsonl"
    if not experiment_tasks_path.exists():
        print(f"No experiment tasks log found at {experiment_tasks_path} — nothing to aggregate.")
        print("(Phase 0 ships this aggregator ahead of any runs, per test/experiments.md §8 Phase 0.)")
        return

    experiment_tasks_jsonl = []
    with experiment_tasks_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                experiment_tasks_jsonl.append(json.loads(line))

    df = load_results(experiment_tasks_jsonl)
    if df.empty:
        print(f"No valid result files loaded from {experiment_tasks_path} — nothing to aggregate.")
        return

    print(f"Loaded {len(df)} result rows from {experiment_tasks_path}\n")

    print("=== Summary table (§5 descriptive view) ===")
    print(summary_table(df).to_string(index=False))


    # ==== Success-at-budget curve (§3.2.4/§3.2.5) ======
    budgets = [float(b) for b in args.budgets.split(",")]
    print(f"\n=== Success-at-budget curve on '{args.metric}' (§3.2.4/§3.2.5) ===")
    curve_df = success_at_budget_curve(df, args.metric, budgets, ceiling=args.ceiling)
    if curve_df.empty:
        print(f"(no non-null '{args.metric}' values to build a curve from)")
    else:
        print(curve_df.to_string(index=False))


if __name__ == "__main__":
    main()
