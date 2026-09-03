---
name: learn
description: Autonomously discover and accumulate skills and knowledge in the SUMO traffic simulation environment. Use when user asks to start learning.
---

## Purpose

Run a learning loop that generates novel traffic simulation tasks, finds methods to accomplish them, and distills the results into procedural memory (skills) and semantic memory (knowledge pages) — building up capability over successive iterations rather than in a single pass.


## Steps

1. On receiving the user's instruction to begin, load the `memory-lint` and `infer` **skills**, then start the learning loop.
2. Invoke the  `memory-lint` **skill** in "incremental" mode (it checks the threshold and only lints if enough new material has accumulated).
3. Invoke `curriculum-agent` **agent** in the foreground (`run_in_background: false`) to propose the next novel task — step 4 needs that task immediately, and this loop may be running non-interactively, where a backgrounded agent's completion notification never gets looped back into this skill's reasoning.
4. Invoke the `infer` **skill** on that task, following its own process to produce an answer (which, per `infer`'s own steps, may already result in new or updated skills/knowledge along the way);
5. If the user has explicitly asked to stop, exit the loop and check the `log.md` for the procedural and semantic memory updates, then return learning progress updates (e.g. skills and knowledge pages added or updated this session). Otherwise, by default, return to step 2. Pause after 10 consecutive iterations with no memory changes, and ask the user for instructions.
