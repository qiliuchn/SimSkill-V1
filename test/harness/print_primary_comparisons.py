"""
Standalone script to print primary comparison results from SimSkill experiment
results, without re-running anything.

Loads result JSONs from the experiment-tasks log (a JSONL file written by
run_experiment.py that records every (task, repeat) actually executed in a
sweep), prints the summary table, and reports the pre-registered primary
comparisons (§5 of test/experiments.md): full-ver vs vanilla-cc, full-ver vs
proc-mem-ver, full-ver vs sem-mem-ver — for every condition and model present.

Also plots the empirical success-at-budget curves (§3.2.4/§3.2.5) for all five
experiment conditions together, omitting only conditions that have no data for
the selected model and metric. Verified failures remain in the denominator and
are never solved, so each curve plateaus at that condition's verified success
rate; each one is marked at the cost/wall-clock it consumed, drawn on its
condition's curve. Each legend entry counts every run the experiment log holds
for that condition (verified successes / runs executed), and names how many of
them lacked the plotted metric and so could not be placed on the axis. Unless `--budgets` pins the axis, the x range covers every
trial executed — successes and failures alike — so no marker is cut off.

Useful for re-checking results after closing the terminal, or for inspecting a
subset of conditions/models without running the full run_experiment_1.py grid.


## CLI Flags and options

| Flag | Default | Description |
|---|---|---|
| `--experiment-tasks` | `test/experiment_tasks.jsonl` | Path to the JSONL log written by the sweep driver; each line records one (task, repeat) actually executed. |
| `--conditions` | *(all present)* | Comma-separated condition names to filter by (e.g. `full-ver,vanilla-cc`). |
| `--models` | *(all present)* | Comma-separated model keys to filter by (e.g. `claude-opus-5`). |
| `--metric` | `cost_usd` | Metric for the budget axis of the success-at-budget plot. Also accepted: `wall_clock_total_s`. |
| `--budgets` | *(none)* | Comma-separated budget thresholds for the optional point-estimate table (e.g. `0.1,0.5,2,10`). The largest value is also the plot's exact x-axis maximum, and any trial that ran past it is dropped from the plot — a warning names how many. When omitted, the axis spans every trial executed, success or failure, plus 5%. |
| `--price-table` | `test/harness/price_table.yaml` | Rates used to reprice every saved run from its raw whole-tree `modelUsage`. |
| `--stored-costs` | `False` | Use the historical derived `cost_usd` values instead of repricing raw usage. |
| `--ceiling` | *(none)* | Deprecated compatibility option; ignored by empirical curves. |
| `--output` | `test/results/success_at_budget_curves_{metric}.png` | Path to save the plot PNG. Default embeds the metric name so different `--metric` runs don't overwrite each other. When multiple models are present, the model name is also inserted. |
| `--label-task-ids` | `False` | Draw a node at every visible verified-success jump and annotate it with the task ID. Also annotates the verified-failure 'x' markers. |
| `--no-failure-markers` | `False` | Suppress the 'x' markers that show where each verified failure spent its budget. |
| `--no-plot` | `False` | Skip plotting entirely; print the text tables only. |


## Usage
    # Print everything from the default experiment-tasks log
    python test/harness/print_primary_comparisons.py

    # Filter to specific conditions and models
    python test/harness/print_primary_comparisons.py --conditions full-ver,vanilla-cc --models claude-haiku-4-5

    # Point at a specific experiment-tasks log
    python test/harness/print_primary_comparisons.py --experiment-tasks /path/to/experiment_tasks.jsonl

    # Text-only (no plot)
    python test/harness/print_primary_comparisons.py --no-plot

    # Cost curves with point estimates at specific budget thresholds
    python test/harness/print_primary_comparisons.py --metric cost_usd --budgets 0.1,0.5,2,10

    # Wall-clock curves with custom budget range
    python test/harness/print_primary_comparisons.py --metric wall_clock_total_s --budgets 60,300,900,3600

    # Custom output path
    python test/harness/print_primary_comparisons.py --output test/results/my_curves.png

    # Label verified-success nodes (and verified-failure 'x' marks) with task IDs
    python test/harness/print_primary_comparisons.py --metric cost_usd --label-task-ids

    # Success curves only, without the verified-failure 'x' marks
    python test/harness/print_primary_comparisons.py --no-failure-markers
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter
import matplotlib.colors as mcolors
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import aggregate_results
import cost_time
import run_experiment as re1

DEFAULT_EXPERIMENT_TASKS = re1.REPO_ROOT / "test" / "experiment_tasks.jsonl"
DEFAULT_OUTPUT_DIR = re1.REPO_ROOT / "test"
DEFAULT_PRICE_TABLE = re1.HARNESS_DIR / "price_table.yaml"

PRIMARY_COMPARISONS = [
    ("full-ver", "vanilla-cc"),
    ("full-ver", "proc-mem-ver"),
    ("full-ver", "sem-mem-ver"),
    ("full-ver", "infer-frame-only"),
]

PLOT_CONDITIONS = (
    "full-ver",
    "proc-mem-ver",
    "sem-mem-ver",
    "infer-frame-only",
    "vanilla-cc",
)

if False:
    PLOT_CONDITIONS = (
        "full-ver",
        "vanilla-cc",
    )

color_scheme = {
    "full-ver": "#d62728",
    "vanilla-cc": "#1f77b4",
    "proc-mem-ver": "#DAA520",
    "sem-mem-ver": "#2ca02c",
    "infer-frame-only": "#9467bd",
}

def darken_color(color, factor=0.70):
    """Darken a matplotlib color. factor < 1 makes it darker."""
    rgb = mcolors.to_rgb(color)
    return tuple(c * factor for c in rgb)


def print_primary_comparisons(df, conditions: set[str], model: str) -> None:
    """Print the §5 pre-registered pairwise comparisons for one model."""
    summary = aggregate_results.summary_table(df[df["model"] == model])
    if summary is None or summary.empty:
        print(f"  (no results for model={model})")
        return

    by_condition = summary.set_index("condition")

    for a, b in PRIMARY_COMPARISONS:
        if a not in conditions and b not in conditions:
            continue
        if a not in by_condition.index or b not in by_condition.index:
            missing = []
            if a not in by_condition.index:
                missing.append(a)
            if b not in by_condition.index:
                missing.append(b)
            print(
                f"  {a} vs {b}  (model={model}):  "
                f"no results for {', '.join(missing)}"
            )
            continue

        ra, rb = by_condition.loc[a], by_condition.loc[b]

        def fmt(v):
            if v is None or (isinstance(v, float) and v != v):  # NaN check
                return "n/a"
            return f"{v:.2f}"

        print(
            f"  {a} vs {b}  (model={model}):  "
            f"success_rate  {fmt(ra['success_rate'])} vs {fmt(rb['success_rate'])}  |  "
            f"median_cost_usd  {fmt(ra['median_cost_usd'])} vs {fmt(rb['median_cost_usd'])}  |  "
            f"median_wall_clock_total_s  {fmt(ra['median_wall_clock_total_s'])} vs {fmt(rb['median_wall_clock_total_s'])}"
        )


# ======================================================================
# Empirical success-at-budget plotting helpers
# ======================================================================

def _success_nodes(
    group: pd.DataFrame, metric: str, plot_end: float, denominator: int,
) -> list[tuple[float, float, str]]:
    """Return visible success-jump nodes as ``(x, y, task_ids)`` tuples."""
    if denominator == 0 or "task_id" not in group.columns:
        return []

    successes = group[
        group["verified_success"].eq(True)
        & group[metric].notna()
        & group[metric].le(plot_end)
    ].copy()
    if successes.empty:
        return []

    nodes = []
    solved = 0
    for value, at_value in successes.groupby(metric, sort=True):
        solved += len(at_value)
        task_ids = [
            str(task_id)
            for task_id in at_value["task_id"]
            if pd.notna(task_id)
        ]
        nodes.append((float(value), solved / denominator, ", ".join(task_ids)))
    return nodes


def _curve_value_at(xs: list[float], ys: list[float], x: float) -> float:
    """Height of the ``where="post"`` step curve at ``x``.

    A jump at ``x`` is already in effect there, so a point landing exactly on a
    success node sits on top of the riser rather than under it.
    """
    index = max(bisect.bisect_right(xs, x) - 1, 0)
    return ys[index]


def _failure_nodes(
    group: pd.DataFrame, metric: str, plot_end: float,
    xs: list[float], ys: list[float],
) -> list[tuple[float, float, str]]:
    """Return verified-failure markers as ``(x, y, task_ids)`` tuples.

    A verified failure never raises the curve — it only enlarges the denominator —
    so it is placed at the curve's own height at its observed metric value, marking
    the budget a run consumed without solving its task.
    """
    if not xs or metric not in group.columns:
        return []

    failures = group[
        group["verified_success"].eq(False)
        & group[metric].notna()
        & group[metric].le(plot_end)
    ]
    if failures.empty:
        return []

    has_task_ids = "task_id" in group.columns
    nodes = []
    for value, at_value in failures.groupby(metric, sort=True):
        task_ids = [
            str(task_id)
            for task_id in at_value["task_id"]
            if pd.notna(task_id)
        ] if has_task_ids else []
        nodes.append(
            (float(value), _curve_value_at(xs, ys, float(value)), ", ".join(task_ids))
        )
    return nodes


def _plot_conditions(
    ax, df: pd.DataFrame, metric: str, conditions: list[str], model: str,
    specified_budgets: list[float] | None,
    label_task_ids: bool,
    mark_failures: bool = True,
) -> None:
    """Plot every available condition's success-at-budget curve on one Axes."""
    plot_data = df[
        df["condition"].isin(conditions)
        & (df["model"] == model)
        & df[metric].notna()
        & df["verified_success"].notna()
    ]
    if plot_data.empty:
        return

    # The x range must span every trial actually executed — verified failures
    # included. A failure's marker sits at the budget it burned, so it is as much
    # an observation as a success and must never fall off the right edge.
    observed_max = float(plot_data[metric].max())
    if specified_budgets:
        plot_end = max(specified_budgets)
        off_axis = int((plot_data[metric] > plot_end).sum())
        if off_axis:
            print(
                f"[warn] --budgets caps the x axis at {plot_end:.4g}, but "
                f"{off_axis} of {len(plot_data)} trial(s) for model={model} ran "
                f"past it (largest {metric} = {observed_max:.4g}); those runs — "
                "successes and failures alike — are not drawn. Omit --budgets, "
                f"or raise its largest value above {observed_max:.4g}, to show "
                "every trial.",
                file=sys.stderr,
            )
    else:
        plot_end = observed_max * 1.1 if observed_max > 0 else 1.0

    drew_failures = False
    for cond in conditions:
        group = df[(df["condition"] == cond) & (df["model"] == model)]
        if group.empty:
            continue
        xs, ys, n, n_success = aggregate_results.empirical_success_step_curve(
            group, metric, end=plot_end,
        )
        if not xs:
            continue

        # If a success occurs exactly at the right boundary, do not terminate the
        # visible line with a vertical stroke. Show the left-limit as an open point
        # and the inclusive value at the boundary as the filled endpoint instead.
        # This is the standard closed-endpoint representation of a jump at x_max.
        line_ys = list(ys)
        boundary_jump = (
            len(xs) >= 2
            and math.isclose(xs[-1], plot_end)
            and not math.isclose(ys[-1], ys[-2])
        )
        if boundary_jump:
            line_ys[-1] = ys[-2]

        # The legend reports this condition's full record from the experiment log —
        # every (task, repeat) executed — not just the subset the curve could place
        # on the budget axis. A run whose metric is missing cannot be drawn, but it
        # still happened, so hiding it from the counts would understate n. Any such
        # gap is named explicitly rather than silently shrinking the denominator.
        total_runs = len(group)
        total_success = int(group["verified_success"].eq(True).sum())
        label = f"{cond} (solved: {total_success}/{total_runs})"
        not_plotted = total_runs - n

        line, = ax.step(
            xs,
            line_ys,
            where="post",
            label=label,
            linewidth=1.5,
            color=color_scheme.get(cond),
        )
        if boundary_jump:
            ax.plot(
                plot_end,
                ys[-2],
                marker="o",
                markersize=4,
                markerfacecolor="none",
                markeredgecolor=line.get_color(),
                linestyle="None",
                clip_on=False,
            )
        # Mark the inclusive value at the closed right endpoint explicitly — but
        # only where that endpoint means something: a budget the caller asked
        # about, or a jump landing exactly on it. When the axis merely pads 5%
        # past the last observation, nothing happened at plot_end, and a dot per
        # condition there is decoration that reads as data.
        if specified_budgets or boundary_jump:
            ax.plot(
                plot_end,
                ys[-1],
                marker="o",
                markersize=4,
                linestyle="None",
                color=line.get_color(),
                clip_on=False,
            )

        if label_task_ids:
            nodes = _success_nodes(group, metric, plot_end, n)
            if nodes:
                ax.scatter(
                    [node[0] for node in nodes],
                    [node[1] for node in nodes],
                    s=13,
                    color=line.get_color(),
                    zorder=line.get_zorder() + 1,
                )
            for node_x, node_y, task_ids in nodes:
                if not task_ids:
                    continue
                ax.annotate(
                    task_ids,
                    xy=(node_x, node_y),
                    xytext=(4, -4),
                    textcoords="offset points",
                    ha="left",
                    va="top",
                    fontsize=6.5,
                    rotation=-45,
                    rotation_mode="anchor",
                    color=line.get_color(),
                    annotation_clip=True,
                )

        # Verified failures never raise the curve, so mark each one where it sits
        # on the curve: the budget it burned without solving its task.
        if mark_failures:
            failures = _failure_nodes(group, metric, plot_end, xs, ys)
            if failures:
                drew_failures = True
                ax.scatter(
                    [node[0] for node in failures],
                    [node[1] for node in failures],
                    marker=".",  # failure marker
                    s=36,
                    linewidths=1.2,
                    color=darken_color(line.get_color()),
                    zorder=line.get_zorder() + 2,
                    clip_on=False,
                )
            if label_task_ids:
                for node_x, node_y, task_ids in failures:
                    if not task_ids:
                        continue
                    ax.annotate(
                        task_ids,
                        xy=(node_x, node_y),
                        xytext=(4, 4),
                        textcoords="offset points",
                        ha="left",
                        va="bottom",
                        fontsize=6.5,
                        rotation=45,
                        rotation_mode="anchor",
                        color=line.get_color(),
                        annotation_clip=True,
                    )

    ax.set_xlabel(_metric_label(metric), fontsize=14)
    ax.set_ylabel("Fraction solved", fontsize=14)
    ax.set_title(
        f"(SimSkill LLM={model}, Judge LLM=claude-opus-5)",
        fontsize=16,
    )
    ax.set_xlim(0, plot_end)
    if specified_budgets:
        # Requested budgets double as meaningful x ticks, including the exact
        # right boundary rather than leaving the endpoint between auto ticks.
        ax.set_xticks(sorted({0.0, *specified_budgets}))
        ax.xaxis.set_major_formatter(
            FuncFormatter(lambda value, _position: f"{value:.4g}")
        )
    handles, _ = ax.get_legend_handles_labels()
    if drew_failures:
        handles.append(
            Line2D(
                [], [],
                linestyle="None",
                marker=".",  # failure marker
                markersize=5,
                markeredgewidth=1.2,
                color="0.35",
                label="task failure",
            )
        )
    ax.legend(handles=handles, fontsize=12,
              #loc="upper left",
              )
    ax.set_ylim(-0.02, 1.02)
    ax.grid(True, alpha=0.3)


