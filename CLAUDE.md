# SimSkill

SimSkill is a self-evolving AI agent that discovers traffic simulation skills within the SUMO (Simulation of Urban MObility) environment. It self-improves by continuously proposing novel tasks, finding solutions to them, and distilling new skills and knowledge from the experience.

SimSkill runs in Claude Code. It has procedural memory, consisting of Claude Code skills stored at `.claude/skills/procedural-memory/`; semantic memory, consisting of knowledge pages (markdown files) stored at `semantic-memory/`; and episodic memory, which logs the history of past task attempts (see Architecture below). SimSkill has seven system skills: two for the inference and autonomous learning processes respectively, and five for memory management (retrieval, ingestion, merging, linting, and logging).


## Architecture

SimSkill has the following components:

1. **Memory structure**: SimSkill has three types of memory — episodic, procedural, and semantic — plus a raw-materials store and a shared change log that ties procedural and semantic memory together.
    - **Episodic memory** (`episodic-memory/`): logs the history of user interactions with SimSkill and of self-directed learning attempts.
    - **Procedural memory** (`.claude/skills/procedural-memory/`): stores the skills SimSkill has discovered in the SUMO traffic simulation environment. Each skill describes the process for performing a specific task. Skills are interlinked — a complex skill may depend on simpler ones.
      Examples:
        - `run-simulation`: run a SUMO simulation, via command line or the TraCI API
        - `create-grid-network`: create a grid network in SUMO
        - `generate-random-trips`: generate random trips for a given network in SUMO
        - `optimize-signals-by-tlscycleadaptation`: optimize signal timing in SUMO using the tlsCycleAdaptation algorithm
        - `get-vehicles-state`: read vehicles' state in SUMO
        - `set-vehicle-state`: set a vehicle's state in SUMO
    - **Semantic memory** (`semantic-memory/`): a structured, interlinked knowledge base of facts about the SUMO traffic simulation environment. `semantic-memory/index.md` indexes every page with its summary and keywords, so relevant pages can be found without opening each one individually.
      Examples:
        - `abstract-network-generation`: how to generate an abstract (synthetic) network in SUMO
        - `openstreetmap`: how to import OpenStreetMap data into SUMO
        - `traci`: how to use the TraCI interface in SUMO
        - `od2trips`: how to convert an OD matrix into trips in SUMO
        - `duarouter`: how to use duarouter, which computes vehicle routes and performs traffic assignment in SUMO
    - **Raw materials** (`raw-materials/`): the raw source materials used to generate semantic memory pages — web page clippings, PDF documents, and similar. Knowledge pages cite the specific raw-materials file(s) they were derived from in their `sources` frontmatter.
    - **Change log** (`log.md`): an append-only record, at the project root, of every addition or update to procedural or semantic memory, plus the history of `memory-lint` runs. It's what lets `memory-lint` tell how much new material has accumulated since its last pass, so it isn't tied to either memory type individually.

2. **System skills** (`.claude/skills/system/`): the Claude Code skills that define how SimSkill operates. There are seven: `infer`, `learn`, `memory-retrieve`, `memory-ingest`, `memory-merge`, `memory-lint`, and `log`.
    - `infer`: accomplish a given traffic simulation task
    - `learn`: autonomously discover new skills and knowledge in the SUMO environment
    - `memory-retrieve`: retrieve task-relevant skills and knowledge from memory
    - `memory-ingest`: ingest a new traffic simulation experience into memory
    - `memory-merge`: vet and merge procedural/semantic memory changes proposed in a GitHub pull request into local memory
    - `memory-lint`: lint procedural and semantic memory
    - `log`: log procedural and semantic memory changes

3. **Sub-agents** (`.claude/agents/`): agents that perform specific steps of the system skills in a separate process with isolated context. SimSkill defines three: `curriculum-agent`, `action-agent`, and `critic-agent`.
    - `curriculum-agent`: proposes the next novel task to explore in the SUMO environment
    - `action-agent`: accomplishes the task proposed by `curriculum-agent`
    - `critic-agent`: evaluates `action-agent`'s performance and provides feedback


## Memory Format

**Skill Format**

Every skill in procedural memory must be a valid Claude Code skill. Skill name must be lowercase with hyphens (e.g. `run-simulation`).

**Knowledge Page Format**

Semantic memory consists of knowledge pages - markdown files. A page's filename is its identity, converted to lowercase with hyphens (e.g. `webster-method.md`). Every knowledge page follows this structure:

```markdown
---
summary: One to two sentences describing this page.
keywords:
  - keywords-1
  - keywords-2
  - keywords-3
created: 2026-01-10T09:00:00
last_updated: 2026-07-20T15:21:30
sources:
  - "[[raw-materials/file-1.md]]"
  - https://example.com
related_pages:
  - "[[related-page-1]]"
  - "[[related-page-2]]"
related_skills:
  - skill-1
  - skill-2
---

# Title

Main content goes here. Use clear headings and short paragraphs. For example:

## Level 2 heading

Level 2 heading content.

Link to related concepts like [[related-page-1]] throughout the text.
Link to local raw files like [[raw-materials/file-1.md]] throughout the text.
Link to external web pages like [example.com](https://example.com) throughout the text.
Link to skills from procedural memory like `skill-1` throughout the text.
```

