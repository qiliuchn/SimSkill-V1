"""
Standalone post-hoc verification script for SimSkill experiment results.

Reads the experiment-tasks JSONL log (written by ``run_experiment.py``), finds
records whose ``verified_success`` is null (or whose corresponding result JSON
is still unverified), and runs independent verification on each pending one via
the same ``run_verification()`` function that ``run_experiment.py`` uses.

After each attempt it updates the per-run result JSON, the matching entry in the
global experiment JSONL, and the same entry in that run's worktree-local
``test/worktree_tasks.jsonl``.  These records include the canonical paths to the
verifier result and raw logs.  JSONL files are replaced atomically after every
task so completed verification work survives an interrupted batch.

With ``--redo``, every record is verified again through a timestamped copy of
the experiment log and task result.  Its verification paths receive only the new
verifier's output.  The original log, artifacts, and worktree-local task records
are not changed.

Much simpler than the old worktree-discovery approach: the JSONL log records
every (task, repeat) actually executed, with explicit ``result_path`` pointers,
so there's no need to glob directories or guess at worktree names.


## Usage
    # Verify all unverified results from the default experiment-tasks log
    python test/harness/verify.py --verify-model claude-opus-5
    python test/harness/verify.py --verify-model deepseek-v4-pro

    # Point at a specific experiment-tasks log
    python test/harness/verify.py --verify-model claude-opus-5 --experiment-tasks /path/to/experiment_tasks.jsonl

    # Filter to specific conditions and/or models
    python test/harness/verify.py --verify-model claude-opus-5 --conditions full-ver --models claude-haiku-4-5

    # Dry-run to list what would be verified without spending anything
    python test/harness/verify.py --verify-model claude-opus-5 --dry-run

    # Re-verify every result using timestamped copies, preserving the originals
    python test/harness/verify.py --verify-model claude-opus-5 --redo
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_experiment as re1

DEFAULT_EXPERIMENT_TASKS = re1.REPO_ROOT / "test" / "experiment_tasks.jsonl"
REDO_ARTIFACT_FIELDS = (
    "result_path",
    "verify_result_path",
    "verify_stdout_path",
    "verify_stderr_path",
)


# ---------------------------------------------------------------------------
# Persistence and verdict helpers
# ---------------------------------------------------------------------------

def _atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace *path* with UTF-8 *text*.
    This function safely writes text to a file using an atomic replacement. Its main
    purpose is to avoid leaving path partially written or corrupted if something goes
    wrong during writing.

    Conceptually, instead of:
        path.write_text(text)

    It does:
        1. Write everything to a temporary file
        2. Finish/close the temporary file
        3. Replace the original file with the temporary file
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
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


def write_experiment_tasks(path: Path, experiment_tasks: list[dict]) -> None:
    """Persist every JSONL record without dropping filtered or skipped tasks.
    This function rewrites an entire JSONL file using the records in experiment_tasks.
    """
    text = "".join(json.dumps(item, default=str) + "\n" for item in experiment_tasks)
    _atomic_write_text(path, text)


def make_redo_suffix(verify_model: str, timestamp: Optional[datetime] = None) -> str:
    """Return a filename-safe ``<verify-model>_<timestamp>`` suffix."""
    safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "-", verify_model).strip("._-")
    if not safe_model:
        safe_model = "verify-model"
    timestamp_text = (timestamp or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    return f"{safe_model}_{timestamp_text}"


def path_with_redo_suffix(path: Path, run_id: str, redo_suffix: str) -> Path:
    """Insert *redo_suffix* after the run ID and before a path's extensions.

    path.with_name(new_name) returns a new Path with the same parent directory
    but a different filename.

    For example:
        path: /results/raw/sample_run.verify.stdout.log
        redo_suffix: "claude-opus-5_2026-07-21_18-35-42"
        run_id: "sample_run"
        return: /results/raw/sample_run_claude-opus-5_2026-07-21_18-35-42.verify.stdout.log
    """
    suffixed_run_id = f"{run_id}_{redo_suffix}"
    if run_id in path.name:
        name = path.name.replace(run_id, suffixed_run_id, 1)
    else:
        # fallback logic for when the filename does not contain run_id
        # Example:
        # path = Path("custom.verify.stdout.log")
        # Then path.suffixes is
        # [".verify", ".stdout", ".log"]
        # stem = "custom"
        #
        # return: "custom_claude-opus-5_2026-07-21_18-35-42.verify.stdout.log"
        extensions = "".join(path.suffixes)
        stem = path.name[:-len(extensions)] if extensions else path.name
        name = f"{stem}_{redo_suffix}{extensions}"
    return path.with_name(name)


def experiment_path_with_redo_suffix(path: Path, redo_suffix: str) -> Path:
    """Return the timestamped copy path for an experiment-tasks JSONL file."""
    return path.with_name(f"{path.stem}_{redo_suffix}{path.suffix}")


def prepare_redo_experiment(
    experiment_tasks_path: Path,
    experiment_tasks: list[dict],
    verify_model: str,
    timestamp: Optional[datetime] = None,
) -> tuple[Path, list[dict], str]:
    """Copy task results and assign fresh verification paths for ``--redo``.

    Create one suffix from ``verify_model`` and ``timestamp``, copy the experiment
    JSONL using that suffix, copy each task result, and assign suffixed paths for
    the new verifier result, stdout, and stderr.  Verification fields are cleared
    in the copied task records and copied result JSON files so the caller will
    verify every copied record again.  This function does not run the verifier.

    The input records, source experiment JSONL, and source artifacts are not
    modified.  Old verification output is deliberately not copied.  The source
    task result JSON is required.

    Args:
        experiment_tasks_path: Path to the source experiment-tasks JSONL file.
        experiment_tasks: Parsed records from the source experiment-tasks file.
        verify_model: Verification model name included in every copied filename.
        timestamp: Time included in the filename suffix.  Defaults to the current
            local time; callers may supply one so all names are deterministic.

    Returns:
        A tuple containing the copied experiment JSONL path, its rewritten task
        records, and the ``<verify_model>_<timestamp>`` filename suffix.

    Raises:
        FileNotFoundError: A task's source result JSON does not exist.
        FileExistsError: A destination experiment or artifact file already exists.
        ValueError: A record is invalid, a result is not valid JSON, or two records
            would produce the same destination path.
    """
    redo_suffix = make_redo_suffix(verify_model, timestamp)
    redo_experiment_path = experiment_path_with_redo_suffix(
        experiment_tasks_path, redo_suffix
    )
    if redo_experiment_path.exists():
        raise FileExistsError(
            f"redo experiment log already exists: {redo_experiment_path}"
        )

    plans: list[tuple[dict, dict, dict[str, Path], dict[str, Path]]] = []
    planned_targets: set[Path] = {redo_experiment_path}
    for item in experiment_tasks:
        run_id = item.get("run_id")
        if not run_id:
            raise ValueError("task record has no run_id")
        missing_fields = [field for field in REDO_ARTIFACT_FIELDS if not item.get(field)]
        if missing_fields:
            raise ValueError(
                f"run_id={run_id} is missing artifact paths: "
                f"{', '.join(missing_fields)}"
            )
        source_paths = {
            field: Path(item[field])
            for field in REDO_ARTIFACT_FIELDS
        }
        if not source_paths["result_path"].is_file():
            raise FileNotFoundError(
                f"result file not found for run_id={run_id}: "
                f"{source_paths['result_path']}"
            )
        try:
            source_result = json.loads(
                source_paths["result_path"].read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid result JSON at {source_paths['result_path']}: {exc}"
            ) from exc

        target_paths = {
            field: path_with_redo_suffix(source, run_id, redo_suffix)
            for field, source in source_paths.items()
        }
        for target in target_paths.values():
            if target in planned_targets:
                raise ValueError(f"duplicate redo output path: {target}")
            if target.exists():
                raise FileExistsError(f"redo artifact already exists: {target}")
            planned_targets.add(target)
        plans.append((item, source_result, source_paths, target_paths))

    # Start with a literal copy, then rewrite that copy with the new paths and
    # cleared verdicts after all four per-record paths have been prepared.
    redo_experiment_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(experiment_tasks_path, redo_experiment_path)

    redo_tasks: list[dict] = []
    for item, source_result, source_paths, target_paths in plans:
        redo_item = dict(item)
        for field in REDO_ARTIFACT_FIELDS:
            source = source_paths[field]
            target = target_paths[field]
            if field == "result_path":
                # Preserve the original task execution result.  Its verification
                # fields and artifact paths are rewritten below in the copy only.
                if not source.is_file():
                    raise FileNotFoundError(f"result file not found: {source}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            redo_item[field] = str(target)

        copied_result_path = target_paths["result_path"]
        copied_result = dict(source_result)

        # clear verification fields
        for field in (
            "verified_success",
            "verification_agreement",
            "verification_episodic_record_found",
            "verification_critique",
        ):
            copied_result[field] = None
        # Store the new verification artifact paths; this does not copy their content.
        for field in REDO_ARTIFACT_FIELDS[1:]:
            copied_result[field] = str(target_paths[field])
        _atomic_write_text(
            copied_result_path,
            json.dumps(copied_result, indent=2, default=str) + "\n",
        )

        redo_item["verified_success"] = None
        redo_item["verification_agreement"] = None
        if "verification_critique" in redo_item:
            redo_item["verification_critique"] = None
        redo_tasks.append(redo_item)

    # write the redo experiment tasks records to the JSONL file
    write_experiment_tasks(redo_experiment_path, redo_tasks)

    # Note: the returned redo-tasks are from the redo experiment tasks file, not the
    # source experiment tasks file.
    return redo_experiment_path, redo_tasks, redo_suffix


def needs_verification(task_item: dict, result: dict) -> bool:
    """Return whether a task needs verification or consistency repair.

    The experiment JSONL record is the queue, but the per-run result is also a
    downstream source of truth.  If either one lacks a verdict, verify the task and
    update both rather than leaving the two stores inconsistent.
    """
    return (
        task_item.get("verified_success") is None
        or result.get("verified_success") is None
    )


def update_result_with_verdict(
    result_path: Path, result: dict, verdict: dict,
    verify_result_path: Optional[str] = None,
    verify_stdout_path: Optional[str] = None,
    verify_stderr_path: Optional[str] = None,
) -> dict:
    """Merge *verdict* fields back into *result* and write it to disk in-place,
    matching the field layout that ``annotate_with_cost_time`` produces so every
    downstream consumer (``aggregate_results``, ``print_primary_comparisons``,
    …) picks up the verification data without any other file changing."""
    verified_success, verification_agreement, verify_warnings = (
        re1.resolve_verification_result(
            verdict, result.get("self_reported_success")
        )
    )
    result["verified_success"] = verified_success
    result["verification_agreement"] = verification_agreement
    result["verification_episodic_record_found"] = verdict.get("episodic_record_found")
    result["verification_critique"] = verdict.get("critique") or verdict.get("summary")

    # Persist the paths where verification artifacts were saved, so downstream
    # consumers know exactly where to find them.
    if verify_result_path:
        result["verify_result_path"] = verify_result_path
    if verify_stdout_path:
        result["verify_stdout_path"] = verify_stdout_path
    if verify_stderr_path:
        result["verify_stderr_path"] = verify_stderr_path

    # Merge any warnings the verifier produced
    stale_verification_warning_prefixes = (
        "verification skipped",
        "verification result",
        "non-boolean verified_success",
        "ignoring conflicting textual verdict",
        "verify skill did not write",
        "verify output at",
    )
    existing = [
        warning
        for warning in (result.get("warnings") or [])
        if not str(warning).startswith(stale_verification_warning_prefixes)
    ]
    for w in verify_warnings:
        if w not in existing:
            existing.append(w)
    result["warnings"] = existing

    _atomic_write_text(result_path, json.dumps(result, indent=2, default=str) + "\n")
    return {
        "verified_success": verified_success,
        "verification_agreement": verification_agreement,
        "verification_episodic_record_found": verdict.get("episodic_record_found"),
        "verification_critique": result["verification_critique"],
        "verification_warnings": verify_warnings,
        "verify_result_path": verify_result_path,
        "verify_stdout_path": verify_stdout_path,
        "verify_stderr_path": verify_stderr_path,
    }


def update_experiment_task(task_item: dict, verification_fields: dict) -> None:
    """Apply the post-hoc verification fields to one JSONL task record."""
    for key in (
        "verified_success",
        "verification_agreement",
        "verify_result_path",
        "verify_stdout_path",
        "verify_stderr_path",
    ):
        task_item[key] = verification_fields[key]


def update_worktree_task_file(
    task_item: dict, verification_fields: dict
) -> tuple[Path, int]:
    """Update the matching run in its worktree-local task JSONL.

    Returns the file path and number of matching records updated.  The caller can
    warn and continue when the original worktree or local task log is unavailable;
    post-hoc verification should still update the durable global result stores.
    """
    worktree_path_value = task_item.get("worktree_path")
    if not worktree_path_value:
        raise FileNotFoundError("task record has no worktree_path")

    worktree_tasks_path = Path(worktree_path_value) / "test" / "worktree_tasks.jsonl"
    if not worktree_tasks_path.is_file():
        raise FileNotFoundError(f"worktree task log not found: {worktree_tasks_path}")

    run_id = task_item.get("run_id")
    if not run_id:
        raise ValueError("task record has no run_id")

    worktree_tasks = []
    with worktree_tasks_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                worktree_tasks.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSON in {worktree_tasks_path} at line "
                    f"{line_number}: {exc}"
                ) from exc

    matches = 0
    for worktree_task in worktree_tasks:
        if worktree_task.get("run_id") == run_id:
            update_experiment_task(worktree_task, verification_fields)
            matches += 1

    if matches:
        write_experiment_tasks(worktree_tasks_path, worktree_tasks)
    return worktree_tasks_path, matches






# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--experiment-tasks", type=Path, default=DEFAULT_EXPERIMENT_TASKS,
        help="path to the experiment_tasks.jsonl log file "
             "(default: test/experiment_tasks.jsonl)",
    )
    parser.add_argument(
        "--verify-model",
        default="claude-opus-5",
        metavar="VERIFY_MODEL",
        help="model key from --models-file used for independent verification (default: claude-opus-5)",
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
        "--worktree-root", type=Path, default=re1.DEFAULT_WORKTREE_ROOT,
        help="directory where the disposable verify worktree is created",
    )
    parser.add_argument(
        "--benchmark", type=Path, default=re1.DEFAULT_BENCHMARK,
        help="path to benchmark_tasks.yaml (for resolving task_id → task text)",
    )
    parser.add_argument(
        "--conditions-file", type=Path,
        default=re1.HARNESS_DIR / "conditions.yaml",
        help="condition configuration used to prepare the verifier worktree",
    )
    parser.add_argument(
        "--models-file", type=Path,
        default=re1.HARNESS_DIR / "models.yaml",
        help="model configuration containing the --verify-model key",
    )
    parser.add_argument(
        "--max-budget-usd", type=float, default=None,
        help="per-call cost cap forwarded to claude -p",
    )
    parser.add_argument(
        "--no-skip-permissions", action="store_true",
        help="disable --dangerously-skip-permissions (only use in interactive runs)",
    )
    parser.add_argument(
        "--redo", action="store_true",
        help="re-verify every result using timestamped copies; preserve originals",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="list what would be verified without touching git or claude",
    )
    args = parser.parse_args()

    if args.redo and (args.conditions or args.models):
        parser.error(
            "--redo verifies every record and cannot be combined with "
            "--conditions or --models"
        )

    
    
    # ------------------------------------------------------------------
    # 1. Load benchmark to resolve task_id → task text
    # ------------------------------------------------------------------
    benchmark = re1.load_yaml(args.benchmark)
    task_by_id = {t["id"]: t for t in benchmark["tasks"]}  # get a dict of task_id: task pairs
    conditions = re1.load_yaml(args.conditions_file)["conditions"]
    models = re1.load_yaml(args.models_file)["models"]
    if args.verify_model not in models:
        parser.error(
            f"unknown verify model '{args.verify_model}' — choices: {sorted(models)}"
        )
    verify_model_config = models[args.verify_model]
    verify_condition = conditions.get(re1.VERIFY_CONDITION_NAME)
    if verify_condition is None:
        parser.error(
            f"verification requires condition '{re1.VERIFY_CONDITION_NAME}' in "
            f"{args.conditions_file}"
        )

    print(f"Model used for verification: {args.verify_model}")
    
    
    # ------------------------------------------------------------------
    # 2. Load the experiment-tasks JSONL log
    # ------------------------------------------------------------------
    experiment_tasks_path: Path = args.experiment_tasks
    if not experiment_tasks_path.exists():
        print(f"Experiment tasks log not found at {experiment_tasks_path} — nothing to do.")
        return

    all_experiment_tasks = []
    with experiment_tasks_path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if line:
                try:
                    all_experiment_tasks.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise SystemExit(
                        f"Invalid JSON in {experiment_tasks_path} at line "
                        f"{line_number}: {exc}"
                    ) from exc

    if not all_experiment_tasks:
        print(f"Experiment tasks log at {experiment_tasks_path} is empty — nothing to do.")
        return

    # -----------if redo verification, create a new experiment log with a redo suffix---------
    redo_suffix: Optional[str] = None
    if args.redo:
        missing_task_ids = sorted(
            {
                str(item.get("task_id") or "<missing>")
                for item in all_experiment_tasks
                if item.get("task_id") not in task_by_id
            }
        )
        if missing_task_ids:
            raise SystemExit(
                "Could not prepare --redo copies: task IDs are missing from the "
                f"benchmark: {', '.join(missing_task_ids)}"
            )

        redo_timestamp = datetime.now()
        redo_suffix = make_redo_suffix(args.verify_model, redo_timestamp)
        redo_experiment_path = experiment_path_with_redo_suffix(
            experiment_tasks_path, redo_suffix
        )
        if args.dry_run:
            print(
                f"[dry-run] Would copy the experiment log to: "
                f"{redo_experiment_path}"
            )
            print(
                f"[dry-run] Would copy each task result and assign three new "
                f"verification paths for {len(all_experiment_tasks)} record(s)."
            )
        else:
            try:
                experiment_tasks_path, all_experiment_tasks, redo_suffix = (
                    prepare_redo_experiment(
                        experiment_tasks_path,
                        all_experiment_tasks,
                        args.verify_model,
                        redo_timestamp,
                    )
                )
            except (FileExistsError, FileNotFoundError, ValueError, OSError) as exc:
                raise SystemExit(f"Could not prepare --redo copies: {exc}") from exc
            print(f"Redo experiment log: {experiment_tasks_path}")
            print(
                f"Copied each task result and assigned three new verification "
                f"paths for {len(all_experiment_tasks)} record(s); originals are "
                f"unchanged."
            )

    # Filter a list of references to the original dicts.  Updates are written using
    # all_experiment_tasks so records excluded by filters are never dropped.
    experiment_tasks = list(all_experiment_tasks)

    # ------------------------------------------------------------------
    # 3. Apply --conditions / --models filters
    # ------------------------------------------------------------------
    if args.conditions:
        wanted_conditions = set(c.strip() for c in args.conditions.split(","))
        experiment_tasks = [
            item for item in experiment_tasks
            if item.get("task_condition") in wanted_conditions
        ]

    if args.models:
        wanted_models = set(m.strip() for m in args.models.split(","))
        experiment_tasks = [
            item for item in experiment_tasks
            if item.get("task_model") in wanted_models
        ]

    if not experiment_tasks:
        print("No tasks match the given --conditions / --models filters.")
        return

    # ------------------------------------------------------------------
    # 4. Collect pending results (those needing verification)
    # ------------------------------------------------------------------
    pending: list[tuple[Path, dict, dict]] = []  # (result_path, result, task_item)
    # "item": experiment tasks item
    # "result": the json result file stored in the item
    unavailable_count = 0
    already_count = 0
    for item in experiment_tasks:
        result_path_value = item.get("result_path")
        if not result_path_value:
            print(
                f"[warn] result_path missing for run_id={item.get('run_id')}, skipping"
            )
            unavailable_count += 1
            continue
        result_path = Path(result_path_value)
        if not result_path.exists():
            print(f"[warn] result file not found, skipping: {result_path}")
            unavailable_count += 1
            continue
        try:
            result = json.loads(result_path.read_text())  # load the result file
        except json.JSONDecodeError:
            print(f"[warn] skipping unparseable result file: {result_path}")
            unavailable_count += 1
            continue
        if args.redo or needs_verification(item, result):
            pending.append((result_path, result, item))
        else:
            already_count += 1

    total = len(experiment_tasks)
    print(
        f"{total} task(s) in experiment log, "
        f"{len(pending)} to verify"
        + (f", {already_count} already verified" if already_count else "")
        + (f", {unavailable_count} unavailable" if unavailable_count else "")
        + (" (--redo)" if args.redo else "")
    )

    if not pending:
        if not args.redo and already_count:
            print("  Use --redo to verify every result again using timestamped copies.")
        return

    # ------------------------------------------------------------------
    # 5. Dry-run: print what would happen, then exit
    # ------------------------------------------------------------------
    if args.dry_run:
        print("\n[dry-run] Would verify the following results:")
        for result_path, result, item in pending:
            task_id = item.get("task_id", "?")
            wt = item.get("worktree_path")
            ep = result.get("episodic_path") or item.get("episodic_path")
            print(f"  {result_path.name}")
            print(f"    task_id={task_id}")
            print(f"    condition={item.get('task_condition')}")
            print(f"    model={item.get('task_model')}")
            print(
                f"    worktree={wt if wt and Path(wt).is_dir() else '[MISSING]'}"
            )
            worktree_tasks_path = (
                Path(wt) / "test" / "worktree_tasks.jsonl" if wt else None
            )
            print(
                "    worktree_tasks_jsonl="
                + (
                    str(worktree_tasks_path)
                    if worktree_tasks_path and worktree_tasks_path.is_file()
                    else "[MISSING]"
                )
            )
            print(f"    episodic_path={ep}")
            if result.get("verified_success") is not None:
                reason = (
                    "--redo"
                    if args.redo
                    else "the experiment JSONL record is missing its verdict"
                )
                print(f"    [result is already verified — would re-verify because {reason}]")
        print(
            f"\n[dry-run] Would create one verify worktree, run "
            f"{len(pending)} claude -p invocation(s), then tear it down."
        )
        print(
            f"[dry-run] The verify worktree would apply filesystem removals from "
            f"condition {re1.VERIFY_CONDITION_NAME}."
        )
        print(
            f"[dry-run] Verification model: {args.verify_model} -> "
            f"{re1.redacted_model_config(verify_model_config)}"
        )
        if args.redo:
            print("[dry-run] Original experiment log and artifacts would remain unchanged.")
        return

    # ------------------------------------------------------------------
    # 6. Create a single disposable verify worktree, reused across all runs
    # ------------------------------------------------------------------
    verify_worktree_name = f"verify-{uuid.uuid4().hex[:6]}"
    verify_worktree_path = args.worktree_root / verify_worktree_name

    print(f"\nCreating verify worktree: {verify_worktree_path}")
    re1.create_worktree(verify_worktree_path, ref="HEAD")

    try:
        # Keep post-hoc verification isolated from the framework and memories under
        # evaluation.  The miscellaneous /verify skill is not removed by vanilla-cc.
        re1.memory_ops.apply_condition(verify_worktree_path, verify_condition)
        verify_settings_path = re1.write_worktree_settings(
            verify_worktree_path, verify_model_config
        )

        skip_permissions = not args.no_skip_permissions
        verified_count = 0
        inconclusive_count = 0
        skipped_count = 0
        error_count = 0
        worktree_log_updated_count = 0
        worktree_log_unavailable_count = 0

        for result_path, result, item in pending:
            task_id = item.get("task_id", "")
            task = task_by_id.get(task_id)

            if task is None:
                print(
                    f"\n  [SKIP] {result_path.name}: task_id '{task_id}' not in "
                    f"benchmark — skipping"
                )
                skipped_count += 1
                continue

            run_id = item.get("run_id") or result.get("run_id")
            if not run_id:
                print(
                    f"\n  [SKIP] {result_path.name}: run_id is missing — skipping"
                )
                skipped_count += 1
                continue

            print(
                f"\n  Verifying {result_path.name}  "
                f"(task: {task_id}, condition: {item.get('task_condition')}, "
                f"model: {item.get('task_model')})..."
            )

            verification_run_id = (
                f"{run_id}_{redo_suffix}" if args.redo else run_id
            )
            verify_result_path = Path(item["verify_result_path"])
            verify_stdout_path = Path(item["verify_stdout_path"])
            verify_stderr_path = Path(item["verify_stderr_path"])
            verification_paths = (
                verify_result_path,
                verify_stdout_path,
                verify_stderr_path,
            )

            for artifact_path in verification_paths:
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                # A new attempt must not accidentally consume an artifact left by a
                # previous attempt if the verifier fails before writing new output.
                if artifact_path.exists():
                    artifact_path.unlink()

            verify_result_path_str = str(verify_result_path)
            verify_stdout_path_str = str(verify_stdout_path)
            verify_stderr_path_str = str(verify_stderr_path)
            episodic_path = result.get("episodic_path") or item.get("episodic_path")
            # Note how to get episodic path
            
            if not episodic_path:
                print("\n    [ERROR] episodic is not valid!!")
                continue
            else:
                print(f"\n [Verify] Inspecting folder: {episodic_path}")
            
            try:
                verdict = re1.run_verification(
                    run_id=verification_run_id,
                    results_dir=result_path.parent,
                    task_id=task_id,
                    task_text=task["task"],
                    episodic_path_str=str(episodic_path or ""),
                    verify_result_path_str=verify_result_path_str,
                    verify_worktree_path=verify_worktree_path,
                    verify_model_config=verify_model_config,
                    verify_settings_path=verify_settings_path,
                    max_budget_usd=args.max_budget_usd,
                    skip_permissions=skip_permissions,
                    self_reported_success=item.get("self_reported_success", None),
                )
            except Exception as exc:
                print(
                    f"    [ERROR] verification process failed: {exc}",
                    file=sys.stderr,
                )
                error_count += 1
                continue
            
            # Update verification output files and result file
            verification_fields = update_result_with_verdict(
                result_path, result, verdict,
                verify_result_path=verify_result_path_str,
                verify_stdout_path=verify_stdout_path_str,
                verify_stderr_path=verify_stderr_path_str,
            )
            update_experiment_task(item, verification_fields)
            
            # Update worktree tasks file
            if not args.redo:
                try:
                    worktree_tasks_path, matches = update_worktree_task_file(
                        item, verification_fields
                    )
                except (FileNotFoundError, ValueError, OSError) as exc:
                    print(
                        f"    [WARN] could not update worktree_tasks.jsonl: {exc}",
                        file=sys.stderr,
                    )
                    worktree_log_unavailable_count += 1
                else:
                    if matches == 0:
                        print(
                            f"    [WARN] run_id={run_id} not found in "
                            f"{worktree_tasks_path}",
                            file=sys.stderr,
                        )
                        worktree_log_unavailable_count += 1
                    else:
                        worktree_log_updated_count += 1
                        if matches > 1:
                            print(
                                f"    [WARN] updated {matches} duplicate entries for "
                                f"run_id={run_id} in {worktree_tasks_path}",
                                file=sys.stderr,
                            )
                            
            # Checkpoint after every task so an interrupted batch does not lose the
            # verification records already completed.
            write_experiment_tasks(experiment_tasks_path, all_experiment_tasks)

            if verification_fields["verified_success"] is not None:
                print(
                    f"    verified_success={verification_fields['verified_success']}, "
                    f"agreement={verification_fields['verification_agreement']}"
                )
                verified_count += 1
            else:
                print(
                    f"    verification inconclusive — "
                    f"warnings: {verification_fields['verification_warnings']}"
                )
                inconclusive_count += 1

        print(
            f"\nDone: {verified_count} verified, "
            f"{inconclusive_count} inconclusive, "
            f"{skipped_count} skipped, "
            f"{error_count} errors; "
            f"{worktree_log_updated_count} worktree task log(s) updated, "
            f"{worktree_log_unavailable_count} unavailable"
        )
        if args.redo:
            print(f"Redo results were written to: {experiment_tasks_path}")
            print("Original artifacts and worktree task logs were left unchanged.")

    finally:
        re1.remove_worktree(verify_worktree_path)


if __name__ == "__main__":
    main()
5