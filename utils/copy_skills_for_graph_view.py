#!/usr/bin/env python3
"""Copy each procedural-memory skill's SKILL.md into procedural-memory-for-graph-view/,
renamed to the skill's name (e.g. <skill-name>.md), adding related_skills / related_pages
frontmatter fields parsed from the skill's "## Related" section. Re-running overwrites
existing copies and re-derives the related_* fields from scratch each time.

Also updates every semantic-memory/*.md page (except index.md) in place, adding/overriding
a related_skills_for_graph_view field mirroring its related_skills field in [[name]] form."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / ".claude" / "skills" / "procedural-memory"
SEM_DIR = ROOT / "semantic-memory"
DEST_DIR = ROOT / "procedural-memory-for-graph-view"

FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
RELATED_FIELD_RE = re.compile(
    r"^(?:related_skills|related_skills_for_graph_view|related_pages):[ \t]*"
    r"(?:\n(?:[ \t]+-.*\n?)*|\[[^\n]*\]\n?)?",
    re.MULTILINE,
)


def collect_valid_names() -> tuple[set, set]:
    skill_names = {p.name for p in SRC_DIR.iterdir() if p.is_dir()}
    page_names = {p.stem for p in SEM_DIR.glob("*.md")}
    return skill_names, page_names


def extract_related_section(body: str) -> str:
    lines = body.splitlines()
    section_lines = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if stripped.lower() == "## related":
                in_section = True
                continue
            if in_section:
                break
        elif in_section:
            section_lines.append(line)
    return "\n".join(section_lines)


def normalize_existing(values) -> list:
    """Strip [[ ]] / `` / quotes off any related_* entries already present in frontmatter."""
    names = []
    if not values:
        return names
    for raw in re.findall(r"-\s*(.+)", values):
        name = raw.strip().strip('"').strip("'")
        m = WIKILINK_RE.fullmatch(name) or BACKTICK_RE.fullmatch(name)
        if m:
            name = m.group(1)
        if name and name not in names:
            names.append(name)
    return names


def find_related(section_text: str, self_name: str, valid_skills: set, valid_pages: set):
    skills = []
    for name in BACKTICK_RE.findall(section_text):
        name = name.strip()
        if name in valid_skills and name != self_name and name not in skills:
            skills.append(name)
    pages = []
    for name in WIKILINK_RE.findall(section_text):
        name = name.strip()
        if name in valid_pages and name not in pages:
            pages.append(name)
    return skills, pages


def build_frontmatter(fm_text: str, skills: list, pages: list) -> str:
    fm_text = RELATED_FIELD_RE.sub("", fm_text).rstrip("\n")
    block = fm_text + "\n"
    if skills:
        block += "related_skills:\n"
        block += "".join(f"  - {name}\n" for name in skills)
        block += "related_skills_for_graph_view:\n"
        block += "".join(f'  - "[[{name}]]"\n' for name in skills)
    if pages:
        block += "related_pages:\n"
        block += "".join(f'  - "[[{name}]]"\n' for name in pages)
    return block


SEM_GRAPH_FIELD_RE = re.compile(
    r"^related_skills_for_graph_view:[ \t]*(?:\n(?:[ \t]+-.*\n?)*|\[[^\n]*\]\n?)?",
    re.MULTILINE,
)


def update_semantic_memory() -> int:
    """Add/override related_skills_for_graph_view in every semantic-memory page
    (except index.md), mirroring its related_skills field in [[name]] form."""
    updated = 0
    for page_file in sorted(SEM_DIR.glob("*.md")):
        if page_file.name == "index.md":
            continue

        text = page_file.read_text()
        match = FRONTMATTER_RE.match(text)
        if not match:
            continue

        fm_text = match.group(1)
        body = text[match.end():]

        related_skills_match = re.search(r"^related_skills:[ \t]*\n((?:[ \t]+-.*\n?)*)", fm_text, re.MULTILINE)
        if not related_skills_match:
            continue

        skills = normalize_existing(related_skills_match.group(1))
        if not skills:
            continue

        fm_text = SEM_GRAPH_FIELD_RE.sub("", fm_text)
        related_skills_match = re.search(r"^related_skills:[ \t]*\n((?:[ \t]+-.*\n?)*)", fm_text, re.MULTILINE)
        insert_at = related_skills_match.end()

        graph_block = "related_skills_for_graph_view:\n" + "".join(f'  - "[[{name}]]"\n' for name in skills)
        new_fm_text = fm_text[:insert_at] + graph_block + fm_text[insert_at:]

        new_text = f"---\n{new_fm_text}---\n{body}"
        if new_text != text:
            page_file.write_text(new_text)
            updated += 1

    return updated


def main() -> None:
    valid_skills, valid_pages = collect_valid_names()
    DEST_DIR.mkdir(exist_ok=True)

    copied = 0
    skipped = []
    for skill_dir in sorted(SRC_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        src_file = skill_dir / "SKILL.md"
        if not src_file.is_file():
            skipped.append(skill_dir.name)
            continue

        text = src_file.read_text()
        match = FRONTMATTER_RE.match(text)
        if not match:
            skipped.append(skill_dir.name)
            continue

        fm_text = match.group(1)
        body = text[match.end():]

        existing_skills_raw = re.search(
            r"^related_skills:[ \t]*\n((?:[ \t]+-.*\n?)*)", fm_text, re.MULTILINE
        )
        existing_skills_graph_raw = re.search(
            r"^related_skills_for_graph_view:[ \t]*\n((?:[ \t]+-.*\n?)*)", fm_text, re.MULTILINE
        )
        existing_pages_raw = re.search(r"^related_pages:[ \t]*\n((?:[ \t]+-.*\n?)*)", fm_text, re.MULTILINE)

        related_section = extract_related_section(body)
        found_skills, found_pages = find_related(related_section, skill_dir.name, valid_skills, valid_pages)

        skills = normalize_existing(existing_skills_raw.group(1) if existing_skills_raw else None)
        for name in normalize_existing(existing_skills_graph_raw.group(1) if existing_skills_graph_raw else None):
            if name not in skills:
                skills.append(name)
        for name in found_skills:
            if name not in skills:
                skills.append(name)

        pages = normalize_existing(existing_pages_raw.group(1) if existing_pages_raw else None)
        for name in found_pages:
            if name not in pages:
                pages.append(name)

        new_fm_text = build_frontmatter(fm_text, skills, pages)
        new_text = f"---\n{new_fm_text}---\n{body}"

        dest_file = DEST_DIR / f"{skill_dir.name}.md"
        dest_file.write_text(new_text)
        copied += 1

    print(f"Copied {copied} skill file(s) to {DEST_DIR}")
    if skipped:
        print(f"Skipped {len(skipped)} dir(s) with no SKILL.md: {', '.join(skipped)}")

    updated = update_semantic_memory()
    print(f"Updated related_skills_for_graph_view in {updated} semantic-memory page(s)")


if __name__ == "__main__":
    main()