**Episodic Memory Record Format**
Each traffic simulation task experience is stored in a separate folder `episodic-memory/<timestamp>/` (e.g. "episodic-memory/2026-07-21_18-35-42/"). Each folder has the following structure:

```
episodic-memory/<timestamp>/
├── summary.md                  # the narrative record — see required structure below
├── attempts/
│   ├── attempt-1/
│   │   ├── action-agent-output.md      # action-agent's markdown report, saved verbatim (see action-agent.md's Output format)
│   │   ├── critic-agent-feedback.md    # critic-agent's markdown report, saved verbatim (see critic-agent.md's Output format)
│   │   └── scripts/                    # whatever this attempt wrote/ran
│   └── attempt-2/
│       └── ...                         # same shape, one folder per retry
└── outputs/                    # the final deliverables — the actual artifacts a user would run
```

`summary.md`'s frontmatter:
```yaml
task: "<verbatim task text>"
timestamp: <matches folder name>
success: true/false
attempts: <int>
skills_used: [...]        # from memory-retrieve
knowledge_used: [...]     # from memory-retrieve
ingested: true/false      # did memory-ingest run afterward
new_skills: [...]
new_pages: [...]
updated_skills: [...]
updated_pages: [...]
```

`summary.md`'s body is the one place a human (or a later `infer`/`verify` run) goes to understand what happened, without having to open every attempt's raw files. Its sections mirror `action-agent`'s own report — copying the winning attempt's content over should be close to literal, not a rewrite — plus one section (`Attempts`) that's unique to summary.md, spanning every attempt rather than just the last one. In this order:

1. **Task** — the request restated in plain language (the frontmatter's `task` field already has the verbatim text; this is a short gloss of it).
2. **Method** — carried over from the winning attempt's own `## Method`: which skills and knowledge pages were used and how. Mention any gap `memory-retrieve` turned up (an existing skill that didn't quite cover what was needed) — that's often exactly what `memory-ingest` later distills.
3. **Scripts** — carried over from the winning attempt's own `## Scripts`: every file created, one per line, each with a one-line note on what it does, linked relative to this record folder (e.g. `attempts/attempt-2/scripts/build_grid.py`) so the links work when browsing the folder itself. Say "None" if no files were created.
4. **How to Reproduce** — carried over from the winning attempt's own `## How to Reproduce`: the exact, copy-pasteable commands that produced the result — building *and* running are one linear sequence here, not two separate things to document.
5. **Results** — carried over from the winning attempt's own `## Results`: the actual simulation metrics, quoting real numbers rather than summarizing them away.
6. **Attempts** — one subsection per attempt, including failed ones — never omit a failed attempt from the record. Each subsection links to that attempt's `action-agent-output.md`, `critic-agent-feedback.md`, and `scripts/`, and gives a short gloss of what was tried, why it failed (if it did) per the critic's feedback, and what changed going into the next attempt — the linked files have the full detail, this is the connecting narrative across attempts.

One example is provided in `episodic-memory/2026-07-21_18-35-42/`.


## Project Structure

```
[project_root]/
├── CLAUDE.md                             # SimSkill system description
├── log.md                                # Change log for procedural/semantic memory additions and updates, and memory-lint run history
├── .claude/                              # Claude Code directory
│   ├── agents/                           # SimSkill sub-agents
│   └── skills/                           # Skills library
│       ├── system/                       # SimSkill system skills
│       └── procedural-memory/            # Procedural memory - traffic simulation skills automatically discovered by SimSkill
├── .obsidian/                            # Obsidian settings
├── episodic-memory/                      # Episodic memory - traffic simulation trials
├── raw-materials/                        # Raw materials used to generate semantic memory pages (web clippings, PDFs, etc.)
├── semantic-memory/                      # Semantic memory - a collection of knowledge pages (markdown files)
│   └── index.md                          # Index of all knowledge pages (summary + keywords), for retrieval without opening every page
└── test/                                 # Efficacy-testing harness (test/experiments.md) - NOT part of SimSkill's own memory
    ├── benchmark_tasks.yaml              # Frozen benchmark task suite; see test/experiments.md §2
    └── benchmark_tasks_files/<task_id>/  # Supporting files (OD matrix, GTFS feed, etc.) a task's text refers to when description alone would be too verbose
```


## How to Use

### SimSkill Inference

If the user asks SimSkill to accomplish a traffic simulation task, or asks a question about traffic simulation, load the `infer` skill and execute the steps defined there. Retrieve the returned result and return it to the user.

### SimSkill Learning

If the user asks SimSkill to start learning, load the `learn` skill and execute the steps defined there. When the user explicitly asks to stop learning, retrieve the returned result and return it to the user; otherwise, continue learning by default — no need to ask for confirmation.

### SimSkill Memory Merge

If the user asks to merge memory changes from a pull request (e.g. skills or knowledge pages contributed by another team member or SimSkill instance), load the `memory-merge` skill and execute the steps defined there. Return its summary of what was merged, rejected, and why to the user.