def _metric_label(metric: str) -> str:
    if metric == "cost_usd":
        return "Cost (USD)"
    if metric == "wall_clock_total_s":
        return "Wall-clock time (s)"
    return metric


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--experiment-tasks", type=Path, default=DEFAULT_EXPERIMENT_TASKS,
        help="path to the experiment_tasks.jsonl log file (default: test/experiment_tasks.jsonl)",
    )
    parser.add_argument(
        "--conditions",
        default=None,
        help="comma-separated condition names to filter by (default: all present)",
    )
    parser.add_argument(
        "--models",
        default=None,
        help="comma-separated model keys to filter by (default: all present)",
    )
    parser.add_argument(
        "--metric", default="cost_usd",
        help="metric for the budget axis of the success-at-budget plot (default: cost_usd)",
    )
    parser.add_argument(
        "--budgets",
        default=None,
        help=(
            "comma-separated budget thresholds at which to also print a table of "
            "fraction-solved point estimates (e.g. 0.1,0.5,2,10); the largest "
            "threshold is also the plot's x-axis maximum. Omit to skip the table "
            "and plot 5%% beyond the largest observed value."
        ),
    )
    parser.add_argument(
        "--price-table", type=Path, default=DEFAULT_PRICE_TABLE,
        help=(
            "pricing table used to reprice raw whole-tree modelUsage "
            "(default: test/harness/price_table.yaml)"
        ),
    )
    parser.add_argument(
        "--stored-costs", action="store_true",
        help=(
            "use cost_usd frozen in each result JSON instead of repricing its "
            "raw whole-tree modelUsage"
        ),
    )
    parser.add_argument(
        "--ceiling", type=float, default=None,
        help="deprecated compatibility option; ignored by empirical curves",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="path to save the plot PNG (default: test/results/success_at_budget_curves_{metric}.png)",
    )
    parser.add_argument(
        "--label-task-ids",
        action="store_true",
        help="label each visible verified-success node with its task ID",
    )
    parser.add_argument(
        "--no-failure-markers",
        action="store_true",
        help="do not mark verified failures with an 'x' on their condition's curve",
    )
    parser.add_argument(
        "--no-plot", action="store_true",
        help="skip plotting; print the text tables only",
    )
    args = parser.parse_args()

    budgets = None
    if args.budgets is not None:
        try:
            budgets = [float(value) for value in args.budgets.split(",")]
        except ValueError as exc:
            parser.error(f"--budgets must be comma-separated numbers: {exc}")
        if not budgets or any(
            not math.isfinite(value) or value <= 0 for value in budgets
        ):
            parser.error("--budgets values must be finite numbers greater than zero")

    # ---- Load the experiment-tasks JSONL log ----
    experiment_tasks_path: Path = args.experiment_tasks
    if not experiment_tasks_path.exists():
        print(f"Experiment tasks log not found at {experiment_tasks_path} — nothing to print.")
        return

    experiment_tasks_jsonl = []
    with experiment_tasks_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                experiment_tasks_jsonl.append(json.loads(line))

    if not experiment_tasks_jsonl:
        print(f"Experiment tasks log at {experiment_tasks_path} is empty — nothing to print.")
        return

    # ---- Build DataFrame from the result files referenced in the log ----
    # Saved ``cost_usd`` fields are derived snapshots and may use old prices or
    # top-level-only usage. Reprice from raw ``modelUsage`` by default so the
    # command counts the entire agent tree, including subagents.
    price_table = None
    if not args.stored_costs:
        if not args.price_table.is_file():
            parser.error(f"price table not found: {args.price_table}")
        price_table = cost_time.load_price_table(args.price_table)
    df = aggregate_results.load_results_by_experiment_log(
        experiment_tasks_jsonl,
        price_table=price_table,
        reprice=not args.stored_costs,
    )
    if df.empty:
        print(f"No valid result files loaded from {experiment_tasks_path} — nothing to print.")
        return

    repricing = df.attrs.get("cost_repricing") or {}
    if repricing.get("enabled"):
        print(
            "Cost accounting: repriced "
            f"{repricing.get('repriced_count', 0)}/{len(df)} run(s) from raw "
            "whole-tree modelUsage using "
            f"{args.price_table} (price_table_date="
            f"{repricing.get('price_table_date')}, pricing_basis="
            f"{repricing.get('pricing_basis')})."
        )
        warning_count = int(repricing.get("warning_count") or 0)
        if warning_count:
            print(f"[warn] {warning_count} cost-repricing warning(s):")
            unique_warnings = list(dict.fromkeys(repricing.get("warnings") or []))
            for warning in unique_warnings[:10]:
                print(f"  - {warning}")
            if len(unique_warnings) > 10:
                print(f"  - ... {len(unique_warnings) - 10} more unique warning(s)")
        print()

    # ---- Filter ----
    if args.conditions:
        wanted_conditions = set(c.strip() for c in args.conditions.split(","))
        df = df[df["condition"].isin(wanted_conditions)]
    if args.models:
        wanted_models = set(m.strip() for m in args.models.split(","))
        df = df[df["model"].isin(wanted_models)]

    if df.empty:
        print("No results match the given --conditions / --models filters.")
        return
    if args.label_task_ids and "task_id" not in df.columns:
        print(
            "[warn] --label-task-ids requested, but result rows have no task_id column",
            file=sys.stderr,
        )

    # ---- Summary table ----
    print(f"=== {len(df)} run(s) loaded from {experiment_tasks_path} ===\n")
    print(aggregate_results.summary_table(df).to_string(index=False))

    # ---- Primary comparisons ----
    print("\n=== §5 pre-registered primary comparisons ===\n")

    conditions_in_df = set(df["condition"].unique())
    models_in_df = sorted(df["model"].unique())

    for model in models_in_df:
        print_primary_comparisons(df, conditions_in_df, model)
        print()  # blank line between models

    # ---- Optional point-estimate table at specific budgets ----
    if budgets is not None:
        print(
            f"=== Success-at-budget point estimates "
            f"(metric={args.metric}, budgets={args.budgets}) ===\n"
        )
        curve_df = aggregate_results.success_at_budget_curve(
            df, args.metric, budgets, ceiling=args.ceiling,
        )
        if curve_df.empty:
            print(f"  (no non-null '{args.metric}' values to build a curve from)\n")
        else:
            print(curve_df.to_string(index=False))
            print()

    # ---- Empirical success-at-budget plots ----
    if args.no_plot:
        return

    # Resolve default output path: include the metric name so different --metric
    # runs don't overwrite each other's plots.
    if args.output is None:
        args.output = DEFAULT_OUTPUT_DIR / f"success_at_budget_curves_{args.metric}.png"

    # One figure per model, with every condition that has plottable data sharing
    # the same axes.
    for model in models_in_df:
        model_data = df[
            (df["model"] == model)
            & df["condition"].isin(PLOT_CONDITIONS)
            & df[args.metric].notna()
            & df["verified_success"].notna()
        ]
        active_conditions = [
            condition
            for condition in PLOT_CONDITIONS
            if condition in set(model_data["condition"])
        ]
        if not active_conditions:
            print(
                f"(no conditions with non-null '{args.metric}' and verified "
                f"outcomes for model={model} — nothing to plot)"
            )
            continue

        fig, ax = plt.subplots(
            figsize=(
                7.5 if args.label_task_ids else 6.5,
                5.5 if args.label_task_ids else 4.5,
            ),
        )
        _plot_conditions(
            ax,
            df,
            args.metric,
            active_conditions,
            model,
            budgets,
            args.label_task_ids,
            not args.no_failure_markers,
        )

        fig.tight_layout()

        # If multiple models, embed model name in output filename.
        if len(models_in_df) > 1:
            stem = args.output.stem
            suffix = args.output.suffix
            out = args.output.with_name(f"{stem}_{model}{suffix}")
        else:
            out = args.output

        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"Plot saved to {out}")


if __name__ == "__main__":
    main()
