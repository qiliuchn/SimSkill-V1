---
name: infer
description: Infer the answer to a given traffic simulation task. Use when user asks to finish a traffic simulation task or answer a question about traffic simulation.
---

## Purpose

Accomplish a given traffic simulation task: find a method (Python/bash scripts, existing skills, or a combination), execute it, and return both the method and the result. `infer` process contains a loop in which `action-agent` can be invoked multiple times to correct major design problems until the task is genuinely completed or max attempts reached.


## Modes

`infer` runs in one of two modes. They are identical except for whether step 7 runs.

- **Normal mode (default)**: used for real tasks. The experience is ingested into memory via `memory-ingest`, so future tasks can benefit from what was learned.
- **Test mode**: used when the user is testing, debugging, or dry-running `infer` itself (e.g. evaluating a skill change) and the resulting experience should not pollute procedural/semantic memory. Step 7 is skipped. Only enter test mode when the user explicitly asks for it (e.g. "infer in test mode", "don't ingest this one"). Test mode changes nothing else — step 6 (saving to episodic memory) is not step 7, is not about procedural/semantic memory, and always runs in both modes.


## Steps
1. Load the `memory-retrieve` **skill** and `memory-ingest` **skill**.
2. Use the `memory-retrieve` **skill** to retrieve relevant skills from procedural memory and relevant knowledge page entries from semantic memory.
3. Invoke `action-agent` **agent** in the foreground (`run_in_background: false`) — step 4 needs its result immediately, and this process may be running non-interactively (`claude -p`), where a backgrounded agent's completion notification never gets looped back into this skill's reasoning. Pass it the task plus the retrieved skills and knowledge pages as context and the `critic-agent`'s ALL feedback history if applicable.
4. Invoke `critic-agent` **agent**, also in the foreground (same reason), to evaluate `action-agent`'s response.
5. If `critic-agent` reports the task complete, or the maximum number of attempts (default: 3) has been reached, proceed to step 6. Otherwise, add the critic's feedback to `action-agent`'s context and return to step 3.
6. Save this simulation experience to episodic memory following the episodic memory record format defined in `episodic-memory-record-format.md`.
7. **Normal mode only**: invoke `memory-ingest` **skill** to ingest the simulation experience. Skip this step in test mode.

Note: `infer` skill's process has an execution loop which is intended to correct major design issues until the task is genuinely completed. `action-agent` also has an execution loop which is intended to correct minor script errors until the simulation runs successfully. Hence in `infer` skill's process, feedbacks are accumulated and passed to `action-agent` to avoid making the same design mistakes again. However, the script debugging history from `action-agent` execution loop is not kept in `infer` skill's iterations.

## Rules

- `action-agent`'s reply (step 3) is an intermediate result for later evaluation — NOT your final answer. However complete and polished it reads (it's written as a finished report), do NOT stop there.
- Before producing any response to the user, verify all of the following actually happened: `critic-agent` was invoked and returned a verdict (step 4); the task was judged complete or the attempt limit was reached (step 5); the episodic memory record was actually written to disk via the `Write` tool (step 6); and, in normal mode, `memory-ingest` ran (step 7). If any of these hasn't happened yet, you are not done — continue the process instead of responding.
- Steps 3-7 are *your* job, not something to hand off. Never invoke `action-agent` with the task framed as "run the infer workflow," "handle this end-to-end," or similar — give it only the concrete simulation task itself (plus context per step 3). `action-agent` has no knowledge of `critic-agent`, retry loops, memory modes, or the episodic memory record format; asking it to do more than the concrete task will skip the rest of this process silently.
