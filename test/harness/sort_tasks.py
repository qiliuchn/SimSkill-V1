"""Sort the experiment and optional worktree task logs.

Records are ordered by:

1. condition: ``full-ver``, ``sem-mem-ver``, ``infer-frame-only``, then
   ``vanilla-cc``;
2. model name, alphabetically;
3. task ID, in the order in ``test/benchmark_tasks.yaml``.

The main ``test/experiment_tasks.jsonl`` log is always considered.  Passing a
worktree name also sorts that worktree's ``test/worktree_tasks.jsonl``::

    python test/harness/sort_tasks.py
    python test/harness/sort_tasks.py \\
        --worktree infer-frame-only_deepseek-v4-pro

This script never removes task records or changes their contents.  If an input
contains the same (condition, model, task ID, repeat) more than once, it prints
a warning to stdout and leaves that entire file untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiment import DEFAULT_BENCHMARK, DEFAULT_WORKTREE_ROOT, REPO_ROOT


EXPERIMENT_TASKS_PATH = REPO_ROOT / "test" / "experiment_tasks.jsonl"
CONDITION_ORDER = (
    "full-ver",
    "sem-mem-ver",
    "infer-frame-only",
    "vanilla-cc",
)
REQUIRED_FIELDS = ("task_condition", "task_model", "task_id")
DUPLICATE_KEY_FIELDS = (*REQUIRED_FIELDS, "task_repeat")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSON objects from *path*, with useful errors for invalid records."""
    print(f"[read] {path}")
    records: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
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

            missing = [field for field in REQUIRED_FIELDS if field not in record]
            if missing:
                raise ValueError(
                    f"invalid record in {path} at line {line_number}: missing "
                    f"required field(s): {', '.join(missing)}"
                )
            records.append(record)

    return records


def load_task_order(path: Path) -> dict[str, int]:
    """Return a task-ID-to-position map from the benchmark YAML file."""
    print(f"[read] {path}")
    with path.open("r", encoding="utf-8") as handle:
        benchmark = yaml.safe_load(handle)

    if not isinstance(benchmark, dict) or not isinstance(benchmark.get("tasks"), list):
        raise ValueError(f"invalid benchmark in {path}: expected a 'tasks' list")

    task_ids: list[str] = []
    for position, task in enumerate(benchmark["tasks"], start=1):
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            raise ValueError(
                f"invalid benchmark task in {path} at position {position}: "
                "expected an object with a string 'id'"
            )
        task_ids.append(task["id"])

    duplicate_ids = [
        task_id for task_id, count in Counter(task_ids).items() if count > 1
    ]
    if duplicate_ids:
        raise ValueError(
            f"invalid benchmark in {path}: duplicate task ID(s): "
            + ", ".join(duplicate_ids)
        )

    return {task_id: position for position, task_id in enumerate(task_ids)}


def duplicate_keys(records: Iterable[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Return repeated task identities, preserving first-appearance order."""
    keys = [
        tuple(record.get(field) for field in DUPLICATE_KEY_FIELDS)
        for record in records
    ]
    counts = Counter(keys)
    return list(dict.fromkeys(key for key in keys if counts[key] > 1))


def _text_sort_key(value: Any) -> tuple[str, str]:
    """Sort textual record fields case-insensitively with a deterministic tie-break."""
    text = str(value)
    return text.casefold(), text


def record_sort_key(
    record: dict[str, Any], task_order: dict[str, int]
) -> tuple[Any, ...]:
    """Build the requested condition/model/benchmark-order key for one record."""
    condition = str(record["task_condition"])
    task_id = str(record["task_id"])

    try:
        condition_position = CONDITION_ORDER.index(condition)
        condition_key: tuple[Any, ...] = (0, condition_position, "", "")
    except ValueError:
        # Preserve records from future conditions and keep their ordering deterministic.
        condition_key = (1, len(CONDITION_ORDER), *_text_sort_key(condition))

    if task_id in task_order:
        task_key: tuple[Any, ...] = (0, task_order[task_id], "", "")
    else:
        # Preserve records from another benchmark version after all known tasks.
        task_key = (1, len(task_order), *_text_sort_key(task_id))

    return condition_key + _text_sort_key(record["task_model"]) + task_key


def save_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Atomically rewrite *path* with one unchanged JSON object per line."""
    text = "".join(json.dumps(record) + "\n" for record in records)

    temporary_path: Path | None = None
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
            temporary_path = Path(handle.name)

        temporary_path.chmod(path.stat().st_mode)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def sort_task_file(path: Path, task_order: dict[str, int]) -> bool:
    """Sort one task log, returning ``False`` when duplicates cause a skip."""
    records = load_jsonl(path)
    duplicates = duplicate_keys(records)
    if duplicates:
        detail = ", ".join(
            "(" + ", ".join(repr(value) for value in key) + ")"
            for key in duplicates
        )
        print(
            f"[warning] {path}: duplicate task key(s) {detail}; "
            "leaving file unchanged"
        )
        return False

    sorted_records = sorted(
        records, key=lambda record: record_sort_key(record, task_order)
    )
    save_jsonl(path, sorted_records)
    print(f"[sort] {path}: sorted {len(records)} record(s)")
    return True


def worktree_tasks_path(worktree: str) -> Path:
    """Resolve a worktree name without allowing arbitrary path traversal."""
    worktree_name = Path(worktree)
    if worktree_name.name != worktree or worktree in {".", ".."}:
        raise ValueError(f"worktree must be a name, not a path: {worktree!r}")
    return DEFAULT_WORKTREE_ROOT / worktree_name / "test" / "worktree_tasks.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--worktree",
        metavar="WORKTREE",
        help=(
            "worktree name under DEFAULT_WORKTREE_ROOT whose "
            "test/worktree_tasks.jsonl should also be sorted"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    task_order = load_task_order(DEFAULT_BENCHMARK)
    paths = [EXPERIMENT_TASKS_PATH]
    if args.worktree:
        paths.append(worktree_tasks_path(args.worktree))

    for path in paths:
        sort_task_file(path, task_order)


if __name__ == "__main__":
    main()
