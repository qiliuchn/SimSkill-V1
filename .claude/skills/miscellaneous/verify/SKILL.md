---
name: verify
description: Independently verify whether a traffic simulation task was actually accomplished, by inspecting the episodic memory folder rather than trusting any self-reported success.
---

## Purpose

Task-running sessions self-report their own success — whether via `action-agent`'s `success` field, `critic-agent`'s verdict, or (under conditions with no SimSkill scaffolding at all) a plain-language claim with nothing checking it. Self-report is not evidence; it's a claim made by the same process that has every incentive (and, for weaker models, every tendency) to believe it already finished. This skill exists to independently ground-truth that claim from a cold start, with no memory of and no context from the run being checked.

## Input

Whoever invokes this must supply:
- **Task ID** - the ID of the task run to verify.
- **The original task text**, verbatim — the actual spec to check against. Don't rely on a `summary.md`'s `task` frontmatter field for this if you can get it from the source instead; that field may not exist (see below).
- **The episodic memory record location ("episodic path")** — the task run record saved in `episodic-memory/` directory.
- **The location of the verification result file** — the file to write to.


## Steps

1. **If no episodic memory record exists at all, that is itself a finding, not a dead end**: directly go to step 5.
2. Find `summary.md` file in the episodic memory record for instructions on how to reproduce the task. If no summary exist, check whether there is a `attempts/` folder within the episodic memory record.
3. Try re-run scripts or the simulation itself rather than trusting the summary report. Form your own success/failure judgment from this alone.
4. Write the output file (see below for formatting).


## Principles

When checking whether a task was accomplished, follow these principles:
1. **Can you reproduce the task?** Are the instructions in `summary.md` sufficient to reproduce the task?
2. **Check the claim against the evidence.** Does the reported result (script output, simulation metrics, file paths) actually satisfy what the task asked for? If scripts or output files are referenced, inspect them rather than trusting the summary alone.
3. **Check for silent failure.** A script that ran without crashing isn't the same as a script that produced a correct result — watch for empty or trivially-wrong output (e.g. an empty tripinfo file, zero vehicles simulated when the task needed traffic, a route file with unrouted trips, obvious SUMO warnings/errors in stderr that were reported as success anyway).
4. **Check scope, not just execution.** If the task had multiple parts, confirm all of them were addressed — a technically-successful run that only covers part of the ask is not a full success.
5. **If it failed, be specific about why.** Point to the actual failure — a wrong parameter, a missing prerequisite step, a misread requirement, a tool error — rather than a generic "did not complete." Your critique should be specific enough that `action-agent` could act on it in a retry.


## Output

Write to the location of the verification result file given in your prompt. 
The file must have the following JSON structure:
```json
{
    "task_id": "<as supplied>",
    "episodic_path": "<as supplied>",
    "episodic_record_found": true,
    "self_reported_success": true,
    "critique": "<what was actually checked, and any caveats>",
    "verified_success": true,
    "agreement": true
}
```

If verification shows task wasn't accomplished:
```json
{
    "task_id": "<as supplied>",
    "episodic_path": "<as supplied>",
    "episodic_record_found": true,
    "self_reported_success": true,
    "critique": "<what was actually checked, and why it fails>",
    "verified_success": false,
    "agreement": false
}
```

If episodic record does not exist:
```json
{
    "task_id": "<as supplied>",
    "episodic_path": "<as supplied>",
    "episodic_record_found": false,
    "self_reported_success": null,   
    "critique": "No episodic record found.",
    "verified_success": null,
    "agreement": null
}
```
- `self_reported_success`: whatever the run itself claimed (from `summary.md`), or `null` if there was nothing to read; true/false.
- `critique`: a field be specific enough to explain what you have checked, and the reason for your final verdict.
- `verified_success`: your independent judgment whether the task is accomplished, formed before reading the self-report; true/false.
- `agreement`: whether your judgement agrees with self-verification in the `summary.md`; namely, `verified_success == self_reported_success`, or `null` if `self_reported_success` is `null`.

Note: you are allowed to add other fields to the JSON output (say more details on the checking process and results) if needed; the above is just the minimum required.
