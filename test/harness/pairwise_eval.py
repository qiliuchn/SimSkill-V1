"""Run blind pairwise evaluations over two experiment conditions.

For each task in the benchmark, this script finds exactly one experiment record
for each requested condition and the requested task model.  Pending pairs are
shown to an independent Claude Code judge in random order.  A valid judge result
is enriched with the condition-to-position mapping, then both experiment JSONL
records are updated with complementary boolean ``winner`` values and the shared
``pairwise_eval_result_path``.

The judge runs in one disposable ``vanilla-cc`` worktree, reused for the batch,
so bypass-permissions mode never runs from the user's main checkout.  The
experiment log is atomically replaced after every successful comparison.

Examples:

    python test/harness/pairwise_eval.py --conditions full-ver,vanilla-cc --model deepseek-v4-pro

    python test/harness/pairwise_eval.py --conditions full-ver vanilla-cc --model claude-haiku-4-5 --judge-model claude-opus-5
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_experiment as re1


DEFAULT_EXPERIMENT_TASKS = re1.REPO_ROOT / "test" / "experiment_tasks.jsonl"
DEFAULT_RESULTS_DIR = re1.DEFAULT_RESULTS_DIR / "pairwise_eval"
DEFAULT_PROMPT_TEMPLATE = (
    re1.REPO_ROOT / "test" / "harness" / "pairwise_eval_prompt_template.txt"
)
DEFAULT_MODELS_FILE = re1.REPO_ROOT / "test" / "harness" / "models.yaml"
DEFAULT_CONDITIONS_FILE = re1.REPO_ROOT / "test" / "harness" / "conditions.yaml"


@dataclass(frozen=True)
class Comparison:
    """The two experiment-log records to compare for one benchmark task."""

    task: dict  # benchmark task
    record_a: dict  # experiment tasks JSONL record
    record_b: dict


# ---------------------------------------------------------------------------
# Loading and persistence
# ---------------------------------------------------------------------------

def _atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace *path* with UTF-8 *text*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        if path.exists():
            temp_path.chmod(path.stat().st_mode)
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def load_experiment_tasks(path: Path) -> list[dict]:
    """Load a JSONL experiment log, reporting the line of malformed input."""
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


def write_experiment_tasks(path: Path, records: Sequence[dict]) -> None:
    """Atomically persist every JSONL record, including skipped records."""
    text = "".join(json.dumps(record, default=str) + "\n" for record in records)
    _atomic_write_text(path, text)


# ---------------------------------------------------------------------------
# Pair selection and randomization
# ---------------------------------------------------------------------------

def already_compared(record_a: dict, record_b: dict) -> bool:
    """Return true only when both records contain a non-null winner verdict."""
    return (
        "winner" in record_a
        and record_a["winner"] is not None
        and "winner" in record_b
        and record_b["winner"] is not None
    )


def collect_comparisons(
    benchmark_tasks: Sequence[dict],
    experiment_tasks: Sequence[dict],
    condition_a: str,
    condition_b: str,
    model: str,
) -> tuple[list[Comparison], int, int]:
    """Collect pending comparisons in benchmark order.

    A benchmark task is eligible only if exactly one record exists for each
    ``(task_id, condition, model)`` cell.  Ambiguous or missing cells are warned
    about and skipped instead of guessing how repeated runs should be paired.

    Returns ``(pending, already_compared_count, unavailable_count)``.
    """
    pending: list[Comparison] = []
    completed = 0
    unavailable = 0

    for task in benchmark_tasks:
        task_id = task.get("id")
        matches_a = [
            record
            for record in experiment_tasks
            if record.get("task_id") == task_id
            and record.get("task_condition") == condition_a
            and record.get("task_model") == model
        ]
        matches_b = [
            record
            for record in experiment_tasks
            if record.get("task_id") == task_id
            and record.get("task_condition") == condition_b
            and record.get("task_model") == model
        ]

        if len(matches_a) != 1 or len(matches_b) != 1:
            print(
                f"[WARN] task_id={task_id}: expected exactly one result for "
                f"condition '{condition_a}' and one for '{condition_b}' with "
                f"model '{model}', found {len(matches_a)} and {len(matches_b)}; "
                "skipping",
                file=sys.stderr,
            )
            unavailable += 1
            continue

        record_a, record_b = matches_a[0], matches_b[0]
        if already_compared(record_a, record_b):
            completed += 1
            continue

        missing_paths = [
            condition
            for condition, record in (
                (condition_a, record_a),
                (condition_b, record_b),
            )
            if not record.get("episodic_path")
        ]
        if missing_paths:
            print(
                f"[WARN] task_id={task_id}: missing episodic_path for "
                f"condition(s) {', '.join(missing_paths)}; skipping",
                file=sys.stderr,
            )
            unavailable += 1
            continue

        pending.append(Comparison(task=task, record_a=record_a, record_b=record_b))

    return pending, completed, unavailable


def randomize_comparison(
    comparison: Comparison,
    condition_a: str,
    condition_b: str,
    rng: random.Random,
) -> tuple[tuple[dict, str], tuple[dict, str]]:
    """Return ``((record_1, condition_1), (record_2, condition_2))`` blindly."""
    sides = [
        (comparison.record_a, condition_a),
        (comparison.record_b, condition_b),
    ]
    rng.shuffle(sides)
    return sides[0], sides[1]


# ---------------------------------------------------------------------------
# Prompt, command, validation, and result updates
# ---------------------------------------------------------------------------

def absolute_path_string(value: str | Path) -> str:
    """Return an absolute path string without requiring the path to exist."""
    return str(Path(value).expanduser().resolve())


def build_pairwise_prompt(
    *,
    template_path: Path,
    task_id: str,
    task_text: str,
    episodic_path_1: str,
    episodic_path_2: str,
    pairwise_eval_result_path: str,
) -> str:
    """Format the standalone, condition-blind pairwise judge prompt."""
    template = template_path.read_text(encoding="utf-8")
    return template.format(
        task_id=task_id,
        task_text=task_text,
        episodic_path_1=episodic_path_1,
        episodic_path_2=episodic_path_2,
        pairwise_eval_result_path=pairwise_eval_result_path,
    )


def build_pairwise_command(
    *,
    prompt: str,
    judge_model_config: dict,
    judge_settings_path: Optional[Path],
    max_budget_usd: Optional[float],
    skip_permissions: bool,
) -> list[str]:
    """Build the non-interactive Claude Code judge command."""
    command = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--no-session-persistence",
    ]
    model_flag = judge_model_config.get("claude_model_flag")
    if model_flag:
        command += ["--model", str(model_flag)]
    if judge_settings_path is not None:
        command += ["--settings", str(judge_settings_path)]
    if max_budget_usd is not None:
        command += ["--max-budget-usd", str(max_budget_usd)]
    if skip_permissions:
        command += [
            "--permission-mode",
            "bypassPermissions",
            "--dangerously-skip-permissions",
        ]
    return command


def validate_pairwise_result(
    result: object,
    *,
    task_id: str,
    task_text: str,
    episodic_path_1: str,
    episodic_path_2: str,
) -> dict:
    """Validate and return a judge result, or raise ``ValueError``.

    Exact input echoing prevents a stale or misdirected result file from being
    assigned to the current pair.  ``bool`` is deliberately rejected as a winner
    even though it is a subclass of ``int`` in Python.
    """
    if not isinstance(result, dict):
        raise ValueError("top-level JSON value must be an object")

    expected_values = {
        "task_id": task_id,
        "task_text": task_text,
        "episodic_path_1": episodic_path_1,
        "episodic_path_2": episodic_path_2,
    }
    for field, expected in expected_values.items():
        if field not in result:
            raise ValueError(f"missing required field '{field}'")
        if field != "task_text" and result[field] != expected:
            # we don't need task text to be exact, but it's nice to have it
            raise ValueError(f"field '{field}' does not match the supplied value")

    winner = result.get("winner")
    if isinstance(winner, str):
        winner = winner.strip()
        if winner in {"1", "2"}:
            winner = int(winner)
    if isinstance(winner, bool) or not isinstance(winner, int) or winner not in (1, 2):
        raise ValueError("field 'winner' must be 1 or 2 (integer or numeric string)")
    # Downstream code and the persisted result use one canonical representation,
    # regardless of whether the judge wrote 1 or "1".
    result["winner"] = winner

    reasoning = result.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise ValueError("field 'reasoning' must be a non-empty string")

    return result


def read_valid_pairwise_result(
    result_path: Path,
    *,
    task_id: str,
    task_text: str,
    episodic_path_1: str,
    episodic_path_2: str,
) -> dict:
    """Read and validate a result file written by the judge."""
    if not result_path.is_file():
        raise ValueError(f"judge did not write result file {result_path}")
    try:
        parsed = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"result file is not valid JSON: {exc}") from exc
    return validate_pairwise_result(
        parsed,
        task_id=task_id,
        task_text=task_text,
        episodic_path_1=episodic_path_1,
        episodic_path_2=episodic_path_2,
    )


def save_successful_comparison(
    *,
    result_path: Path,
    result: dict,
    record_1: dict,
    condition_1: str,
    record_2: dict,
    condition_2: str,
) -> None:
    """Enrich the judge result and update the two in-memory log records."""
    winner = result["winner"]
    result["condition_1"] = condition_1
    result["condition_2"] = condition_2
    _atomic_write_text(result_path, json.dumps(result, indent=2) + "\n")

    result_path_str = str(result_path)
    record_1["winner"] = winner == 1
    record_2["winner"] = winner == 2
    record_1["pairwise_eval_result_path"] = result_path_str
    record_2["pairwise_eval_result_path"] = result_path_str


def pairwise_result_path(
    results_dir: Path,
    condition_a: str,
    condition_b: str,
    model: str,
    task_id: str,
) -> Path:
    """Build the specified pairwise result filename and return it absolutely."""
    for label, value in (
        ("condition A", condition_a),
        ("condition B", condition_b),
        ("model", model),
        ("task ID", task_id),
    ):
        if (
            not value
            or "/" in value
            or "\\" in value
            or Path(value).name != value
            or value in {".", ".."}
        ):
            raise ValueError(f"{label} is not safe for a result filename: {value!r}")
    return (
        results_dir
        / f"{condition_a}_{condition_b}_{model}_{task_id}.json"
    ).expanduser().resolve()


def run_one_comparison(
    *,
    comparison: Comparison,
    condition_a: str,
    condition_b: str,
    results_dir: Path,
    model: str,
    template_path: Path,
    rng: random.Random,
    judge_worktree_path: Path,
    judge_model_config: dict,
    judge_settings_path: Optional[Path],
    max_budget_usd: Optional[float],
    skip_permissions: bool,
) -> tuple[Path, dict, dict, int]:
    """Invoke the judge once and return the validated result and ordered records."""
    task_id = str(comparison.task["id"])
    task_text = str(comparison.task["task"])
    (record_1, condition_1), (record_2, condition_2) = randomize_comparison(
        comparison, condition_a, condition_b, rng
    )
    episodic_path_1 = absolute_path_string(record_1["episodic_path"])
    episodic_path_2 = absolute_path_string(record_2["episodic_path"])
    result_path = pairwise_result_path(
        results_dir, condition_a, condition_b, model, task_id
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)

    # Never accept an artifact from an earlier failed attempt as this call's output.
    if result_path.exists():
        if not result_path.is_file():
            raise ValueError(f"result path exists and is not a file: {result_path}")
        result_path.unlink()

    prompt = build_pairwise_prompt(
        template_path=template_path,
        task_id=task_id,
        task_text=task_text,
        episodic_path_1=episodic_path_1,
        episodic_path_2=episodic_path_2,
        pairwise_eval_result_path=str(result_path),
    )
    command = build_pairwise_command(
        prompt=prompt,
        judge_model_config=judge_model_config,
        judge_settings_path=judge_settings_path,
        max_budget_usd=max_budget_usd,
        skip_permissions=skip_permissions,
    )
    process = subprocess.run(
        command,
        cwd=judge_worktree_path,
        env=re1.build_llm_subprocess_env(judge_model_config),
        capture_output=True,
        text=True,
        check=False,
    )

    result = read_valid_pairwise_result(
        result_path,
        task_id=task_id,
        task_text=task_text,
        episodic_path_1=episodic_path_1,
        episodic_path_2=episodic_path_2,
    )
    if process.returncode != 0:
        print(
            f"    [WARN] judge exited with status {process.returncode}, but wrote "
            "a valid result; accepting it",
            file=sys.stderr,
        )

    # Stash the randomized mapping for the caller without exposing it to the prompt.
    ordered = {
        "record_1": record_1,
        "condition_1": condition_1,
        "record_2": record_2,
        "condition_2": condition_2,
    }
    return result_path, result, ordered, process.returncode


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_conditions(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> tuple[str, str]:
    """Resolve either supported condition-pair CLI spelling."""
    explicit_pair = args.condition_a is not None or args.condition_b is not None
    if args.conditions and explicit_pair:
        parser.error("use either --conditions or --condition-a/--condition-b, not both")

    if args.conditions:
        values = [
            value.strip()
            for chunk in args.conditions
            for value in chunk.split(",")
            if value.strip()
        ]
    else:
        if args.condition_a is None or args.condition_b is None:
            parser.error(
                "supply exactly two conditions with --conditions, or provide both "
                "--condition-a and --condition-b"
            )
        values = [args.condition_a.strip(), args.condition_b.strip()]

    if len(values) != 2:
        parser.error(f"expected exactly two conditions, received {len(values)}")
    if values[0] == values[1]:
        parser.error("the two conditions must be different")
    return values[0], values[1]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--conditions",
        nargs="+",
        help="exactly two conditions, comma- or space-separated",
    )
    parser.add_argument("--condition-a", help="first condition (alternative spelling)")
    parser.add_argument("--condition-b", help="second condition (alternative spelling)")
    parser.add_argument(
        "--model", required=True, help="task model whose experiment records are compared"
    )
    parser.add_argument(
        "--judge-model",
        default="claude-opus-5",
        help="model key from --models-file used as the independent judge",
    )
    parser.add_argument(
        "--experiment-tasks", type=Path, default=DEFAULT_EXPERIMENT_TASKS
    )
    parser.add_argument("--benchmark", type=Path, default=re1.DEFAULT_BENCHMARK)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument(
        "--prompt-template", type=Path, default=DEFAULT_PROMPT_TEMPLATE
    )
    parser.add_argument("--models-file", type=Path, default=DEFAULT_MODELS_FILE)
    parser.add_argument(
        "--conditions-file", type=Path, default=DEFAULT_CONDITIONS_FILE
    )
    parser.add_argument(
        "--worktree-root", type=Path, default=re1.DEFAULT_WORKTREE_ROOT
    )
    parser.add_argument("--ref", default="HEAD", help="git ref for the judge worktree")
    parser.add_argument("--max-budget-usd", type=float, default=None)
    parser.add_argument(
        "--no-skip-permissions",
        action="store_true",
        help="disable bypass-permissions mode for the non-interactive judge",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="optional randomization seed"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list pending comparisons without creating a worktree or invoking Claude",
    )
    args = parser.parse_args(argv)

    condition_a, condition_b = parse_conditions(args, parser)
    if args.max_budget_usd is not None and args.max_budget_usd <= 0:
        parser.error("--max-budget-usd must be greater than zero")

    try:
        benchmark = re1.load_yaml(args.benchmark)
        benchmark_tasks = benchmark["tasks"]
    except (OSError, KeyError, TypeError) as exc:
        parser.error(f"could not load benchmark: {exc}")

    try:
        configured_conditions = re1.load_yaml(args.conditions_file)["conditions"]
        models = re1.load_yaml(args.models_file)["models"]
    except (OSError, KeyError, TypeError) as exc:
        parser.error(f"could not load harness configuration: {exc}")

    if args.judge_model not in models:
        parser.error(
            f"unknown judge model '{args.judge_model}'; choices: {sorted(models)}"
        )
    if not args.experiment_tasks.is_file():
        print(f"Experiment tasks log not found: {args.experiment_tasks}")
        return 0
    if not args.prompt_template.is_file():
        parser.error(f"prompt template not found: {args.prompt_template}")

    try:
        experiment_tasks = load_experiment_tasks(args.experiment_tasks)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    pending, completed, unavailable = collect_comparisons(
        benchmark_tasks,
        experiment_tasks,
        condition_a,
        condition_b,
        args.model,
    )
    print(
        f"{len(benchmark_tasks)} benchmark task(s): {len(pending)} to compare, "
        f"{completed} already compared, {unavailable} unavailable"
    )

    if not pending:
        return 0

    if args.dry_run:
        print("\n[dry-run] Pending comparisons:")
        for comparison in pending:
            print(
                f"  task_id={comparison.task['id']}  "
                f"{condition_a}={comparison.record_a.get('run_id', '?')}  "
                f"{condition_b}={comparison.record_b.get('run_id', '?')}"
            )
        print(
            f"\n[dry-run] Would create one disposable judge worktree and run "
            f"{len(pending)} Claude invocation(s) with judge model "
            f"'{args.judge_model}'."
        )
        return 0

    judge_condition = configured_conditions.get(re1.VERIFY_CONDITION_NAME)
    if judge_condition is None:
        parser.error(
            f"pairwise evaluation requires condition '{re1.VERIFY_CONDITION_NAME}' "
            f"in {args.conditions_file}"
        )

    rng = random.Random(args.seed)
    judge_model_config = models[args.judge_model]
    judge_worktree_path = (
        args.worktree_root / f"pairwise-eval-{uuid.uuid4().hex[:6]}"
    ).expanduser().resolve()
    success_count = 0
    failed_count = 0

    print(f"\nCreating judge worktree: {judge_worktree_path}")
    re1.create_worktree(judge_worktree_path, ref=args.ref)
    try:
        re1.memory_ops.apply_condition(judge_worktree_path, judge_condition)
        judge_settings_path = re1.write_worktree_settings(
            judge_worktree_path, judge_model_config
        )

        for comparison in pending:
            task_id = comparison.task["id"]
            print(f"\n  Comparing task_id={task_id}...")
            try:
                result_path, result, ordered, _returncode = run_one_comparison(
                    comparison=comparison,
                    condition_a=condition_a,
                    condition_b=condition_b,
                    results_dir=args.results_dir,
                    model=args.model,
                    template_path=args.prompt_template,
                    rng=rng,
                    judge_worktree_path=judge_worktree_path,
                    judge_model_config=judge_model_config,
                    judge_settings_path=judge_settings_path,
                    max_budget_usd=args.max_budget_usd,
                    skip_permissions=not args.no_skip_permissions,
                )
                ordered_records = (ordered["record_1"], ordered["record_2"])
                record_snapshots = [dict(record) for record in ordered_records]
                try:
                    save_successful_comparison(
                        result_path=result_path,
                        result=result,
                        record_1=ordered["record_1"],
                        condition_1=ordered["condition_1"],
                        record_2=ordered["record_2"],
                        condition_2=ordered["condition_2"],
                    )
                    write_experiment_tasks(args.experiment_tasks, experiment_tasks)
                    # Note: 
                    # var `experiment_tasks` elements ("record"s) are updated by save_successful_comparison
                    # since
                    #   record_a, record_b = matches_a[0], matches_b[0]
                    #   Comparison(..., record_a=record_a, record_b=record_b)
                except OSError:
                    # A later successful checkpoint must not accidentally persist
                    # an in-memory update whose own JSONL checkpoint failed.
                    for record, snapshot in zip(
                        ordered_records, record_snapshots, strict=True
                    ):
                        record.clear()
                        record.update(snapshot)
                    raise
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                print(
                    f"    [WARN] pairwise evaluation failed for task_id={task_id}: "
                    f"{exc}; leaving both experiment records unchanged",
                    file=sys.stderr,
                )
                failed_count += 1
                continue

            winning_condition = ordered[f"condition_{result['winner']}"]
            print(
                f"    winner={result['winner']} ({winning_condition}); "
                f"result={result_path}"
            )
            success_count += 1
    finally:
        re1.remove_worktree(judge_worktree_path)

    print(
        f"\nDone: {success_count} compared, {failed_count} failed, "
        f"{completed} previously completed, {unavailable} unavailable"
    )
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
