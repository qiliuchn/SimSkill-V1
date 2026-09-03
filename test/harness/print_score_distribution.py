r"""Create publication-quality score-distribution figures by task model.

The primary panel is an inclusive empirical survival function:

    S(t) = fraction of scored runs with score >= t

This is the complementary form of an empirical cumulative distribution
function (ECDF).  Unlike an overlaid histogram, it requires no bin choice,
normalizes conditions with different sample sizes, preserves ties and endpoint
masses, and permits direct threshold statements such as "70% of runs scored at
least 0.8".  Higher/rightward curves indicate better score distributions.

The companion panel uses a conventional horizontal boxplot together with every
observed score.  Boxes span the interquartile range, center lines are medians,
and whiskers follow the standard 1.5-IQR rule.  Vertically offset dots reduce
overplotting at exact ties and keep the underlying observations visible.

One figure is produced per task model.  PDF is the default because vector output
is generally preferable for academic manuscripts; PNG and SVG are also
supported by choosing the corresponding ``--output`` suffix.

Examples:

    # Default experiment log, vector output at test/score_distribution.pdf.
    python test/harness/print_score_distribution.py

    # A user-supplied scored experiment log.
    python test/harness/print_score_distribution.py \
        --experiment-tasks /path/to/experiment_tasks.jsonl

    # A filtered, high-resolution raster figure.
    python test/harness/print_score_distribution.py \
        --experiment-tasks /path/to/experiment_tasks.jsonl \
        --conditions full-ver,vanilla-cc --models deepseek-v4-pro \
        --output paper/score_distribution.png --dpi 600
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import print_score_hist as score_hist
import run_experiment as re1


DEFAULT_EXPERIMENT_TASKS = score_hist.DEFAULT_EXPERIMENT_TASKS
DEFAULT_OUTPUT = re1.REPO_ROOT / "test" / "score_distribution.pdf"

# Okabe-Ito-derived colors, paired with line styles so conditions remain
# distinguishable in grayscale and for readers with color-vision deficiencies.
CONDITION_COLORS = {
    "full-ver": "#D55E00",          # vermillion
    "vanilla-cc": "#0072B2",        # blue
    "proc-mem-ver": "#E69F00",      # orange
    "sem-mem-ver": "#009E73",       # bluish green
    "infer-frame-only": "#CC79A7",  # reddish purple
}
# Additional colorblind-safe colors for condition names not known in advance.
# These intentionally do not duplicate the five built-in condition colors.
CUSTOM_CONDITION_COLORS = (
    "#56B4E9",
    "#000000",
    "#332288",
    "#88CCEE",
    "#44AA99",
    "#117733",
    "#999933",
    "#882255",
    "#AA4499",
    "#661100",
    "#6699CC",
    "#888888",
)
LINE_STYLES = ("-", "--", "-.", ":", (0, (5, 2, 1, 2)))
SCORE_AXIS_PADDING = 0.015

PUBLICATION_STYLE = {
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans"],
    "font.size": 9.0,
    "axes.titlesize": 10.5,
    "axes.labelsize": 9.5,
    "axes.linewidth": 0.8,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "legend.fontsize": 12,
    "legend.frameon": False,
    "lines.linewidth": 1.8,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "savefig.facecolor": "white",
    "figure.facecolor": "white",
}


def inclusive_survival_points(
    scores: Sequence[float],
) -> tuple[list[float], list[float]]:
    """Return thresholds and ``P(score >= threshold)`` values.

    Thresholds include both endpoints of the valid score scale and collapse
    repeated scores.  Plot the result with ``where="pre"``: the inclusive
    survival function is left-continuous, so a run tied exactly at a threshold
    still counts at that threshold and drops immediately afterward.
    """
    if len(scores) == 0:
        raise ValueError("at least one score is required")

    values = np.asarray(scores, dtype=float)
    if (
        values.ndim != 1
        or not np.all(np.isfinite(values))
        or np.any(values < 0.0)
        or np.any(values > 1.0)
    ):
        raise ValueError("scores must be finite numbers in [0, 1]")

    thresholds = np.unique(np.concatenate(([0.0], values, [1.0])))
    survival = [
        float(np.count_nonzero(values >= threshold) / values.size)
        for threshold in thresholds
    ]
    return thresholds.tolist(), survival


def tied_score_offsets(
    scores: Sequence[float], *, half_width: float = 0.14
) -> list[float]:
    """Return deterministic vertical offsets that separate exact score ties."""
    if half_width < 0 or not math.isfinite(half_width):
        raise ValueError("half_width must be a finite non-negative number")

    offsets = [0.0] * len(scores)
    positions_by_score: dict[float, list[int]] = {}
    for index, score in enumerate(scores):
        positions_by_score.setdefault(float(score), []).append(index)

    for positions in positions_by_score.values():
        if len(positions) == 1:
            continue
        spread = np.linspace(-half_width, half_width, len(positions))
        for position, offset in zip(positions, spread):
            offsets[position] = float(offset)
    return offsets


def build_condition_color_map(conditions: Sequence[str]) -> dict[str, str]:
    """Assign non-colliding colors, independent of display order."""
    unique_conditions = set(conditions)
    color_map = {
        condition: color
        for condition, color in CONDITION_COLORS.items()
        if condition in unique_conditions
    }
    custom_conditions = sorted(unique_conditions.difference(CONDITION_COLORS))
    for index, condition in enumerate(custom_conditions):
        color_map[condition] = CUSTOM_CONDITION_COLORS[
            index % len(CUSTOM_CONDITION_COLORS)
        ]
    return color_map


def create_score_distribution_figure(
    condition_scores: dict[str, list[float]],
    *,
    conditions: Sequence[str],
    model: str,
    show_title: bool = True,
    condition_colors: Optional[Mapping[str, str]] = None,
    judge_model: str = "claude-opus-5",
) -> Figure:
    """Build the survival-ECDF plus box-and-dot figure for one task model."""
    if not conditions:
        raise ValueError("at least one condition is required")

    active_conditions: list[tuple[int, str, list[float]]] = []
    for index, condition in enumerate(conditions):
        scores = condition_scores.get(condition)
        if scores is None or len(scores) == 0:
            continue
        active_conditions.append((index, condition, list(scores)))
    if not active_conditions:
        raise ValueError("at least one condition with scores is required")

    resolved_colors = build_condition_color_map(
        [condition for _, condition, _ in active_conditions]
    )
    if condition_colors is not None:
        resolved_colors.update(condition_colors)

    with plt.rc_context(PUBLICATION_STYLE):
        figure, (survival_ax, summary_ax) = plt.subplots(
            1,
            2,
            figsize=(8.4, 4.8),
            gridspec_kw={"width_ratios": (1.2, 1.0)},
            constrained_layout=True,
        )

        for index, condition, scores in active_conditions:
            color = resolved_colors[condition]
            thresholds, survival = inclusive_survival_points(scores)
            median_score = statistics.median(scores)
            mean_score = statistics.fmean(scores)
            survival_ax.step(
                thresholds,
                survival,
                where="pre",
                color=color,
                linestyle=LINE_STYLES[index % len(LINE_STYLES)],
                label=(
                    f"{condition}  (n={len(scores)})\n"
                    f"median={median_score:.2f}, mean={mean_score:.2f}"
                ),
                solid_capstyle="butt",
                zorder=3,
            )

        survival_ax.set_title("A   Empirical survival function", loc="left", pad=8, fontsize=12)
        survival_ax.set_xlabel("Score threshold", fontsize=12)
        survival_ax.set_ylabel(
            "Proportion of scored runs with score ≥ threshold", fontsize=12
        )
        # A tiny view margin keeps endpoint masses from being hidden under the
        # axes; ticks and the statistical score domain remain exactly [0, 1].
        survival_ax.set_xlim(-SCORE_AXIS_PADDING, 1.0 + SCORE_AXIS_PADDING)
        survival_ax.set_ylim(0.0, 1.02)
        survival_ax.set_xticks(np.linspace(0.0, 1.0, 6))
        survival_ax.set_yticks(np.linspace(0.0, 1.0, 5))
        survival_ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0))
        survival_ax.grid(axis="both", color="#D9D9D9", linewidth=0.6, alpha=0.8)
        survival_ax.set_axisbelow(True)
        survival_ax.spines["top"].set_visible(False)
        survival_ax.spines["right"].set_visible(False)

        row_positions = list(range(len(active_conditions), 0, -1))
        row_labels: list[str] = []
        for (index, condition, scores), row_position in zip(
            active_conditions, row_positions
        ):
            color = resolved_colors[condition]
            row_labels.append(f"{condition}  (n={len(scores)})")

            summary_ax.boxplot(
                [scores],
                positions=[row_position],
                vert=False,
                widths=0.42,
                whis=1.5,
                showfliers=False,
                patch_artist=True,
                manage_ticks=False,
                boxprops={
                    "facecolor": color,
                    "edgecolor": color,
                    "alpha": 0.16,
                    "linewidth": 1.25,
                    "zorder": 3,
                },
                medianprops={
                    "color": "#222222",
                    "linewidth": 1.6,
                    "zorder": 4,
                },
                whiskerprops={"color": color, "linewidth": 1.1, "zorder": 3},
                capprops={"color": color, "linewidth": 1.1, "zorder": 3},
            )

            offsets = tied_score_offsets(scores)
            summary_ax.scatter(
                scores,
                [row_position + offset for offset in offsets],
                s=20,
                marker="o",
                facecolor=color,
                edgecolor="white",
                linewidth=0.4,
                alpha=0.78,
                clip_on=False,
                zorder=2,
            )

        summary_ax.set_title(
            "B   Median, IQR, and individual runs", loc="left", pad=8, fontsize=12
        )
        summary_ax.set_xlabel("Task completion score", fontsize=12)
        summary_ax.set_xlim(-SCORE_AXIS_PADDING, 1.0 + SCORE_AXIS_PADDING)
        summary_ax.set_xticks(np.linspace(0.0, 1.0, 6))
        summary_ax.set_ylim(0.45, len(active_conditions) + 0.55)
        summary_ax.set_yticks(row_positions)
        summary_ax.set_yticklabels(row_labels)
        summary_ax.grid(axis="x", color="#D9D9D9", linewidth=0.6, alpha=0.8)
        summary_ax.set_axisbelow(True)
        summary_ax.spines["top"].set_visible(False)
        summary_ax.spines["right"].set_visible(False)
        summary_ax.spines["left"].set_visible(False)
        summary_ax.tick_params(axis="y", length=0)

        if show_title:
            figure.suptitle(
                f"Task score distributions (SimSkill LLM={model}, judge LLM={judge_model})",
                fontsize=14,
                fontweight="semibold",
            )

        handles, labels = survival_ax.get_legend_handles_labels()
        legend_kwargs = {
            # Mean plus median makes labels fairly wide; two columns keep the
            # legend within a standard double-column manuscript figure.
            "ncol": min(2, len(labels)),
            "handlelength": 3.0,
            "columnspacing": 1.5,
        }
        try:
            # Matplotlib >= 3.7 lets constrained layout reserve an external
            # legend row, keeping the distribution curves unobstructed.
            figure.legend(
                handles,
                labels,
                loc="outside lower center",
                **legend_kwargs,
            )
        except ValueError:
            # Older Matplotlib releases do not recognize the ``outside``
            # location syntax.  bbox_inches="tight" still includes this row.
            figure.legend(
                handles,
                labels,
                loc="upper center",
                bbox_to_anchor=(0.5, -0.01),
                **legend_kwargs,
            )

    return figure


def save_publication_figure(
    figure: Figure, output_path: Path, *, dpi: int
) -> None:
    """Save with publication rcParams active, including editable PDF fonts."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with plt.rc_context(PUBLICATION_STYLE):
        figure.savefig(
            output_path,
            dpi=dpi,
            bbox_inches="tight",
            facecolor="white",
        )


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
        "--judge-model",
        default="claude-opus-5",
        help="(Judge LLM model to use for scoring)",
    )
    parser.add_argument(
        "--models",
        default=None,
        help="comma-separated task-model keys to plot (default: all with scores)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "output path; use .pdf/.svg for vector output "
            "(default: test/score_distribution.pdf)"
        ),
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="resolution for raster output such as PNG (default: 300)",
    )
    parser.add_argument(
        "--no-title",
        action="store_true",
        help="omit the overall model title when the paper caption supplies it",
    )
    args = parser.parse_args(argv)

    if args.dpi <= 0:
        parser.error("--dpi must be greater than zero")

    experiment_tasks_path = args.experiment_tasks.expanduser()
    if not experiment_tasks_path.is_file():
        print(
            f"Experiment tasks log not found at {experiment_tasks_path} — "
            "nothing to plot."
        )
        return 0

    try:
        records = score_hist.load_experiment_tasks(experiment_tasks_path)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    if not records:
        print(
            f"Experiment tasks log at {experiment_tasks_path} is empty — "
            "nothing to plot."
        )
        return 0

    requested_conditions = score_hist.parse_csv_filter(args.conditions)
    requested_models = score_hist.parse_csv_filter(args.models)
    grouped, invalid_score_count = score_hist.collect_scores(
        records,
        conditions=requested_conditions,
        models=requested_models,
    )
    if invalid_score_count:
        print(
            f"[warn] ignored {invalid_score_count} non-null invalid score "
            "value(s); expected finite numbers in [0, 1]",
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
    output_base = args.output.expanduser()
    judge_model = args.judge_model
    condition_colors = build_condition_color_map(
        [
            condition
            for model in models
            for condition in grouped[model]
        ]
    )
    for model in models:
        condition_scores = grouped[model]
        conditions = score_hist.ordered_conditions(
            condition_scores, requested_conditions
        )
        if not conditions:
            continue

        figure = create_score_distribution_figure(
            condition_scores,
            conditions=conditions,
            model=model,
            show_title=not args.no_title,
            condition_colors=condition_colors,
            judge_model=judge_model,
        )
        output_path = score_hist.output_path_for_model(
            output_base, model, multiple_models
        )
        try:
            save_publication_figure(figure, output_path, dpi=args.dpi)
        finally:
            plt.close(figure)

        score_count = sum(
            len(condition_scores[condition]) for condition in conditions
        )
        print(
            f"Publication figure saved to {output_path} "
            f"({score_count} scored run(s), {len(conditions)} condition(s), "
            f"model={model})"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
