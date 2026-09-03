---
name: memory-ingest
description: Ingest a completed traffic simulation task experience to generate or update a skill and/or knowledge page. Use when user asks to ingest new traffic simulation task experience or resources.
---

## Purpose

Given a task experience already judged valuable (by whatever invoked this skill), distill it into a new or updated skill in procedural memory and/or a new or updated knowledge page in semantic memory — so future tasks benefit from what was just learned.


## Steps

1. Read the task description, `action-agent`'s output, and `critic-agent`'s feedback.
2. Assess what's actually novel and reusable here: a new skill, an update to an existing skill, a new knowledge page, an update to an existing knowledge page, some combination, or none of the above. Note that if the simulation experience shows that existing skills have errors or drawbacks, you can also update those skills. If none of the above, skip all remaining steps.
3. **For a skill-level takeaway:** search procedural memory for a similar existing skill.
   - If none exists, invoke the `skill-creator` skill to create a new skill and store it in procedural memory. It is good practice to leverage existing skills and knowledge to develop new skills, building more complex capabilities by composing simpler ones rather than starting from scratch each time.
   - If a similar skill exists, merge the new method into it (e.g. a new option, a corrected gotcha, a broader case it now handles) rather than creating a near-duplicate.
4. **For a knowledge-level takeaway:** if there's new understanding about SUMO/simulation that would help future tasks, check semantic memory for a similar existing page.
   - If nothing similar exists, create a new page following the knowledge page format defined in `CLAUDE.md`.
   - If a similar page exists, update it in place instead (revise content, update `last_updated`, extend `sources`/`related_pages`/`related_skills` as needed) rather than creating a near-duplicate.
5. For any new or updated knowledge page, add `[[page-name]]` links to connect it with related pages, and update `semantic-memory/index.md` with the new page and a one-line description (or revise the existing entry, if updated).
6. Invoke the `log` skill to record what changed, without reading `log.md` yourself:
   - For every skill created or updated in step 3, run the `log` skill's `add-procedural-row` operation (timestamp, item name, `created`/`updated`, a one-line description of the change) to update the "Procedural Memory Updates" table.
   - For every knowledge page created or updated in step 4, run the `log` skill's `add-semantic-row` operation likewise to update the "Semantic Memory Updates" table.
   - Then run the `log` skill's `append-items` operation, passing the name of every item just logged. This appends them to the open `Lint Runs Record` row, which is what lets `memory-lint`'s step 0 see how much has accumulated since the last pass — skipping it silently breaks that check. If one task produces multiple changes (e.g. a skill update and a new knowledge page), pass every item name in the same `append-items` call.
   - Never invoke the `log` skill's `close-open` operation here — closing the open row and opening the next one is `memory-lint`'s job, not this skill's.


## Rules

- Keep skill and knowledge page filenames lowercase with hyphens (e.g. `run-simulation`, `webster-method.md`).
- Write in clear, plain language.
- Good cross-references between skills and knowledge pages are what make the memory store navigable — don't skip step 5.
- Always keep `semantic-memory/index.md` in sync with whatever changed, and route every `log.md` read/write through the `log` skill rather than opening the file directly.
