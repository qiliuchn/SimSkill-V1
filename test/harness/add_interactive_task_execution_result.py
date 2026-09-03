"""Add an interactive Claude Code task run to the experiment result stores.

Use this after manually executing one benchmark task in the interactive Claude Code
UI.  The script reconstructs the information that ``run_experiment.py`` normally gets
from ``claude -p --output-format json`` from the saved session transcript instead.  It
then writes the same three kinds of records as the automated harness:

* ``test/results/<run_id>.json`` in the main checkout;
* placeholder stdout/stderr files under ``test/results/raw/`` (interactive mode has no
  captured process output), alongside a ``<run_id>.claude_result.json`` sidecar holding
  the reconstructed whole-tree ``modelUsage`` so the run can be repriced later; and
* one JSON object appended to both the worktree-local ``test/worktree_tasks.jsonl`` and
  the main checkout's ``test/experiment_tasks.jsonl``.

Independent verification is intentionally left for ``verify.py``.  Consequently,
``verified_success`` and ``verification_agreement`` are null in all newly written
records.

Example::

python test/harness/add_interactive_task_execution_result.py \
        --condition full-ver \
        --model deepseek-v4-pro \
        --task-id MT-T3 \
        --repeat 1 \
        --session-id 4172b334-fd15-428c-bf19-9770a1c3eeaa \
        --episodic-path 2026-08-11_15-16-33

By default, the worktree is expected at
``<worktree-root>/<condition>_<model>``.  Use ``--worktree-path`` for a worktree with
another name.  ``--episodic-path`` may be an absolute path, a path relative to the
worktree, or just the record directory name beneath ``episodic-memory/``.  The session
transcript is searched for under both the experiment worktree and the main repository,
because an interactive Claude session may have been launched from either directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_experiment as re1


INTERACTIVE_OUTPUT_PLACEHOLDER = "absent since running in interactive mode\n"
DEFAULT_EXPERIMENT_TASKS = re1.REPO_ROOT / "test" / "experiment_tasks.jsonl"


@dataclass
class TranscriptSummary:
    """Measurements recoverable from an interactive session transcript."""

    start_time_utc: str
    end_time_utc: str
    wall_clock_ms: int
    usage: dict[str, int]
    model_usage: dict[str, dict[str, int]]
    num_turns: int
    warnings: list[str] = field(default_factory=list)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Return an aware UTC datetime for a transcript timestamp, if valid."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _nonnegative_int(value: Any) -> int:
    """Coerce a transcript token counter to a non-negative integer."""
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def summarize_transcript(transcript_path: Path, session_id: str) -> TranscriptSummary:
    """Read an interactive JSONL transcript and reconstruct timing/token metrics.

    Claude Code writes one assistant response as several JSONL records when the response
    contains multiple content blocks.  Every such record repeats the response's complete
    usage object, so summing records would substantially over-count tokens.  Usage is
    therefore counted once per ``message.id`` (falling back to the record UUID).
    """
    timestamps: list[datetime] = []
    assistant_usages: dict[str, tuple[dict[str, Any], str]] = {}
    malformed_lines = 0
    matching_session_records = 0
    subagent_dir = transcript_path.parent / transcript_path.stem / "subagents"
    transcript_paths = [transcript_path]
    if subagent_dir.is_dir():
        transcript_paths.extend(sorted(subagent_dir.glob("*.jsonl")))

    for current_transcript in transcript_paths:
        try:
            handle = current_transcript.open("r", encoding="utf-8")
        except OSError as exc:
            raise ValueError(
                f"cannot read transcript {current_transcript}: {exc}"
            ) from exc

        with handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    malformed_lines += 1
                    continue
                if not isinstance(record, dict):
                    malformed_lines += 1
                    continue

                record_session_id = record.get("sessionId") or record.get("session_id")
                if record_session_id is not None and str(record_session_id) != session_id:
                    continue
                matching_session_records += 1

                timestamp = _parse_timestamp(record.get("timestamp"))
                if timestamp is not None:
                    timestamps.append(timestamp)

                if record.get("type") != "assistant":
                    continue
                message = record.get("message")
                if not isinstance(message, dict):
                    continue
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue

                # A response may be split into thinking/text/tool_use records.
                # message.id is stable across those chunks, while the outer
                # record UUID is not. Prefix with the transcript path so a
                # subagent cannot collide with another agent's response id.
                response_id = message.get("id") or record.get("uuid")
                if response_id is None:
                    response_id = f"line-{line_number}"
                response_key = f"{current_transcript}:{response_id}"
                model_name = str(message.get("model") or "unknown")
                assistant_usages[response_key] = (usage, model_name)

    if matching_session_records == 0:
        raise ValueError(
            f"transcript {transcript_path} contains no records for session {session_id}"
        )
    if not timestamps:
        raise ValueError(f"transcript {transcript_path} has no valid timestamps")

    token_fields = {
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "cache_creation_input_tokens": "cache_creation_input_tokens",
        "cache_read_input_tokens": "cache_read_input_tokens",
    }
    totals = {
        output_name: sum(
            _nonnegative_int(usage.get(source_name))
            for usage, _model_name in assistant_usages.values()
        )
        for output_name, source_name in token_fields.items()
    }

    model_usage: dict[str, dict[str, int]] = {}
    model_field_names = {
        "input_tokens": "inputTokens",
        "output_tokens": "outputTokens",
        "cache_creation_input_tokens": "cacheCreationInputTokens",
        "cache_read_input_tokens": "cacheReadInputTokens",
    }
    for usage, model_name in assistant_usages.values():
        model_totals = model_usage.setdefault(
            model_name,
            {raw_name: 0 for raw_name in model_field_names.values()},
        )
        for transcript_name, raw_name in model_field_names.items():
            model_totals[raw_name] += _nonnegative_int(usage.get(transcript_name))

    start = min(timestamps)
    end = max(timestamps)
    wall_clock_ms = max(int((end - start).total_seconds() * 1000), 0)
    warnings = [
        "interactive run: wall-clock and token metrics were reconstructed from the "
        "Claude Code transcript",
        "interactive transcript wall-clock includes time spent waiting for user input",
    ]
    if not assistant_usages:
        warnings.append(
            "interactive transcript has no assistant usage records — token fields "
            "default to 0"
        )
    if malformed_lines:
        warnings.append(
            f"ignored {malformed_lines} malformed JSONL line(s) in the interactive transcript"
        )
    if len(transcript_paths) > 1:
        warnings.append(
            f"interactive token accounting included {len(transcript_paths) - 1} "
            "subagent transcript(s)"
        )

    return TranscriptSummary(
        start_time_utc=start.isoformat(),
        end_time_utc=end.isoformat(),
        wall_clock_ms=wall_clock_ms,
        usage=totals,
        model_usage=model_usage,
        num_turns=len(assistant_usages),
        warnings=warnings,
    )


def resolve_worktree_path(
    *,
    worktree_path: Optional[Path],
    worktree_root: Path,
    condition: str,
    model: str,
    session_id: str,
) -> Path:
    """Resolve the worktree, preferring the conventional condition/model name.

    Automatically generated harness worktrees carry a timestamp and task label.  If the
    conventional path is absent, use the transcript location to disambiguate matching
    directories under ``worktree_root``.  An explicit ``--worktree-path`` always wins.
    """
    if worktree_path is not None:
        resolved = worktree_path.expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"worktree does not exist or is not a directory: {resolved}")
        return resolved

    root = worktree_root.expanduser().resolve()
    conventional = root / f"{condition}_{model}"
    if conventional.is_dir():
        return conventional.resolve()

    if not root.is_dir():
        raise ValueError(f"worktree root does not exist or is not a directory: {root}")

    marker = f"_{condition}_{model}_"
    candidates = [
        path.resolve()
        for path in root.iterdir()
        if path.is_dir()
        and (path.name.startswith(f"{condition}_{model}") or marker in f"_{path.name}_")
    ]
    transcript_matches = [
        path
        for path in candidates
        if re1.cost_time.find_transcript_path(path, session_id).is_file()
    ]
    if len(transcript_matches) == 1:
        return transcript_matches[0]
    if len(candidates) == 1:
        return candidates[0]

    if transcript_matches:
        detail = ", ".join(str(path) for path in transcript_matches)
        raise ValueError(
            f"multiple worktrees match condition/model/session: {detail}; "
            "pass --worktree-path"
        )
    detail = ", ".join(str(path) for path in candidates) or "none"
    raise ValueError(
        f"could not identify one worktree for condition={condition!r}, model={model!r}; "
        f"matching directories: {detail}. Pass --worktree-path."
    )


def resolve_episodic_path(value: Path, worktree_path: Path) -> Path:
    """Resolve and validate an episodic record directory inside the worktree."""
    episodic_root = (worktree_path / "episodic-memory").resolve()
    supplied = value.expanduser()
    if supplied.is_absolute():
        candidate = supplied.resolve()
    elif supplied.parts and supplied.parts[0] == "episodic-memory":
        candidate = (worktree_path / supplied).resolve()
    else:
        candidate = (episodic_root / supplied).resolve()

    try:
        candidate.relative_to(episodic_root)
    except ValueError as exc:
        raise ValueError(
            f"episodic path must be inside {episodic_root}, got {candidate}"
        ) from exc
    if not candidate.is_dir():
        raise ValueError(
            f"episodic record does not exist or is not a directory: {candidate}"
        )
    summary_path = candidate / "summary.md"
    if not summary_path.is_file():
        raise ValueError(f"episodic record has no summary.md: {candidate}")
    return candidate


def load_episodic_record(episodic_path: Path) -> dict[str, Any]:
    """Load the summary frontmatter in the form expected by the main harness."""
    summary_path = episodic_path / "summary.md"
    record = re1.parse_frontmatter(summary_path)
    record["_summary_path"] = str(summary_path)
    return record


def find_interactive_transcript(
    worktree_path: Path, session_id: str
) -> tuple[Path, Path]:
    """Return ``(transcript_path, transcript_cwd)`` for an interactive session.

    Automated harness sessions run with the experiment worktree as their cwd, whereas a
    user commonly launches interactive Claude from the main checkout and directs it to
    operate on the worktree.  Claude Code buckets transcripts by the launch cwd, so check
    both locations in that order.
    """
    candidate_cwds = [worktree_path, re1.REPO_ROOT.resolve()]
    checked: list[Path] = []
    for candidate_cwd in candidate_cwds:
        candidate_cwd = candidate_cwd.resolve()
        transcript_path = re1.cost_time.find_transcript_path(
            candidate_cwd, session_id
        )
        if transcript_path in checked:
            continue
        checked.append(transcript_path)
        if transcript_path.is_file():
            return transcript_path, candidate_cwd

    locations = ", ".join(str(path) for path in checked)
    raise ValueError(
        f"transcript not found for session {session_id}; checked: {locations}"
    )


def write_claude_result_sidecar(
    run_id: str, raw_result: dict[str, Any], results_dir: Path
) -> Path:
    """Persist the reconstructed ``claude -p --output-format json`` result object.

    Interactive runs have no captured stdout, so ``write_raw_output`` stores only a
    placeholder there. The token accounting recovered from the transcript would
    otherwise survive solely as the derived ``cost_usd`` frozen at ingestion time,
    leaving the run un-repriceable against a newer price table. Writing the object
    to its own file keeps the whole-tree ``modelUsage`` available.
    """
    raw_dir = results_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = raw_dir / f"{run_id}.claude_result.json"
    sidecar_path.write_text(
        json.dumps(raw_result, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n  [Usage] Wrote reconstructed claude result to {sidecar_path}")
    return sidecar_path


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    """Append one task record to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, default=str) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--condition", required=True)
    parser.add_argument("--model", required=True, help="key in test/harness/models.yaml")
    parser.add_argument("--task-id", required=True, help="task id from benchmark_tasks.yaml")
    parser.add_argument("--repeat", required=True, type=int, help="one-based repeat index")
    parser.add_argument("--session-id", required=True, help="Claude Code session/transcript id")
    parser.add_argument(
        "--episodic-path",
        "--episodic_path",
        dest="episodic_path",
        required=True,
        type=Path,
        help="episodic record directory (or its name beneath worktree/episodic-memory)",
    )
    parser.add_argument("--benchmark", type=Path, default=re1.DEFAULT_BENCHMARK)
    parser.add_argument(
        "--conditions-file", type=Path, default=re1.HARNESS_DIR / "conditions.yaml"
    )
    parser.add_argument("--models-file", type=Path, default=re1.HARNESS_DIR / "models.yaml")
    parser.add_argument(
        "--price-table", type=Path, default=re1.HARNESS_DIR / "price_table.yaml"
    )
    parser.add_argument("--results-dir", type=Path, default=re1.DEFAULT_RESULTS_DIR)
    parser.add_argument("--worktree-root", type=Path, default=re1.DEFAULT_WORKTREE_ROOT)
    parser.add_argument(
        "--worktree-path",
        type=Path,
        default=None,
        help="explicit worktree path (overrides --worktree-root discovery)",
    )
    parser.add_argument(
        "--experiment-tasks",
        type=Path,
        default=DEFAULT_EXPERIMENT_TASKS,
        help="main experiment task JSONL log",
    )
    parser.add_argument(
        "--repeats-requested",
        type=int,
        default=None,
        help="planned repeat count stored in the result (defaults to --repeat)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and reconstruct the record without writing any files",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    repeats_requested = args.repeats_requested or args.repeat
    if repeats_requested < args.repeat:
        parser.error("--repeats-requested cannot be smaller than --repeat")

    benchmark = re1.load_yaml(args.benchmark)
    conditions = re1.load_yaml(args.conditions_file).get("conditions") or {}
    models = re1.load_yaml(args.models_file).get("models") or {}
    price_table = re1.load_yaml(args.price_table)
    if args.condition not in conditions:
        parser.error(f"unknown condition {args.condition!r} — choices: {sorted(conditions)}")
    if args.model not in models:
        parser.error(f"unknown model {args.model!r} — choices: {sorted(models)}")
    try:
        task = re1.find_task(benchmark, args.task_id)
        worktree_path = resolve_worktree_path(
            worktree_path=args.worktree_path,
            worktree_root=args.worktree_root,
            condition=args.condition,
            model=args.model,
            session_id=args.session_id,
        )
        episodic_path = resolve_episodic_path(args.episodic_path, worktree_path)
        episodic_record = load_episodic_record(episodic_path)
        transcript_path, transcript_cwd = find_interactive_transcript(
            worktree_path, args.session_id
        )
        transcript = summarize_transcript(transcript_path, args.session_id)
    except (KeyError, OSError, ValueError) as exc:
        parser.error(str(exc))

    raw_result = {
        "session_id": args.session_id,
        "duration_ms": transcript.wall_clock_ms,
        "duration_api_ms": None,
        "num_turns": transcript.num_turns,
        "is_error": None,
        "subtype": "interactive",
        "usage": transcript.usage,
        "modelUsage": transcript.model_usage,
    }
    raw = {
        "cmd": None,
        "returncode": None,
        "stdout": INTERACTIVE_OUTPUT_PLACEHOLDER,
        "stderr": INTERACTIVE_OUTPUT_PLACEHOLDER,
        "raw_result": raw_result,
        "raw_stdout_parse_error": None,
        "start_time_utc": transcript.start_time_utc,
        "end_time_utc": transcript.end_time_utc,
        "wall_clock_ms_measured": transcript.wall_clock_ms,
        "episodic_path": str(episodic_path),
        "episodic_record": episodic_record,
        "task": task,
        "model_key": args.model,
    }

    run_id = re1.make_run_id(args.condition, args.model, args.task_id, args.repeat)
    results_dir = args.results_dir.expanduser().resolve()
    # Passing an explicit pending-verification payload keeps both verification fields
    # null while allowing the shared annotator to initialize its verification variables.
    # (The ``None`` branch in older copies of run_experiment.py did not initialize
    # ``verification_agreement``.)
    pending_verification = {
        "verified_success": None,
        "agreement": None,
        "critique": None,
        "warnings": [
            "verification skipped during interactive result ingestion — use "
            "test/harness/verify.py"
        ],
    }
    result = re1.annotate_with_cost_time(
        raw,
        transcript_cwd,
        args.model,
        price_table,
        verify_result=pending_verification,
    )
    result.update(
        {
            "run_id": run_id,
            "condition": args.condition,
            "repeat": args.repeat,
            "repeats_requested": repeats_requested,
            "cache_mode": "cold",
            "worktree_path": str(worktree_path),
            "git_ref": "HEAD",
            "batch_session_id": args.session_id,
            "batch_position": 0,
            "batch_size": 1,
        }
    )
    result["warnings"].extend(transcript.warnings)

    raw_dir = results_dir / "raw"
    raw_paths = {
        "stdout": str(raw_dir / f"{run_id}.stdout.log"),
        "stderr": str(raw_dir / f"{run_id}.stderr.log"),
    }
    result["raw_stdout_path"] = raw_paths["stdout"]
    result["raw_stderr_path"] = raw_paths["stderr"]
    result_path = results_dir / f"{run_id}.json"

    task_item = {
        "task_id": task["id"],
        "task_condition": args.condition,
        "task_model": args.model,
        "task_repeat": args.repeat,
        "worktree_path": str(worktree_path),
        "session_id": args.session_id,
        "run_id": run_id,
        "episodic_path": str(episodic_path),
        "result_path": str(result_path),
        "self_reported_success": result["self_reported_success"],
        "verified_success": None,
        "verification_agreement": None,
        "raw_stdout_path": raw_paths["stdout"],
        "raw_stderr_path": raw_paths["stderr"],
        "raw_claude_result_path": str(raw_dir / f"{run_id}.claude_result.json"),
        "verify_result_path": str(results_dir / "verify" / f"{run_id}.json"),
        "verify_stdout_path": str(raw_dir / f"{run_id}.verify.stdout.log"),
        "verify_stderr_path": str(raw_dir / f"{run_id}.verify.stderr.log"),
        "transcript_path": str(transcript_path),
    }

    worktree_tasks_path = worktree_path / "test" / "worktree_tasks.jsonl"
    experiment_tasks_path = args.experiment_tasks.expanduser().resolve()
    if args.dry_run:
        print("[dry-run] reconstructed result:")
        print(json.dumps(result, indent=2, default=str))
        print(f"[dry-run] would write result: {result_path}")
        print(f"[dry-run] would write raw logs beneath: {raw_dir}")
        print(
            "[dry-run] would write reconstructed claude result: "
            f"{raw_dir / f'{run_id}.claude_result.json'}"
        )
        print(f"[dry-run] would append task record: {worktree_tasks_path}")
        print(f"[dry-run] would append task record: {experiment_tasks_path}")
        return

    # All inputs are validated before the first write so an invalid transcript or
    # episodic record cannot leave a partial experiment entry behind.
    actual_raw_paths = re1.write_raw_output(run_id, raw, results_dir)
    result["raw_stdout_path"] = actual_raw_paths["stdout"]
    result["raw_stderr_path"] = actual_raw_paths["stderr"]
    # The placeholder stdout log carries no usage, so downstream repricing
    # (aggregate_results.reprice_result) would have nothing to read. Persist the
    # reconstructed whole-tree result — same shape as `claude -p --output-format
    # json` — beside it so an interactive run reprices exactly like a scripted one.
    result["raw_claude_result_path"] = str(
        write_claude_result_sidecar(run_id, raw_result, results_dir)
    )
    result_path = re1.write_result(result, results_dir)
    task_item["result_path"] = str(result_path)
    task_item["raw_stdout_path"] = actual_raw_paths["stdout"]
    task_item["raw_stderr_path"] = actual_raw_paths["stderr"]
    task_item["raw_claude_result_path"] = result["raw_claude_result_path"]
    append_jsonl(worktree_tasks_path, task_item)
    append_jsonl(experiment_tasks_path, task_item)

    print(f"\n[Results] wrote {result_path}")
    print(f"[Task log] appended {worktree_tasks_path}")
    print(f"[Experiment log] appended {experiment_tasks_path}")
    print("[Verification] pending; run test/harness/verify.py to verify this result")


if __name__ == "__main__":
    main()
