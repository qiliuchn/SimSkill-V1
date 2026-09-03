r"""Plot experiment score histograms by condition.

This script reads ``score`` directly from an experiment-tasks JSONL log.  It
ignores records whose score is missing or null, groups the remaining scores by
experiment condition, and draws every non-empty condition histogram on shared
0-to-1 axes.  Conditions without scored records are omitted.

As in ``print_primary_comparisons.py``, task models are kept separate: one plot
is produced per model, and all available conditions for that model share the
same figure.  When more than one model is selected, the model key is inserted
into each output filename.

Examples:

    # Plot all scored conditions from the default experiment log.
    python test/harness/print_score_hist.py

    # Plot scores from a user-supplied experiment log.
    python test/harness/print_score_hist.py --experiment-tasks /path/to/experiment_tasks.jsonl

    # Select conditions and a task model.
    python test/harness/print_score_hist.py --conditions full-ver,vanilla-cc --models deepseek-v4-pro

    # Use twenty shared bins and choose the output path.
    python test/harness/print_score_hist.py --bins 20 --output test/results/my_score_hist.png
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Optional, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_experiment as re1


DEFAULT_EXPERIMENT_TASKS = re1.REPO_ROOT / "test" / "experiment_tasks.jsonl"
DEFAULT_OUTPUT = re1.REPO_ROOT / "test" / "score_hist.png"

PLOT_CONDITIONS = (
    "full-ver",
    "proc-mem-ver",
    "sem-mem-ver",
    "infer-frame-only",
    "vanilla-cc",
)

COLOR_SCHEME = {
    "full-ver": "#d62728",
    "vanilla-cc": "#1f77b4",
    "proc-mem-ver": "#DAA520",
    "sem-mem-ver": "#2ca02c",
    "infer-frame-only": "#9467bd",
}

LINE_STYLES = ("-", "--", "-.", ":", (0, (5, 2, 1, 2)))


def load_experiment_tasks(path: Path) -> list[dict]:
    """Load JSONL records and identify malformed input by line number."""
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSON in {path} at line {line_number}: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    f"invalid record in {path} at line {line_number}: "
                    "expected a JSON object"
                )
            records.append(record)
    return records


def parse_csv_filter(value: Optional[str]) -> Optional[list[str]]:
    """Parse a comma-separated filter while preserving the requested order."""
    if value is None:
        return None
    values: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if part and part not in values:
            values.append(part)
    return values


def canonical_score(value: object) -> Optional[float]:
    """Return a valid numeric score, or ``None`` for missing/invalid values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        score = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        return None
    return score


def record_condition(record: dict) -> Optional[str]:
    """Return the experiment condition from the current or legacy field name."""
    value = record.get("task_condition", record.get("condition"))
    return value if isinstance(value, str) and value else None


def record_model(record: dict) -> Optional[str]:
    """Return the task model from the current or legacy field name."""
    value = record.get("task_model", record.get("model"))
    return value if isinstance(value, str) and value else None


def collect_scores(
    records: Sequence[dict],
    *,
    conditions: Optional[Sequence[str]] = None,
    models: Optional[Sequence[str]] = None,
) -> tuple[dict[str, dict[str, list[float]]], int]:
    """Group valid scores as ``model -> condition -> scores``.

    Missing/null scores are silently ignored.  The returned integer counts
    non-null score values that were ignored because they were malformed,
    non-finite, or outside the required range.
    """
    wanted_conditions = set(conditions) if conditions is not None else None
    wanted_models = set(models) if models is not None else None
    grouped: dict[str, dict[str, list[float]]] = {}
    invalid_score_count = 0

    for record in records:
        condition = record_condition(record)
        model = record_model(record)
        if condition is None or model is None:
            continue
        if wanted_conditions is not None and condition not in wanted_conditions:
            continue
        if wanted_models is not None and model not in wanted_models:
            continue

        raw_score = record.get("score")
        if raw_score is None:
            continue
        score = canonical_score(raw_score)
        if score is None:
            invalid_score_count += 1
            continue
        grouped.setdefault(model, {}).setdefault(condition, []).append(score)

    return grouped, invalid_score_count


def ordered_conditions(
    available: Sequence[str], requested: Optional[Sequence[str]] = None
) -> list[str]:
    """Order known conditions consistently, followed by any custom conditions."""
    available_set = set(available)
    if requested is not None:
        return [condition for condition in requested if condition in available_set]
    known = [condition for condition in PLOT_CONDITIONS if condition in available_set]
    extras = sorted(available_set.difference(PLOT_CONDITIONS))
    return known + extras


