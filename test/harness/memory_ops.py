"""Realize one of test/experiments.md's Experiment #1 memory conditions inside a
disposable git worktree, before `claude -p` is invoked against it.

Every function here mutates files *only* inside the given worktree path. The main
repo is never touched — the worktree is a full, disposable checkout, so deleting
files inside it is safe and (per test/experiments.md §2's contamination-control
requirement) exactly how the benchmark is kept from ever polluting real memory:
the worktree is discarded after the run, never merged or pushed anywhere.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

PROCEDURAL_MEMORY_REL = Path(".claude/skills/procedural-memory")
SYSTEM_SKILLS_REL = Path(".claude/skills/system")
AGENTS_REL = Path(".claude/agents")
SEMANTIC_MEMORY_REL = Path("semantic-memory")
CLAUDE_MD_REL = Path("CLAUDE.md")

_PAGE_ROW_RE = re.compile(r"^\|\s*\[\[.+\]\]\s*\|")


def empty_procedural_memory(worktree: Path) -> None:
    """Remove every skill subdirectory, but keep the parent directory itself
    (experiments.md: "temporarily empty (not delete)")."""
    proc_dir = worktree / PROCEDURAL_MEMORY_REL
    if not proc_dir.is_dir():
        return
    for child in proc_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)


def _empty_index_md(index_path: Path) -> None:
    """Rewrite semantic-memory/index.md keeping its frontmatter, section headers,
    and table header rows, but with every page-row (`| [[page]] | ... |`) removed.
    
    _PAGE_ROW_RE is a regex that identifies a page-listing row in semantic-memory/index.md's markdown tables, 
    so _empty_index_md can filter those rows out while leaving everything else — frontmatter, section headings,
    the table's own header row — intact.
    """
    if not index_path.exists():
        return
    lines = index_path.read_text().splitlines(keepends=True)
    kept = [line for line in lines if not _PAGE_ROW_RE.match(line)]
    index_path.write_text("".join(kept))


def empty_semantic_memory(worktree: Path) -> None:
    """Remove every semantic-memory/*.md page except index.md, and empty
    index.md's page rows while keeping its structure (experiments.md: "keep
    index.md structure but empty its entries")."""
    sem_dir = worktree / SEMANTIC_MEMORY_REL
    if not sem_dir.is_dir():
        return
    for page in sem_dir.glob("*.md"):
        if page.name != "index.md":
            page.unlink()  # NOTE: Delete the page file
    _empty_index_md(sem_dir / "index.md")


def strip_claude_md(worktree: Path) -> None:
    """Delete the CLAUDE.md file from the worktree, if it exists (experiments.md: "strip CLAUDE.md")."""
    path = worktree / CLAUDE_MD_REL
    if path.exists():
        path.unlink()


def strip_system_skills(worktree: Path) -> None:
    """Delete the .claude/skills/system directory from the worktree, if it exists (experiments.md: "strip system skills")."""
    path = worktree / SYSTEM_SKILLS_REL
    if path.is_dir():
        shutil.rmtree(path)


def strip_agents(worktree: Path) -> None:
    """Delete the .claude/agents directory from the worktree, if it exists (experiments.md: "strip agents")."""
    path = worktree / AGENTS_REL
    if path.is_dir():
        shutil.rmtree(path)


def apply_condition(worktree: Path, condition: dict) -> None:
    """Apply one condition dict from conditions.yaml to a worktree checkout."""
    if condition.get("empty_procedural_memory"):
        empty_procedural_memory(worktree)
    if condition.get("empty_semantic_memory"):
        empty_semantic_memory(worktree)
    if condition.get("strip_claude_md"):
        strip_claude_md(worktree)
    if condition.get("strip_system_skills"):
        strip_system_skills(worktree)
    if condition.get("strip_agents"):
        strip_agents(worktree)
