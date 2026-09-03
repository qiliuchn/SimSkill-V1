---
name: memory-retrieve
description: Retrieve relevant skills from procedural memory and knowledge pages from semantic memory. Use when user asks to retrieve relevant skills and knowledge pages.
---

## Purpose

Given a task, retrieve the skills and knowledge pages relevant to it from procedural memory and semantic memory, so `action-agent` has the right context without loading the entire memory store.


## Steps

1. Search procedural memory （`.claude/skills/procedural-memory/`） for skills most relevant to the task (e.g. by matching the task against each skill's `description` frontmatter).
2. Look up `semantic-memory/index.md` and identify the pages relevant to the task (matching against each page's `summary` and `keywords` frontmatter).
3. If the number of skills and knowledge pages combined is more than 10, then retain only the top 10 most relevant skills and knowledge pages.
4. Report all retrieved skills and knowledge page entries together as the task's context. Don't load the full memory store up front — lazy-load individual skill or page details only when actually needed.
