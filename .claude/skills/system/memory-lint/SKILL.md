---
name: memory-lint
description: Autonomously lint the procedural memory and semantic memory — merging redundant items, fixing broken or drifted cross-references, and removing superseded items. Runs in incremental mode by default (only newly added/updated items, gated by how much new material has accumulated since the last lint pass) or full mode on request (every skill and page, unconditionally). Use when user asks to lint the memory, or to run a full/complete memory lint.
---

## Purpose

Keep procedural memory (skills) and semantic memory (knowledge pages) healthy as they grow: merge near-duplicates, fix cross-references that no longer resolve or have drifted out of sync, and remove items that have been fully superseded. Unlike a report-only linter, this skill **applies fixes directly** for anything mechanical or unambiguous.


## Steps

### 0. Determine mode and scope

- **Mode**: default to **incremental mode**. Run **full mode** instead only if the invocation explicitly asks for it (phrases like "full lint", "lint everything", "check all skills/pages", "full mode").
- Invoke the `log` skill's `get-open-row-info` operation to get the open row's item count and item names, without reading `log.md` yourself (there is always exactly one open row, at the bottom of the `Lint Runs Record` table). This is needed in both modes — in incremental mode to gate and scope this pass, in full mode so the row can still be closed at the end (step 8).
- **Incremental mode**: if the open row's item count is **below 10** (default threshold — adjust if the user specifies a different number), stop here and skip every remaining step; there isn't enough new material to make a lint pass worthwhile yet. Otherwise continue, with scope = the items returned by `get-open-row-info` — only newly added or updated skills (procedural memory) and pages (semantic memory).
- **Full mode**: ignore the threshold entirely and always continue. Scope = every skill in `.claude/skills/procedural-memory/` and every page in `semantic-memory/`, regardless of what `get-open-row-info` returned.

### Procedural memory

1. Check for skills covering similar or overlapping ground (compare scoped skills against the full procedural-memory library, since a duplicate may be an older, out-of-scope skill). If two are largely duplicative, merge them into one more general skill and remove the redundant one. If they're similar but each has a distinct enough purpose that merging would lose something, leave them separate and note why in the findings.
2. For every skill in scope, if it invokes another skill (in its SKILL.md text or its scripts), confirm the referenced skill still exists under that name and that the assumed interface (script arguments, expected inputs/outputs) still matches what it actually provides. Fix drifted references directly — update the name, path, or argument being referenced.
3. It is good practice to leverage existing skills and knowledge to develop new skills, building more complex capabilities by composing simpler ones rather than starting from scratch each time. For every skill in scope, check whether it can be conveniently expressed as a composition of existing simpler skills. If so, try replace it with the composed implementation (make sure the new composite skill indeed works by executing it!) and (if new composite skill indeed works) remove the original standalone skill.
4. Remove skills that are fully superseded by a newer skill (the newer skill can fulfill the older skill's functionality in the same way; but the newer skill is more generally applicably or better designed). Before removing, update any other skill or knowledge page that referenced the removed one, so nothing is left pointing at a name that no longer exists.

### Semantic memory

5. Check for pages covering similar or overlapping ground (compare scoped pages against the full semantic-memory library, same reasoning as step 1); merge duplicates into one more comprehensive page, same standard as step 1 — merge only when they're genuinely redundant, not just related.
6. For every page in scope, confirm each `[[page-name]]` link resolves to a page that still exists, and that `related_skills` entries reference skills that still exist in procedural memory. Fix broken links directly (update to the merged/renamed target, or remove the link if the target was removed with nothing to redirect to).
7. Remove pages fully superseded by a newer, more accurate page, updating any other page's `[[links]]`/`related_pages` that pointed at the removed one.

### Sync and record

8. Update `semantic-memory/index.md` to match reality: add missing pages, remove entries for deleted/merged pages, and re-sync each entry's `summary`/`keywords` with the corresponding page's current frontmatter.
9. Invoke the `log` skill to record this pass, without reading or writing `log.md` yourself:
   - Run its `add-procedural-row`/`add-semantic-row` operations for every merge, removal, or content update made in steps 1-8, so "Procedural Memory Updates" and "Semantic Memory Updates" table in `log.md` are updated.
   - Run its `close-open` operation, passing the current timestamp plus `Findings`/`Actions Taken` describing what this pass found and did (one-to-one — each finding paired with the action taken on it). This closes the current open `Lint Runs Record` row of "Lint Runs Record" table **and** appends a fresh empty open row below it in the same call — the new pending row that `memory-ingest`'s `append-items` operation targets going forward. Do this in both modes: even in full mode, the pass covers (at least) everything the open row tracked, so it's safe to close.
10. Report a summary of what changed: which mode ran, merges performed, references fixed, items removed.


## Rules

- Keep skill and page names lowercase with hyphens (e.g. `run-simulation`, `webster-method.md`).
- Write in clear, plain language.
- Good cross-references between skills and knowledge pages are what make the memory store navigable — that's exactly what steps 2 and 6 exist to protect.
- Only `memory-lint` invokes the `log` skill's `close-open` operation (step 9). `memory-ingest` only ever invokes `append-items` on an already-open row — never the other way around, or the "exactly one open row, always at the bottom" invariant breaks.
- Route every `log.md` read/write through the `log` skill rather than opening the file directly.