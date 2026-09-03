#!/usr/bin/env python3

from pathlib import Path


def get_procedural_skills(root: Path) -> list[str]:
    """Return the names of skill directories."""
    procedural_dir = root / ".claude" / "skills" / "procedural-memory"

    return sorted(
        p.name
        for p in procedural_dir.iterdir()
        if p.is_dir()
    )


def get_semantic_memories(root: Path) -> list[str]:
    """Return semantic memory names (without .md), excluding index.md."""
    semantic_dir = root / "semantic-memory"

    return sorted(
        p.stem
        for p in semantic_dir.glob("*.md")
        if p.stem != "index"
    )


def main() -> None:
    root = Path.cwd()

    procedural_skills = get_procedural_skills(root)
    semantic_memories = get_semantic_memories(root)

    print("=== Procedural Skills ===")
    print(procedural_skills)
    print(f"Count: {len(procedural_skills)}")
    print()

    print("=== Semantic Memories ===")
    print(semantic_memories)
    print(f"Count: {len(semantic_memories)}")


if __name__ == "__main__":
    main()