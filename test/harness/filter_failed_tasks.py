"""Remove failed task records from experiment JSONL logs.

A task record is considered failed when it does not contain a non-empty
``episodic_path``.  The main experiment log is always filtered.  Worktree logs
can also be filtered by passing one or more worktree names::

    python test/harness/filter_failed_tasks.py
    python test/harness/filter_failed_tasks.py \
        --worktrees infer-frame-only_deepseek-v4-pro full-ver_deepseek-v4-pro
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiment import DEFAULT_WORKTREE_ROOT, REPO_ROOT


EXPERIMENT_TASKS_PATH = REPO_ROOT / "test" / "experiment_tasks.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    """Read JSON objects from *path*, with useful errors for invalid records."""
    print(f"\n[read] {path}")
    records: list[dict] = []

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
            records.append(record)

    return records


def save_jsonl(path: Path, records: list[dict]) -> None:
    """Atomically rewrite *path* with one JSON object per line."""
    print(f"\n[save] {len(records)} record(s) to {path}")
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


def filter_failed_tasks(path: Path) -> tuple[int, int]:
    """Remove records without a valid episodic path and return (kept, removed)."""
    records = load_jsonl(path)
    filtered_records = [record for record in records if record.get("episodic_path")]
    removed_count = len(records) - len(filtered_records)

    print(
        f"\n[filter] {path}: removed {removed_count} record(s) without a valid "
        f"episodic_path; kept {len(filtered_records)}"
    )
    save_jsonl(path, filtered_records)
    return len(filtered_records), removed_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--worktrees",
        nargs="+",
        default=[],
        metavar="WORKTREE",
        help=(
            "worktree name(s) under DEFAULT_WORKTREE_ROOT whose "
            "test/worktree_tasks.jsonl files should also be filtered"
        ),
    )
    # NOTE: argparse.ArgumentParser enables unambiguous long-option abbreviations by default. 
    # Therefore, --worktree is treated as a prefix of --worktrees. Even --workt currently works:
    # --worktree full-ver_glm-5.2
    # --workt full-ver_glm-5.2
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = [EXPERIMENT_TASKS_PATH]

    for worktree in args.worktrees:
        worktree_name = Path(worktree)
        if worktree_name.name != worktree or worktree in {".", ".."}:
            raise ValueError(f"worktree must be a name, not a path: {worktree!r}")
        paths.append(
            DEFAULT_WORKTREE_ROOT
            / worktree_name
            / "test"
            / "worktree_tasks.jsonl"
        )

    for path in paths:
        filter_failed_tasks(path)


if __name__ == "__main__":
    main()
