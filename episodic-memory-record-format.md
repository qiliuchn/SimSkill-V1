# Episodic Memory Record Format

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