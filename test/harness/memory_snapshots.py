"""Building blocks for Experiment #4 (Learning Curve, test/experiments.md §4): reconstructing
N evenly-spaced memory snapshots from log.md's append-only history, and sizing each snapshot
by reusing utils/get_memory_statistics.py rather than re-implementing skill/page counting.

This module only computes *which commit* corresponds to each snapshot point — it does not
check anything out or create worktrees itself (that's Experiment #4's own runner, built when
that experiment actually runs; Phase 0 only needs the reusable logic in place per §6 item 5).

Known limitation, discovered while building this: this repo's git history was squashed into
a single "Initial commit" on 2026-07-30, but log.md has real, dated entries going back to
2026-07-21 — so `resolve_commit_for_timestamp` cannot find a matching commit for any cutoff
before the squash, even though log.md itself has genuine history there. `count_items_as_of`
is the fallback for that: it sizes a snapshot straight from log.md's own tables, independent
of git, so the learning curve's x-axis (memory size) is still recoverable everywhere even on
the stretch where re-running the benchmark against reconstructed file *content* is not.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.get_memory_statistics import get_procedural_skills, get_semantic_memories  # noqa: E402

LOG_MD = REPO_ROOT / "log.md"

# log.md has used two timestamp spellings across its history — ISO ("2026-07-21T09:00:00")
# and underscore-separated ("2026-07-24_08-58-09", matching episodic-memory folder names).
# Parse both rather than assuming the file is internally consistent. Anchored to the start
# of a table row (`| <timestamp> | ...`) so this only matches the Timestamp *column*, not an
# incidental date mentioned inside a free-text Change/Findings cell.
_ROW_TS_RE = re.compile(
    r"^\|\s*(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}|_\d{2}-\d{2}-\d{2}))\s*\|",
    re.MULTILINE,
)


def _parse_log_timestamp(token: str) -> datetime | None:
    try:
        return datetime.strptime(token, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        pass
    try:
        return datetime.strptime(token, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return None


def _extract_table(text: str, begin_marker: str, end_marker: str) -> str:
    start = text.find(begin_marker)
    end = text.find(end_marker)
    if start == -1 or end == -1:
        return ""
    return text[start:end]


def get_current_counts(repo_root: Path = REPO_ROOT) -> dict:
    """Reuses utils/get_memory_statistics.py's own functions (per §6 item 5) rather
    than re-deriving skill/page counts a second way."""
    skills = get_procedural_skills(repo_root)
    pages = get_semantic_memories(repo_root)
    return {"procedural_skill_count": len(skills), "semantic_page_count": len(pages)}


def _row_timestamps(table_text: str) -> list[datetime]:
    out = []
    for match in _ROW_TS_RE.finditer(table_text):
        ts = _parse_log_timestamp(match.group(1))
        if ts is not None:
            out.append(ts)
    return out


def _parse_table_rows(table_text: str) -> list[tuple[datetime, str, str]]:
    """Returns (timestamp, item, operation) for each well-formed row in a
    Timestamp|Item|Operation|Change table, skipping the header/separator rows."""
    rows: list[tuple[datetime, str, str]] = []
    for line in table_text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("Timestamp", "---"):
            continue
        ts = _parse_log_timestamp(cells[0])
        if ts is None:
            continue
        rows.append((ts, cells[1], cells[2]))
    return rows


def list_log_md_timestamps(log_path: Path = LOG_MD) -> list[datetime]:
    """Every distinct timestamp appearing in log.md's two memory-update tables
    (procedural + semantic — the Lint Runs Record table is deliberately excluded,
    since lint passes aren't memory-content snapshots), in chronological order.
    log.md is append-only, so file order already tracks chronological order, but
    timestamps are re-sorted anyway for robustness against any manual edits."""
    text = log_path.read_text()
    procedural = _extract_table(text, "<!--LOG_TABLE:PROCEDURAL-->", "<!--END_LOG_TABLE:PROCEDURAL-->")
    semantic = _extract_table(text, "<!--LOG_TABLE:SEMANTIC-->", "<!--END_LOG_TABLE:SEMANTIC-->")
    found = set(_row_timestamps(procedural)) | set(_row_timestamps(semantic))
    return sorted(found)


def count_items_as_of(cutoff: datetime | None, log_path: Path = LOG_MD) -> dict:
    """Git-independent snapshot sizing: replays log.md's two tables up to `cutoff`
    and counts items whose most recent operation at or before that time wasn't
    "removed". Useful as a fallback (or cross-check) wherever `resolve_commit_for_timestamp`
    can't find a matching commit — see the module docstring's note on this repo's
    squashed early git history. `cutoff=None` means "before log.md's first entry"
    (the 0% snapshot), not "unbounded" — it returns zero counts, not the full total."""
    if cutoff is None:
        return {"procedural_skill_count": 0, "semantic_page_count": 0}
    text = log_path.read_text()
    counts = {}
    for label, markers in (
        ("procedural_skill_count", ("<!--LOG_TABLE:PROCEDURAL-->", "<!--END_LOG_TABLE:PROCEDURAL-->")),
        ("semantic_page_count", ("<!--LOG_TABLE:SEMANTIC-->", "<!--END_LOG_TABLE:SEMANTIC-->")),
    ):
        table_text = _extract_table(text, *markers)
        last_op: dict[str, str] = {}
        for ts, item, operation in _parse_table_rows(table_text):
            if cutoff is not None and ts > cutoff:
                continue
            last_op[item] = operation.lower()
        counts[label] = sum(1 for op in last_op.values() if op != "removed")
    return counts


@dataclass
class SnapshotTarget:
    index: int
    fraction: float
    cutoff_timestamp: datetime | None  # None means "before any memory existed"
    resolved_commit: str | None = None
    log_derived_counts: dict | None = None  # git-independent fallback sizing


def pick_snapshot_targets(timestamps: list[datetime], n: int = 6) -> list[SnapshotTarget]:
    """N evenly spaced points across log.md's history, per Experiment #4's methodology
    (e.g. n=6: 0%, 20%, 40%, 60%, 80%, 100% of accumulation so far)."""
    if not timestamps:
        return [SnapshotTarget(index=0, fraction=0.0, cutoff_timestamp=None)]

    targets: list[SnapshotTarget] = []
    for i in range(n):
        fraction = i / (n - 1) if n > 1 else 1.0
        if fraction <= 0:
            targets.append(SnapshotTarget(index=i, fraction=0.0, cutoff_timestamp=None))
            continue
        pos = min(int(round(fraction * (len(timestamps) - 1))), len(timestamps) - 1)
        targets.append(SnapshotTarget(index=i, fraction=fraction, cutoff_timestamp=timestamps[pos]))
    return targets


def resolve_commit_for_timestamp(cutoff: datetime | None, repo_root: Path = REPO_ROOT) -> str | None:
    """Nearest commit at or before `cutoff` on the current branch's history, via
    `git log --before`. Returns None for the "0 memory" (before-any-commit) snapshot,
    which has no corresponding commit at all."""
    if cutoff is None:
        return None
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", f"--before={cutoff.isoformat()}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    commit = result.stdout.strip()
    return commit or None


def build_snapshot_plan(n: int = 6, repo_root: Path = REPO_ROOT) -> list[SnapshotTarget]:
    """Note: in this repo, git history was squashed on 2026-07-30 (see log.md entries
    dated before that with no corresponding commit) — `resolved_commit` will be None
    for any snapshot whose cutoff predates the squash, even though log.md has real
    entries there. `log_derived_counts` still gives a correct *size* for those points
    from log.md alone; only literal file-content checkout is unavailable for them, so
    Experiment #4 can plot the full learning curve by size, but can only re-run early
    snapshots against real memory *content* from the earliest resolvable commit onward."""
    timestamps = list_log_md_timestamps(repo_root / "log.md")
    targets = pick_snapshot_targets(timestamps, n=n)
    for target in targets:
        target.resolved_commit = resolve_commit_for_timestamp(target.cutoff_timestamp, repo_root)
        target.log_derived_counts = count_items_as_of(target.cutoff_timestamp, repo_root / "log.md")
    return targets


if __name__ == "__main__":
    print("Current memory (live file scan):", get_current_counts())
    for t in build_snapshot_plan():
        checkoutable = "yes" if (t.resolved_commit or t.cutoff_timestamp is None) else "NO (pre-squash)"
        print(
            f"snapshot {t.index} ({t.fraction:.0%}): cutoff={t.cutoff_timestamp} "
            f"commit={t.resolved_commit} checkoutable={checkoutable} "
            f"log_derived_counts={t.log_derived_counts}"
        )
