"""Assign pointwise completion scores to experiment-task records.

Each pending record in an experiment-tasks JSONL log is evaluated independently
against the original benchmark task.  The judge inspects the record's episodic
artifacts and writes a structured result containing a score in the inclusive
range ``[0, 1]``.  A score of 1 means the task was completed perfectly, 0 means
complete failure, and intermediate values represent the fraction of the task's
weighted requirements that were actually completed.

The judge runs in one disposable verification worktree, reused for the batch, so
bypass-permissions mode never runs from the user's main checkout.  After each
successful judgment, this script adds ``score`` and ``score_result_path`` to the
matching JSONL object and atomically checkpoints the whole log.  Invalid judge
output leaves that record unchanged, making interrupted or partially failed runs
safe to resume.  A failed scoring attempt prints the failing stage, exception,
result-artifact status, judge exit code, and captured stdout/stderr to stderr.

Examples:

    # Score every record that does not already have a valid score.
    python test/harness/score.py --judge-model claude-opus-5

    # Score a specific experiment log with another configured judge model.
    python test/harness/score.py --experiment-tasks /path/to/experiment_tasks.jsonl --judge-model deepseek-v4-pro

    # Restrict scoring to selected experiment conditions and task models.
    python test/harness/score.py --conditions full-ver,vanilla-cc --models claude-haiku-4-5

    # Inspect the pending jobs without creating a worktree or invoking a judge.
    python test/harness/score.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_experiment as re1


DEFAULT_EXPERIMENT_TASKS = re1.REPO_ROOT / "test" / "experiment_tasks.jsonl"
DEFAULT_RESULTS_DIR = re1.DEFAULT_RESULTS_DIR / "score"
DEFAULT_PROMPT_TEMPLATE = (
    re1.REPO_ROOT / "test" / "harness" / "score_prompt_template.txt"
)
DEFAULT_MODELS_FILE = re1.REPO_ROOT / "test" / "harness" / "models.yaml"
DEFAULT_CONDITIONS_FILE = re1.REPO_ROOT / "test" / "harness" / "conditions.yaml"
DIAGNOSTIC_TEXT_LIMIT = 8_000


@dataclass(frozen=True)
class ScoringJob:
    """A benchmark task and the experiment record to score."""

    task: dict
    record: dict
    run_id: str
    task_id: str
    episodic_path: str


class ScoringAttemptError(Exception):
    """Expected per-record failure plus context captured from the judge attempt."""

    def __init__(
        self,
        *,
        stage: str,
        cause: Exception,
        result_path: Optional[Path] = None,
        process: Optional[subprocess.CompletedProcess] = None,
    ) -> None:
        self.stage = stage
        self.cause = cause
        self.result_path = result_path
        self.returncode = None if process is None else process.returncode
        self.stdout = None if process is None else process.stdout
        self.stderr = None if process is None else process.stderr
        # Some subprocess exceptions embed the full command in ``str(exc)``;
        # that command contains the scoring prompt, so keep it out of this
        # wrapper's own message and render only safe details below.
        super().__init__(f"{stage}: {type(cause).__name__}")


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
    """Load a JSONL experiment log and identify malformed input by line."""
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
    """Atomically persist every JSONL record, including filtered/skipped ones."""
    text = "".join(json.dumps(record, default=str) + "\n" for record in records)
    _atomic_write_text(path, text)


# ---------------------------------------------------------------------------
# Job selection
# ---------------------------------------------------------------------------


def _canonical_numeric_score(value: object, *, allow_string: bool) -> float:
    """Return *value* as a finite score in ``[0, 1]`` or raise ``ValueError``."""
    if isinstance(value, bool):
        raise ValueError("score must be a number, not a boolean")

    try:
        if isinstance(value, (int, float)):
            score = float(value)
        elif allow_string and isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("score must not be an empty string")
            score = float(value)
        else:
            raise ValueError("score must be numeric")
    except (OverflowError, ValueError) as exc:
        raise ValueError("score must be numeric") from exc

    if not math.isfinite(score):
        raise ValueError("score must be finite")
    if not 0.0 <= score <= 1.0:
        raise ValueError("score must be between 0 and 1 inclusive")
    return score


def has_valid_score(record: dict) -> bool:
    """Return whether *record* already contains a canonical JSON numeric score."""
    if "score" not in record or record["score"] is None:
        return False
    try:
        _canonical_numeric_score(record["score"], allow_string=False)
    except ValueError:
        return False
    return True


def absolute_path_string(value: str | Path) -> str:
    """Return an absolute path string without requiring the path to exist."""
    return str(Path(value).expanduser().resolve())


def record_episodic_path(record: dict) -> str:
    """Resolve an episodic path, falling back to the referenced result JSON."""
    value = record.get("episodic_path")
    if not value:
        result_path_value = record.get("result_path")
        if isinstance(result_path_value, str) and result_path_value.strip():
            result_path = Path(result_path_value).expanduser()
            if result_path.is_file():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    result = None
                if isinstance(result, dict):
                    value = result.get("episodic_path")
    if not value:
        return ""
    if not isinstance(value, (str, Path)):
        raise ValueError("episodic_path must be a path string")
    if isinstance(value, str) and not value.strip():
        return ""
    return absolute_path_string(value)


def duplicate_run_ids(records: Sequence[dict]) -> set[str]:
    """Return non-empty run IDs that occur more than once."""
    run_ids = [
        str(record["run_id"])
        for record in records
        if record.get("run_id") is not None and str(record["run_id"]).strip()
    ]
    return {run_id for run_id, count in Counter(run_ids).items() if count > 1}


def collect_scoring_jobs(
    benchmark_tasks: Sequence[dict],
    experiment_tasks: Sequence[dict],
    *,
    conflicting_run_ids: Optional[set[str]] = None,
) -> tuple[list[ScoringJob], int, int]:
    """Collect pending scoring jobs in experiment-log order.

    Returns ``(pending, already_scored_count, unavailable_count)``.  Missing
    episodic paths remain scoreable: absence of inspectable solution evidence is
    itself evidence the judge must account for, normally with a score of zero.
    """
    task_by_id: dict[str, dict] = {}
    for task in benchmark_tasks:
        if not isinstance(task, dict) or task.get("id") is None:
            continue
        task_by_id[str(task["id"])] = task

    pending: list[ScoringJob] = []
    completed = 0
    unavailable = 0
    conflicts = duplicate_run_ids(experiment_tasks)
    if conflicting_run_ids:
        conflicts.update(conflicting_run_ids)

    for record in experiment_tasks:
        if has_valid_score(record):
            completed += 1
            continue
        if record.get("score") is not None:
            print(
                f"[WARN] run_id={record.get('run_id', '?')}: existing score "
                f"{record.get('score')!r} is invalid; rescoring",
                file=sys.stderr,
            )

        raw_task_id = record.get("task_id")
        task_id = "" if raw_task_id is None else str(raw_task_id)
        task = task_by_id.get(task_id)
        if task is None or not isinstance(task.get("task"), str):
            print(
                f"[WARN] run_id={record.get('run_id', '?')}: task_id "
                f"{task_id or '<missing>'!r} is unavailable in the benchmark; "
                "skipping",
                file=sys.stderr,
            )
            unavailable += 1
            continue

        raw_run_id = record.get("run_id")
        if raw_run_id is None or not str(raw_run_id).strip():
            print(
                f"[WARN] task_id={task_id}: run_id is missing; skipping",
                file=sys.stderr,
            )
            unavailable += 1
            continue
        run_id = str(raw_run_id)
        if run_id in conflicts:
            print(
                f"[WARN] task_id={task_id}: duplicate run_id={run_id!r} would "
                "reuse a scoring artifact path; skipping",
                file=sys.stderr,
            )
            unavailable += 1
            continue
        try:
            validate_filename_component(run_id, "run ID")
        except ValueError as exc:
            print(f"[WARN] task_id={task_id}: {exc}; skipping", file=sys.stderr)
            unavailable += 1
            continue

        try:
            episodic_path = record_episodic_path(record)
        except (OSError, TypeError, ValueError) as exc:
            print(
                f"[WARN] run_id={run_id}: invalid episodic path: {exc}; skipping",
                file=sys.stderr,
            )
            unavailable += 1
            continue

        pending.append(
            ScoringJob(
                task=task,
                record=record,
                run_id=run_id,
                task_id=task_id,
                episodic_path=episodic_path,
            )
        )

    return pending, completed, unavailable


def parse_csv_filter(value: Optional[str]) -> Optional[set[str]]:
    """Parse a comma-separated CLI filter, or return ``None`` for no filter."""
    if value is None:
        return None
    return {part.strip() for part in value.split(",") if part.strip()}


def filter_experiment_tasks(
    records: Sequence[dict],
    *,
    conditions: Optional[set[str]],
    models: Optional[set[str]],
) -> list[dict]:
    """Return references to records matching the optional CLI filters."""
    return [
        record
        for record in records
        if (conditions is None or record.get("task_condition") in conditions)
        and (models is None or record.get("task_model") in models)
    ]


# ---------------------------------------------------------------------------
# Prompt, command, validation, and updates
# ---------------------------------------------------------------------------


def build_score_prompt(
    *,
    template_path: Path,
    run_id: str,
    task_id: str,
    task_text: str,
    episodic_path: str,
    score_result_path: str,
) -> str:
    """Format the standalone pointwise-scoring prompt."""
    template = template_path.read_text(encoding="utf-8")
    values = {
        "run_id": run_id,
        "task_id": task_id,
        "task_text": task_text,
        "episodic_path": episodic_path,
        "score_result_path": score_result_path,
    }
    try:
        return template.format(
            **values,
            **{
                f"{name}_json": json.dumps(value, ensure_ascii=False)
                for name, value in values.items()
            },
        )
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"invalid score prompt template: {exc}") from exc


def build_score_command(
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


def validate_score_result(
    result: object,
    *,
    run_id: str,
    task_id: str,
    task_text: str,
    episodic_path: str,
) -> dict:
    """Validate and canonicalize a judge-written scoring result."""
    if not isinstance(result, dict):
        raise ValueError("top-level JSON value must be an object")

    expected_values = {
        "run_id": run_id,
        "task_id": task_id,
        "episodic_path": episodic_path,
    }
    for field, expected in expected_values.items():
        if field not in result:
            raise ValueError(f"missing required field '{field}'")
        if result[field] != expected:
            raise ValueError(f"field '{field}' does not match the supplied value")

    #if "task_text" not in result:
    #    raise ValueError("missing required field 'task_text'")
    #if result["task_text"] != task_text:
    #    raise ValueError("field 'task_text' does not match the supplied value")

    result["score"] = _canonical_numeric_score(result.get("score"), allow_string=True)

    reasoning = result.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise ValueError("field 'reasoning' must be a non-empty string")

    return result


def read_valid_score_result(
    result_path: Path,
    *,
    run_id: str,
    task_id: str,
    task_text: str,
    episodic_path: str,
) -> dict:
    """Read and validate a result file written by the scoring judge."""
    if not result_path.is_file():
        raise ValueError(f"judge did not write result file {result_path}")
    try:
        parsed = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"result file is not valid JSON: {exc}") from exc
    return validate_score_result(
        parsed,
        run_id=run_id,
        task_id=task_id,
        task_text=task_text,
        episodic_path=episodic_path,
    )


def validate_filename_component(value: str, label: str) -> None:
    """Reject values that could escape or ambiguously name an artifact file."""
    if (
        not value
        or "/" in value
        or "\\" in value
        or Path(value).name != value
        or value in {".", ".."}
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError(f"{label} is not safe for a result filename: {value!r}")


def score_result_path(results_dir: Path, run_id: str) -> Path:
    """Return the absolute, repeat-safe result artifact path for *run_id*."""
    validate_filename_component(run_id, "run ID")
    return (results_dir / f"{run_id}.json").expanduser().resolve()


def save_successful_score(
    *,
    result_path: Path,
    result: dict,
    record: dict,
    judge_model: str,
) -> None:
    """Persist the canonical judge artifact and update one in-memory record."""
    result["judge_model"] = judge_model
    _atomic_write_text(result_path, json.dumps(result, indent=2) + "\n")
    record["score"] = result["score"]
    record["score_result_path"] = str(result_path)


def _bounded_diagnostic_text(value: object) -> str:
    """Return readable, bounded text with terminal control characters escaped."""
    if value is None:
        return "<not captured>"
    text = str(value)
    if not text:
        return "<empty>"
    text = "".join(
        character
        if character in {"\n", "\t"}
        or not unicodedata.category(character).startswith("C")
        else character.encode("unicode_escape").decode("ascii")
        for character in text
    )
    if len(text) <= DIAGNOSTIC_TEXT_LIMIT:
        return text

    half = DIAGNOSTIC_TEXT_LIMIT // 2
    omitted = len(text) - (half * 2)
    return (
        text[:half]
        + f"\n... <truncated {omitted} character(s)> ...\n"
        + text[-half:]
    )


def _print_diagnostic_block(label: str, value: object) -> None:
    """Print one possibly-multiline diagnostic value with stable indentation."""
    print(f"    {label}:", file=sys.stderr)
    for line in _bounded_diagnostic_text(value).splitlines():
        print(f"      {line}", file=sys.stderr)


def print_scoring_failure_diagnostics(
    *, job: ScoringJob, error: ScoringAttemptError
) -> None:
    """Print actionable context for one failed score without raising another error."""
    print(
        f"    [WARN] scoring failed for run_id={job.run_id}; "
        "leaving the experiment record unchanged",
        file=sys.stderr,
    )
    print(f"    stage: {error.stage}", file=sys.stderr)
    if isinstance(error.cause, subprocess.SubprocessError):
        # ``TimeoutExpired``/``CalledProcessError`` may stringify the full
        # command, including the entire prompt. The stage, exception type, and
        # captured process details are sufficient and safe to display.
        cause_detail = type(error.cause).__name__
    else:
        cause_detail = (
            f"{type(error.cause).__name__}: "
            f"{_bounded_diagnostic_text(error.cause)}"
        )
    print(f"    error: {cause_detail}", file=sys.stderr)

    if error.result_path is not None:
        print(f"    score result path: {error.result_path}", file=sys.stderr)
        try:
            if error.result_path.is_file():
                _print_diagnostic_block(
                    "score result contents",
                    error.result_path.read_text(encoding="utf-8", errors="replace"),
                )
            elif error.result_path.exists():
                print(
                    "    score result status: exists but is not a regular file",
                    file=sys.stderr,
                )
            else:
                print("    score result status: not written", file=sys.stderr)
        except OSError as exc:
            print(
                f"    score result status: could not inspect: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    if error.returncode is not None:
        print(f"    judge exit code: {error.returncode}", file=sys.stderr)
        _print_diagnostic_block("judge stdout", error.stdout)
        _print_diagnostic_block("judge stderr", error.stderr)


def run_one_scoring(
    *,
    job: ScoringJob,
    results_dir: Path,
    template_path: Path,
    judge_worktree_path: Path,
    judge_model_config: dict,
    judge_settings_path: Optional[Path],
    max_budget_usd: Optional[float],
    skip_permissions: bool,
) -> tuple[Path, dict, int]:
    """Invoke the judge once and return its validated pointwise result."""
    result_path: Optional[Path] = None
    process: Optional[subprocess.CompletedProcess] = None
    stage = "preparing score result path"
    try:
        result_path = score_result_path(results_dir, job.run_id)
        result_path.parent.mkdir(parents=True, exist_ok=True)

        # Never accept an artifact left by an earlier failed scoring attempt.
        stage = "removing stale score result"
        if result_path.exists():
            if not result_path.is_file():
                raise ValueError(
                    f"result path exists and is not a file: {result_path}"
                )
            result_path.unlink()

        stage = "building judge prompt"
        prompt = build_score_prompt(
            template_path=template_path,
            run_id=job.run_id,
            task_id=job.task_id,
            task_text=str(job.task["task"]),
            episodic_path=job.episodic_path,
            score_result_path=str(result_path),
        )
        command = build_score_command(
            prompt=prompt,
            judge_model_config=judge_model_config,
            judge_settings_path=judge_settings_path,
            max_budget_usd=max_budget_usd,
            skip_permissions=skip_permissions,
        )

        stage = "running judge subprocess"
        process = subprocess.run(
            command,
            cwd=judge_worktree_path,
            env=re1.build_llm_subprocess_env(judge_model_config),
            capture_output=True,
            text=True,
            check=False,
        )

        stage = "validating judge result"
        result = read_valid_score_result(
            result_path,
            run_id=job.run_id,
            task_id=job.task_id,
            task_text=str(job.task["task"]),
            episodic_path=job.episodic_path,
        )
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ScoringAttemptError(
            stage=stage,
            cause=exc,
            result_path=result_path,
            process=process,
        ) from exc

    if process.returncode != 0:
        print(
            f"    [WARN] judge exited with status {process.returncode}, but wrote "
            "a valid result; accepting it",
            file=sys.stderr,
        )
    return result_path, result, process.returncode


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--experiment-tasks", type=Path, default=DEFAULT_EXPERIMENT_TASKS
    )
    parser.add_argument(
        "--judge-model",
        default="claude-opus-5",
        help="model key from --models-file used as the independent scoring judge",
    )
    parser.add_argument(
        "--conditions",
        default=None,
        help="comma-separated experiment condition names to score (default: all)",
    )
    parser.add_argument(
        "--models",
        default=None,
        help="comma-separated task-model keys to score (default: all)",
    )
    parser.add_argument("--benchmark", type=Path, default=re1.DEFAULT_BENCHMARK)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--prompt-template", type=Path, default=DEFAULT_PROMPT_TEMPLATE)
    parser.add_argument("--models-file", type=Path, default=DEFAULT_MODELS_FILE)
    parser.add_argument("--conditions-file", type=Path, default=DEFAULT_CONDITIONS_FILE)
    parser.add_argument("--worktree-root", type=Path, default=re1.DEFAULT_WORKTREE_ROOT)
    parser.add_argument("--ref", default="HEAD", help="git ref for the judge worktree")
    parser.add_argument("--max-budget-usd", type=float, default=None)
    parser.add_argument(
        "--no-skip-permissions",
        action="store_true",
        help="disable bypass-permissions mode for the non-interactive judge",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list pending scoring jobs without creating a worktree or invoking Claude",
    )
    args = parser.parse_args(argv)

    if args.max_budget_usd is not None and (
        not math.isfinite(args.max_budget_usd) or args.max_budget_usd <= 0
    ):
        parser.error("--max-budget-usd must be a finite number greater than zero")

    # Load benchmark
    try:
        benchmark = re1.load_yaml(args.benchmark)
        benchmark_tasks = benchmark["tasks"]
        if not isinstance(benchmark_tasks, list):
            raise TypeError("'tasks' must be a list")
    except (OSError, KeyError, TypeError) as exc:
        parser.error(f"could not load benchmark: {exc}")

    # Load harness configuration
    try:
        configured_conditions = re1.load_yaml(args.conditions_file)["conditions"]
        configured_models = re1.load_yaml(args.models_file)["models"]
    except (OSError, KeyError, TypeError) as exc:
        parser.error(f"could not load harness configuration: {exc}")

    if args.judge_model not in configured_models:
        parser.error(
            f"unknown judge model '{args.judge_model}'; "
            f"choices: {sorted(configured_models)}"
        )
    if not args.experiment_tasks.is_file():
        print(f"Experiment tasks log not found: {args.experiment_tasks}")
        return 0
    if not args.prompt_template.is_file():
        parser.error(f"prompt template not found: {args.prompt_template}")

    try:
        all_experiment_tasks = load_experiment_tasks(args.experiment_tasks)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    # Filter experiment tasks
    selected_records = filter_experiment_tasks(
        all_experiment_tasks,
        conditions=parse_csv_filter(args.conditions),
        models=parse_csv_filter(args.models),
    )
    if not selected_records:
        if all_experiment_tasks:
            print("No tasks match the given --conditions / --models filters.")
        else:
            print(f"Experiment tasks log is empty: {args.experiment_tasks}")
        return 0

    # Collect scoring jobs
    pending, completed, unavailable = collect_scoring_jobs(
        benchmark_tasks,
        selected_records,
        conflicting_run_ids=duplicate_run_ids(all_experiment_tasks),
    )
    print(f"Model used for scoring: {args.judge_model}")
    print(
        f"{len(selected_records)} selected task(s): {len(pending)} to score, "
        f"{completed} already scored, {unavailable} unavailable"
    )

    if not pending:
        return 0

    if args.dry_run:
        print("\n[dry-run] Pending scoring jobs:")
        for job in pending:
            print(
                f"  run_id={job.run_id}  task_id={job.task_id}  "
                f"condition={job.record.get('task_condition', '?')}  "
                f"model={job.record.get('task_model', '?')}"
            )
            print(f"    episodic_path={job.episodic_path or '[MISSING]'}")
        print(
            f"\n[dry-run] Would create one disposable judge worktree and run "
            f"{len(pending)} Claude invocation(s) with judge model "
            f"'{args.judge_model}'."
        )
        print(
            "[dry-run] Judge model configuration: "
            f"{re1.redacted_model_config(configured_models[args.judge_model])}"
        )
        return 0

    # Create judge worktree
    # Use the verify condition
    judge_condition = configured_conditions.get(re1.VERIFY_CONDITION_NAME)
    if judge_condition is None:
        parser.error(
            f"scoring requires condition '{re1.VERIFY_CONDITION_NAME}' in "
            f"{args.conditions_file}"
        )

    # Load judge model configuration
    judge_model_config = configured_models[args.judge_model]
    judge_worktree_path = (
        (args.worktree_root / f"score-{uuid.uuid4().hex[:6]}").expanduser().resolve()
    )
    success_count = 0
    failed_count = 0

    # Create judge worktree
    print(f"\nCreating judge worktree: {judge_worktree_path}")
    re1.create_worktree(judge_worktree_path, ref=args.ref)
    try:
        re1.memory_ops.apply_condition(judge_worktree_path, judge_condition)
        judge_settings_path = re1.write_worktree_settings(
            judge_worktree_path, judge_model_config
        )

        # Run scoring jobs
        for job in pending:
            print(f"\n  Scoring run_id={job.run_id} (task_id={job.task_id})...")
            try:
                result_path, result, _returncode = run_one_scoring(
                    job=job,
                    results_dir=args.results_dir,
                    template_path=args.prompt_template,
                    judge_worktree_path=judge_worktree_path,
                    judge_model_config=judge_model_config,
                    judge_settings_path=judge_settings_path,
                    max_budget_usd=args.max_budget_usd,
                    skip_permissions=not args.no_skip_permissions,
                )
                record_snapshot = dict(job.record)
                try:
                    save_successful_score(
                        result_path=result_path,
                        result=result,
                        record=job.record,
                        judge_model=args.judge_model,
                    )
                except OSError as exc:
                    job.record.clear()
                    job.record.update(record_snapshot)
                    raise ScoringAttemptError(
                        stage="saving score result artifact",
                        cause=exc,
                        result_path=result_path,
                    ) from exc
                try:
                    write_experiment_tasks(args.experiment_tasks, all_experiment_tasks)
                except OSError as exc:
                    # Do not let a later checkpoint persist an in-memory update
                    # whose own JSONL checkpoint failed.
                    job.record.clear()
                    job.record.update(record_snapshot)
                    raise ScoringAttemptError(
                        stage="checkpointing experiment tasks log",
                        cause=exc,
                        result_path=result_path,
                    ) from exc
            except ScoringAttemptError as exc:
                print_scoring_failure_diagnostics(job=job, error=exc)
                failed_count += 1
                continue
            except (
                KeyError,
                OSError,
                ValueError,
                subprocess.SubprocessError,
            ) as exc:
                # Defensive fallback for orchestration failures outside
                # ``run_one_scoring``'s stage-aware wrapper.
                print_scoring_failure_diagnostics(
                    job=job,
                    error=ScoringAttemptError(
                        stage="processing scoring job",
                        cause=exc,
                    ),
                )
                failed_count += 1
                continue

            print(f"    score={result['score']:.6g}; result={result_path}")
            success_count += 1
    finally:
        re1.remove_worktree(judge_worktree_path)

    print(
        f"\nDone: {success_count} scored, {failed_count} failed, "
        f"{completed} previously scored, {unavailable} unavailable"
    )
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
