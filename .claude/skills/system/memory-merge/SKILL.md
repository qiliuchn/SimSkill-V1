---
name: memory-merge
description: Merge procedural and semantic memory changes proposed in a GitHub pull request into local memory, vetting each item before accepting it. Use when the user asks to merge memory from a pull request, review a memory PR, or fold in another team member's/instance's skills and knowledge.
---

## Purpose

Other SimSkill instances or team members may propose new or updated skills and knowledge pages via a GitHub pull request. Unlike `memory-ingest` (which distills a single experience this instance just had), this skill vets *externally proposed* memory changes before folding them in: new items get the same "does it actually work" bar as a fresh ingestion, and updates to existing items get checked for whether they'd break anything local that depends on them. Conservatism is the point — a rejected improvement costs little, a silently broken dependency costs a lot.

This skill only ever edits local memory files. It never merges, closes, or pushes anything on GitHub — that's a separate, user-confirmed step once the local result looks right.


## Steps

### 0. Identify the pull request

- If the invocation names a PR number or URL, use it directly.
- Otherwise, run `gh pr list --json number,title,files` and shortlist PRs that touch `.claude/skills/procedural-memory/` or `semantic-memory/`. If exactly one matches, proceed with it. If several match or none do, ask the user which PR to merge rather than guessing.

### 1. Fetch the PR's proposed content read-only

- Fetch the PR's head commit without checking it out or touching the working tree: `git fetch origin pull/<n>/head:pr-<n>-tmp`.
- Diff it against local main, scoped to memory paths: `git diff main pr-<n>-tmp -- .claude/skills/procedural-memory semantic-memory`. Read full file contents with `git show pr-<n>-tmp:<path>` as needed (diffs alone can be misleading for reordered or long files).
- If the PR also touches files outside those two paths (e.g. system skills, agents, `CLAUDE.md`), do not apply those changes as part of this skill — flag them to the user separately.
- Delete the temporary ref (`git branch -D pr-<n>-tmp`) once you've read what you need, whether or not the merge succeeds.

### 2. Classify every in-scope changed file

For each changed path, classify it as: new skill, updated skill, new knowledge page, updated knowledge page, or deletion.

### New items

3. **For each newly added skill:**
   - Search procedural memory for a similar existing skill (same standard as `memory-ingest` step 3 and `memory-lint` step 1). If a near-duplicate already exists locally, merge the new one into it instead of adding a parallel copy.
   - Verify the skill actually works before accepting it — invoke `action-agent` **in the foreground** (`run_in_background: false`; the pass/fail decision right after needs its result immediately) on a representative task that exercises it, or run its bundled scripts directly. A skill that merely looks plausible is not enough; this is the same bar `memory-lint` step 3 applies to newly composed skills.
   - If it passes, write the skill's files into `.claude/skills/procedural-memory/` locally. If it fails, reject it and note why.

4. **For each newly added knowledge page:** check semantic memory for a similar existing page (same standard as `memory-ingest` step 4). If none exists, add the page; if one exists, merge the new material into it rather than duplicating.

5. For every new skill/page accepted in steps 3-4, add cross-references (`[[page-name]]` links, `related_pages`, `related_skills`) connecting it to relevant existing items — don't let it land as an orphan — and update `semantic-memory/index.md`.

### Updated items

6. **For each skill or page the PR modifies** (not newly added):
   - Find local skills/pages that depend on it: other skills that invoke it or list it under `related_skills`, other pages that link to it via `[[...]]` or list it under `related_pages`.
   - Judge whether the PR's change is compatible with those dependents — does it preserve the interface/behavior they rely on (same script arguments, same expected inputs/outputs, same meaning), or only extend or fix it?
   - If compatible, apply the update locally.
   - If incompatible, or if you can't tell either way, **reject the update** and leave the local version untouched. Be conservative: missing an improvement is recoverable, silently breaking a depended-upon skill or page is not.

7. **For any deletions the PR proposes:** apply the same check as step 6 — only delete the local skill/page if nothing local still depends on it; otherwise reject the deletion and note why.

### Sync and record

8. Update `semantic-memory/index.md` to match whatever was actually accepted in steps 3-7.
9. Invoke the `log` skill to record only the changes actually applied, without reading `log.md` yourself:
   - Run `add-procedural-row` / `add-semantic-row` for every skill/page created, updated, or deleted in steps 3-7.
   - Run `append-items`, passing the name of every item just logged, so it lands in the open `Lint Runs Record` row.
   - Never invoke `close-open` here — that's `memory-lint`'s job, same rule as `memory-ingest`.
10. Report a summary to the user: items merged (new/updated), items rejected and why, deletions applied or refused, and cross-references added. Do not run `gh pr merge`, close the PR, or push anything — surface the summary and let the user decide when to act on the PR itself.


## Rules

- Scope is strictly `.claude/skills/procedural-memory/`, `semantic-memory/` (plus `semantic-memory/index.md` and `log.md` via the `log` skill). Never silently apply a PR's changes to files outside this scope.
- A new skill is accepted only once verified to actually work — not merely reviewed for plausibility.
- On updates and deletions, when compatibility with local dependents can't be confirmed, reject and say so rather than guess.
- Keep skill and page filenames lowercase with hyphens.
- Good cross-references are what make the memory store navigable — don't skip step 5.
- Route every `log.md` read/write through the `log` skill rather than opening the file directly.
- Never merge, close, or push the pull request itself. Fetching it read-only (step 1) is fine; acting on GitHub is the user's call.
