---
name: log
description: Update log.md via a Python script, so the file content does not enter the LLM context. Use when user asks to update the log.
---

## Purpose

`log.md` records every procedural-memory and semantic-memory change plus lint-run history. As it grows, loading it into context becomes increasingly expensive. This skill offloads all `log.md` read/write operations to `scripts/log_manager.py` (bundled alongside this skill), keeping the file content out of the model context.

Other skills (`memory-ingest`, `memory-lint`) and the `learn` loop invoke this skill to perform specific log operations. The skill maps the requested operation to a script invocation, runs it, and returns structured output to the caller.


## Steps

1. **Determine the operation and its arguments** from the caller's request. Supported operations:

   | Operation | Purpose | Used by |
   |---|---|---|
   | `get-open-count` | Print the number of items in the open row's `New Items Reviewed` | `memory-lint` — decide whether to lint |
   | `get-open-items` | Print item names from the open row, one per line | reporting / inspection |
   | `get-open-row-info` | Print open-row data as JSON `{count, items}` | `learn` summary / reporting |
   | `append-items <name>...` | Append one or more item names to the open row of "Lint Runs Record" table | `memory-ingest`|
   | `close-open --timestamp <ts> [--findings <f>] [--actions <a>]` | Close the current open row of "Lint Runs Record" table and create a fresh one | `memory-lint`|
   | `add-procedural-row --timestamp <ts> --item <n> --operation <op> --change <desc>` | Add a row to the "Procedural Memory Updates" table | `memory-ingest`, `memory-lint` |
   | `add-semantic-row --timestamp <ts> --item <n> --operation <op> --change <desc>` | Add a row to the "Semantic Memory Updates" table | `memory-ingest`, `memory-lint` |
   | `count-rows` | Print row counts for all three tables as JSON | reporting |

2. **Run the Python script** via Bash. The path below is relative to this skill's own directory (the directory containing this `SKILL.md`) — resolve it against that directory, not the caller's current working directory:
   ```
   python3 scripts/log_manager.py <operation> [arguments]
   ```
   The script locates the project root itself (by walking up from its own file location to find `CLAUDE.md`), so it works correctly regardless of the caller's working directory. It handles all parsing and writes directly to `log.md`. The Bash tool's output is the script's stdout.

3. **Return the result** to the caller:
   - For `get-open-count`, return the integer count.
   - For `get-open-items`, return the list of item names.
   - For `get-open-row-info` / `count-rows`, return the parsed JSON object.
   - For all other operations, confirm success from the script's output message.