def shared_bin_edges(bin_count: int) -> list[float]:
    """Return fixed bin edges spanning the full valid score range."""
    if bin_count <= 0:
        raise ValueError("bin count must be greater than zero")
    return [index / bin_count for index in range(bin_count + 1)]


def plot_score_histograms(
    ax,
    condition_scores: dict[str, list[float]],
    *,
    conditions: Sequence[str],
    bin_count: int,
    model: str,
) -> None:
    """Draw all non-empty condition histograms on one shared Axes."""
    bin_edges = shared_bin_edges(bin_count)

    for index, condition in enumerate(conditions):
        scores = condition_scores.get(condition) or []
        if not scores:
            continue
        mean_score = statistics.fmean(scores)
        ax.hist(
            scores,
            bins=bin_edges,
            histtype="step",
            linewidth=2.0,
            linestyle=LINE_STYLES[index % len(LINE_STYLES)],
            color=COLOR_SCHEME.get(condition),
            label=f"{condition} (n={len(scores)}, mean={mean_score:.3f})",
        )

    ax.set_title(f"Score distributions by condition (model={model})", fontsize=14)
    ax.set_xlabel("Task completion score", fontsize=12)
    ax.set_ylabel("Number of scored runs", fontsize=12)
    ax.set_xlim(0.0, 1.0)
    ax.set_xticks([index / 10 for index in range(11)])
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=10)


def output_path_for_model(base_path: Path, model: str, multiple_models: bool) -> Path:
    """Insert *model* before the suffix when producing multiple figures."""
    if not multiple_models:
        return base_path
    return base_path.with_name(f"{base_path.stem}_{model}{base_path.suffix}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--experiment-tasks",
        type=Path,
        default=DEFAULT_EXPERIMENT_TASKS,
        metavar="PATH",
        help=(
            "path to the experiment-tasks JSONL log to read "
            "(default: test/experiment_tasks.jsonl)"
        ),
    )
    parser.add_argument(
        "--conditions",
        default=None,
        help="comma-separated condition names to plot (default: all with scores)",
    )
    parser.add_argument(
        "--models",
        default=None,
        help="comma-separated task-model keys to plot (default: all with scores)",
    )
    parser.add_argument(
        "--bins",
        type=int,
        default=10,
        help="number of equal-width bins over [0, 1] (default: 10)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="output image path (default: test/score_hist.png)",
    )
    args = parser.parse_args(argv)

    if args.bins <= 0:
        parser.error("--bins must be greater than zero")
    experiment_tasks_path = args.experiment_tasks.expanduser()
    if not experiment_tasks_path.is_file():
        print(
            f"Experiment tasks log not found at {experiment_tasks_path} — "
            "nothing to plot."
        )
        return 0

    try:
        records = load_experiment_tasks(experiment_tasks_path)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    if not records:
        print(
            f"Experiment tasks log at {experiment_tasks_path} is empty — "
            "nothing to plot."
        )
        return 0

    requested_conditions = parse_csv_filter(args.conditions)
    requested_models = parse_csv_filter(args.models)
    grouped, invalid_score_count = collect_scores(
        records,
        conditions=requested_conditions,
        models=requested_models,
    )
    if invalid_score_count:
        print(
            f"[warn] ignored {invalid_score_count} non-null invalid score "
            f"value(s); expected finite numbers in [0, 1]",
            file=sys.stderr,
        )

    models = sorted(grouped)
    if requested_models is not None:
        models = [model for model in requested_models if model in grouped]
    if not models:
        print(
            "No valid scores match the given --conditions / --models filters — "
            "nothing to plot."
        )
        return 0

    multiple_models = len(models) > 1
    for model in models:
        condition_scores = grouped[model]
        conditions = ordered_conditions(condition_scores, requested_conditions)
        if not conditions:
            continue

        fig, ax = plt.subplots(figsize=(7.5, 5.0))
        plot_score_histograms(
            ax,
            condition_scores,
            conditions=conditions,
            bin_count=args.bins,
            model=model,
        )
        fig.tight_layout()

        output_path = output_path_for_model(args.output, model, multiple_models)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

        score_count = sum(len(condition_scores[condition]) for condition in conditions)
        print(
            f"Plot saved to {output_path} "
            f"({score_count} scored run(s), {len(conditions)} condition(s))"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
