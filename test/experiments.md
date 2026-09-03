# Experiments

We test the central claim of SimSkill: that accumulating procedural memory (skills) and semantic memory (knowledge pages) makes the agent measurably better at traffic-simulation tasks over time, compared to an agent with no such memory.


## 1. Research Questions

<!--Experiment #1-->
1. **(Accuracy Test)** Does <i>SimSkill (with inference framework + skills + knowledge)</i> outperform <i>Claude Code with only the inference framework (no procedural/semantic memory)</i> and <i>vanilla Claude Code</i> on the same tasks?
2. **(LLM Test)** Does the effect hold across different backbone LLMs, or is it specific to one model family/size? Does it improve performance more on less-capable LLMs, with diminishing gains for SOTA models?
3. **(Memory Ablation)** How much of the gain comes from procedural memory alone, semantic memory alone, or their combination? Is there a synergy (super-additive effect) or redundancy (sub-additive effect)?
4. **(Efficiency Test)** Even when success rate is similar, does memory reduce cost — fewer `action-agent` retry loops, less exploration, fewer tokens, less wall-clock time? (Answering this fairly is not just "add a cost column" — see §3.2 for why prefill-vs-generation, tokenizer differences across LLMs, and open-ended agent run length all need to be controlled for before cost numbers are comparable.)
5. **(Generalization Test)** Does memory built from one set of tasks transfer to novel tasks that require *combining* skills in ways not seen during learning (compositional generalization), or does it only help on near-duplicates of past tasks?


## 2. Task Benchmark

We constructed two frozen benchmarks, each comprising 40 standalone tasks. Benchmark V1 (`test/benchmark_tasks_v1.yaml`) spans ten capability areas: network generation, demand generation, signal control and optimization, TraCI-based closed-loop control, output analysis and visualization, surrogate safety assessment, emissions and energy analysis, multimodal transit, calibration, and cross-category integration. Its 40 tasks are evenly distributed across four difficulty tiers, with 10 tasks per tier; higher tiers require progressively more complex reasoning and stronger generalization.

Benchmark V2 (`test/benchmark_tasks_v2.yaml`) concentrates on substantially more difficult engineering studies. It contains 40 tasks across network design, demand inference, signal control, freeway operations, multimodal transit, safety and human factors, environment and energy, freight and curb operations, planning and policy equity, and simulation methodology.

- Store the suite at `test/benchmark_tasks_v<#>.yaml`, each entry with: task text, category, difficulty tier.
- **Task text is self-contained and concrete**, not just a topic area: a task that says "optimize a signal plan from measured saturation flow" without saying which intersection or what demand isn't reproducible — two solvers would each invent their own scenario and there'd be no shared, well-posed problem to actually judge. Prefer specifying by description (add the missing geometry/demand/target numbers directly into `task`) over adding a file. Every task's `task` text is the *only* context `action-agent` receives.
- **Supporting files, when description would be too verbose**: some data (an OD matrix, detector counts, a GTFS feed) is too unwieldy to inline as prose. For these, store the files at `test/benchmark_tasks_files/<task_id>/` and list them under that task's optional `input_files:` field in `benchmark_tasks.yaml` (paths relative to repo root). This works with the worktree-based harness for free — `git worktree add` checks out the whole repo, so `test/benchmark_tasks_files/<task_id>/` is present in every experiment worktree automatically, and `claude -p` runs with the worktree as its cwd, so a path like `test/benchmark_tasks_files/DG-T2/od_matrix.csv` in the task text resolves correctly. Files should be **raw, tool-agnostic data** (plain CSV, not a pre-formatted SUMO input) — converting them into whatever a specific SUMO tool expects is part of what the task is testing, not something to do for the solver in advance. Don't create an `input_files:` entry or folder for tasks that need no files.
- **Categories**: network generation, demand generation, signal control/optimization, TraCI closed-loop control, output analysis/visualization, safety/SSM, emissions/energy, multimodal/transit, calibration.
- **Contamination control**: benchmark tasks must never be passed through `memory-ingest` during evaluation runs. Clone memory into the worktree, and run `infer` in "test mode" — i.e. execute `infer`'s steps 1–5 as normal but skip steps 6–7 (episodic-memory write and `memory-ingest`), so no benchmark task ever gets folded back into the memory being evaluated.


## 3. Evaluation

### 3.1. Metrics

Log every run as structured JSON (extend the episodic-memory record shape) under `test/results/<run_id>.json` so all runs are analyzable in one table.

1. **Primary — task success**: `critic-agent`'s pass/fail verdict (binary), plus its verdict tier if it distinguishes ACCEPT / ACCEPT WITH CAVEATS / REJECT (treat caveats as partial credit or a separate ordinal outcome, don't collapse it into binary).
2. **Cost**: wall-clock time (agent-side vs. simulation-side, separately) and token usage per run, broken into input/output/cache-read/cache-write — memory is only a net win if the retrieval overhead doesn't outweigh the saved exploration. See §3.2 for why these have to be logged as separate fields, converted to dollar cost, and read as success-at-budget curves rather than a single averaged number — a naive total-tokens or total-time comparison is not a fair one here.
3. **Wall clock time**: wall-clock time for `infer` to complete a single run.
5. **Score - Solution quality beyond pass/fail**: decomposed each task into weighted requirements and assigned a completion score in $[0,1]$, where zero denotes no verifiable task-specific result and one denotes complete, correct, evidenced, and reproducible completion. This continuous score captures substantial partial progress that a binary verdict necessarily discards.

### 3.2. Fair Comparison: Controlling for Compute Budget

"Measurably better" must not collapse into "given enough time and tokens, eventually gets there" — `infer`'s loop and Claude Code sessions in general are open-ended, so an uncontrolled comparison lets whichever condition is allowed to burn the most compute look best (or, just as misleadingly, makes memory look "more expensive" purely because the harness measured it in the least favorable way). This section defines the accounting rules every cost/time comparison in the experiments (§4) has to follow.

#### 3.2.1 Prefill vs. generation aren't the same currency

Memory conditions spend more input/prefill tokens up front (retrieved skill/page content is added to context) but trade that against fewer output tokens and fewer turns (less trial-and-error, fewer wrong first attempts, less deriving things from scratch). A single "total tokens" number nets these together even though they behave completely differently:

- **Input/prefill tokens** are cheap per-token and, critically, *cacheable*. Skill/page content is static within a session and repeats across same-category benchmark tasks, so under prompt caching a memory condition's real marginal input cost after the first task in a session is a small fraction of a cold read. A harness that spins up one fresh, cache-cold session per benchmark task (as §6's harness does by default, for run isolation) will systematically overstate memory's token cost relative to how SimSkill is actually used (long-lived `learn`/`infer` sessions that keep the cache warm). Report both a **cold-cache** number (matches the isolated-per-task harness) and a **warm-cache** number (batch several same-condition tasks into one session so the cache amortizes), so "memory costs more tokens" isn't measured only in its worst case.
- **Output tokens and turns** are expensive per-token and, more importantly, *serial* — each output token and each tool round-trip adds wall-clock latency in a way prefill mostly doesn't. This is exactly where memory is expected to pay for itself.

Log input, output, cache-read, and cache-write tokens as **separate** fields per run — don't pre-sum them into one "tokens used" number before analysis.


#### 3.2.2 Token consumption & dollar cost

We will report token consumption as well as dollar cost. Prefill and generation tokens will be logged separately (per §3.2.1). Dollar cost matters on its own, beyond just being a rollup of tokens: different LLMs (§4's Backbone LLMs list) use different tokenizers, so raw token counts aren't directly comparable across them — the same solution can tokenize to a different length on Claude vs. a third-party model. Converting every run's (input, output, cache-read, cache-write) counts to an actual dollar figure, using each provider's published per-token pricing at the time of the run, is what makes cross-LLM cost comparisons (RQ2) apples-to-apples. Record the price table/date used (pricing changes — see §7).


#### 3.2.3 Wall-clock time: separate agent time from simulation time

Wall-clock is the metric closest to what a user actually experiences — and the direct answer to "can it be solved in 30s / 60s / 120s" — but raw wall-clock conflates two things with very different meaning:
- **Agent-side time**: LLM latency plus tool-orchestration overhead — this is what memory should improve (fewer turns, less exploration).
- **SUMO execution time**: the simulation itself takes however long it takes regardless of which condition produced its config (a 10,000-vehicle multi-hour-horizon run costs the same wall-clock whether `full-ver` or `vanilla-cc` wrote it). This is workload-determined, not agent-determined, and is shared across conditions on a given task — it shouldn't drown out the agent-side signal or get credited/blamed to either condition.

Log both separately (sum of SUMO/`netconvert`/`duarouter`/etc. tool-call durations vs. everything else) so a task with a long simulation doesn't make an efficient agent look slow, and vice versa.

#### 3.2.4 Success-at-budget curves, not one endpoint number

Rather than reporting a single pass/fail per (condition, task) at whatever budget it happened to take, impose a **shared set of budget ceilings** — e.g. wall-clock {30s, 60s, 300s, 900s, 3600s, uncapped} and/or dollar cost {$0.10, $0.50, $2, $10, uncapped} — identical across every condition, and report the fraction of benchmark tasks solved *within* each ceiling. This produces a solved-rate-vs-budget curve per condition (the same idea as pass@k curves in code-generation benchmarks, or task-completion-vs-time-horizon curves used in agent-autonomy evaluations), and it's the fair version of the comparison: it distinguishes memory genuinely solving more tasks from memory only reaching the same eventual answer faster/cheaper, from — the failure mode to watch for — memory only looking better because it was given a larger budget than the alternative.

This doesn't require literally re-running at every ceiling: instrument the harness (§6) to timestamp and cost-stamp every tool call and every `infer`-loop iteration, then reconstruct "would this task already have been solved if cut off at budget B" retrospectively from one full-budget run's transcript (the final artifact's last-write timestamp/cost vs. the ceiling). Only re-run live when a condition is cut off mid-attempt in a way retrospective reconstruction can't resolve cleanly (e.g. a partially-written output file whose validity at that point is ambiguous).



## 4. Experiment Design

**Addresses Research Questions 1–5: accuracy test, LLM test, ablation, efficiency test, and generalization test.** We will test different (Version, Backbone LLM, Task) combinations, and output accuracy and efficiency metrics.

**Versions to test**
A 2×2 factorial over procedural (P) and semantic (S) memory, plus a true-vanilla control:

| Condition | SimSkill Infer Framework | Procedural memory | Semantic memory | What it isolates |
| --- | --- | --- | --- | --- |
| `full-ver` | ✓ | ✓ | ✓ | SimSkill as shipped |
| `proc-mem-ver` | ✓ | ✓ | ✗ | value of skills alone |
| `sem-mem-ver` | ✓ | ✗ | ✓ | value of knowledge alone |
| `infer-frame-only` | ✓ | ✗ | ✗ | SimSkill's own scaffolding (system skills, sub-agent loop, critic) with zero accumulated content — isolates the *architecture* from the *content* |
| `vanilla-cc` | ✗ | ✗ | ✗ | plain Claude Code: no `CLAUDE.md`, no system skills, no sub-agents, just the task prompt. This is the real "no SimSkill at all" baseline |

`vanilla-cc` matters as its own condition because SimSkill's `infer`/`action-agent`/`critic-agent` loop (retries, structured critique) could itself be worth something independent of accumulated content — without `infer-frame-only` sitting between `full-ver` and `vanilla-cc`, a `full-ver` vs `vanilla-cc` comparison alone would confound "has memory" with "has a critic/retry loop at all."

**Backbone LLMs**

Grid across a deliberately broad, cross-vendor spread of models — strong flagship models, cheaper/smaller models, and multiple vendors — so RQ2 (LLM Test) isn't confounded by idiosyncrasies of a single model family. Keep the sub-agent model pinned per run (`CLAUDE_CODE_SUBAGENT_MODEL`) so comparisons aren't confounded by orchestrator/sub-agent using different models across conditions. Given the size of this list, run the full 5-version × 8-LLM grid gradually per §8's phased rollout, following §7's cost-ceiling guidance rather than all at once.

The following LLMs will be tested:
- [DeepSeek v4 pro](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro)
- [Qwen 3.8 Max](https://qwen.ai/blog?id=qwen3.8)
- [GLM-5.2](https://huggingface.co/zai-org/GLM-5.2b)

**How to realize each condition**: use a disposable git worktree per run (`EnterWorktree`/plain `git worktree add`) so runs never share mutable state. For `proc-mem-ver`/`sem-mem-ver`/`infer-frame-only`, temporarily empty (not delete) `.claude/skills/procedural-memory/` and/or `semantic-memory/*.md` (keep `index.md` structure but empty its entries) in that worktree's checkout. For `vanilla-cc`, check out a worktree with `CLAUDE.md`, `.claude/skills/`, and `.claude/agents/` removed entirely, so Claude Code has no SimSkill instructions at all. Note: add worktree at `../` directory. All created worktrees during experiments will be placed within `../<repo-name>-experiments/` — the sibling of the repo root, named after it (e.g. a repo at `.../simskill` uses `.../simskill-experiments/`, a repo at `.../simskill-2` uses `.../simskill-2-experiments/`).


## 5. How to Run the Experiments

The infrastructure from §6 is built and lives under `test/harness/` (config: `conditions.yaml`, `models.yaml`, `price_table.yaml`; code: `memory_ops.py`, `cost_time.py`, `run_experiment.py`, `run_experiment_1.py`, `aggregate_results.py`) alongside `test/benchmark_tasks.yaml`. This section is the operator's guide to actually driving it — everything below is infrastructure usage, not a new experimental design decision.

### 5.1 One-time setup

Two config files ship with deliberate placeholders (§7 "Pricing/tokenizer drift" — these were left blank rather than guessed) that must be filled in before a run can reach an LLM other than native Claude:

- **`test/harness/models.yaml`**: `claude-opus-5` and `claude-haiku-4-5` need nothing (native Anthropic auth). Every `chatgpt-*`/`deepseek-*`/`qwen-*` entry needs its `"TODO"` `env` values filled in (`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`), matching the project README's documented pattern for a non-Anthropic model.
- **`test/harness/price_table.yaml`**: set `price_table_date` and each model's `input`/`output`/`cache_write`/`cache_read` rates. A rate left `null` makes `cost_usd` come back `null` for that model rather than silently `0` — fill in what you intend to actually price before trusting §3.2's cost numbers.

### 5.2 Running one (condition, model, task) cell

First copy the benchmark task you want to run into `test/benchmark_tasks.yaml`. 

Then run:
```bash
python test/harness/run_experiment_1.py --conditions proc-mem-ver\
    --models deepseek-v4-pro --verify-model claude-opus-5\
    --repeats 1 --keep-worktree --continue
```

`--conditions`: the conditions to test;
`--models`: the LLMs to test;
`--verify-model`: the LLM to use for verification;
`--repeats`: how many times to repeat each task;
`--keep-worktree`: keep the worktree after the run, so you can inspect it.
`--continue`: continue the last run, if any.

This command will run all (condition, model) combination pairs, in one worktree. And each worktree will run all tasks in `test/benchmark_tasks.yaml` in one go by invoking `run_experiment.py`. You can also run one (condition, model) combination and even one task manually by running:
```bash
python3 test/harness/run_experiment.py \
  --condition full-ver \
  --model deepseek-v4-pro \
  --task-id NG-T1
```

`--task-id NG-T1` runs one task; task id is any id from `test/benchmark_tasks.yaml`. 
`--task-ids NG-T1,NG-T2,NG-T3` runs those three tasks in a row, in one worktree.
`--all-tasks` runs every task in `test/benchmark_tasks.yaml`, in one worktree.
`--cache-mode` controls whether each task in a batch gets a brand-new Claude Code session or reuses/resumes one session across tasks — it's about Anthropic's prompt caching, not about SUMO or SimSkill's own memory system. It takes value `cold` or `warm`. The default is `cold`.
Every task gets its own fresh --session-id (a new random UUID, see run_experiment). Nothing is cached going in: the full CLAUDE.md, skill files, and semantic-memory pages the agent reads all get prefilled from scratch every single time. This is the worst case for token cost/latency, but it's what you get from running each task in isolation — which is also what makes per-task results independently reproducible for the benchmark.

This single call performs the whole per-cell pipeline: create a disposable git worktree → apply the condition's file manipulation (`memory_ops.py`) → write a per-worktree `.claude/settings.local.json` if the model needs env overrides → invoke `claude -p ... --output-format json` inside that worktree → read back whatever `infer` itself wrote to that worktree's own `episodic-memory/` (success, attempts, skills/knowledge used) → run the §3.2 cost/time instrumentation (`cost_time.py`) → write `test/results/<run_id>.json` → delete the worktree. 
The main repo is never modified by any of this (§2's contamination control).

Each time you run run_experiment.py, it creates exactly one git worktree at the start (create_worktree) and tears it down at the end (remove_worktree, unless --keep-worktree).


### 5.3 Result files

Check `test/save/` for the result files generated during the experiment.
- `experiment_tasks_deepseek_benchmark_v1_two_conditions.jsonl`: experiment results for `full-ver` and `vanilla-cc` conditions tested on Benchmark V1 using `deepseek-v4-pro` model.
- `experiment_tasks_deepseek_benchmark_v1_all_conditions.jsonl`: experiment results for all conditions tested on Benchmark V1 using `deepseek-v4-pro` model.
- `experiment_tasks_deepseek_benchmark_v2_two_conditions.jsonl`: experiment results for `full-ver` and `vanilla-cc` conditions tested on Benchmark V2 using `deepseek-v4-pro` model.
- `experiment_tasks_qwen_benchmark_v1_two_conditions.jsonl`: experiment results for `full-ver` and `vanilla-cc` conditions tested on Benchmark V1 using `qwen-3.7-max` model.
- `experiment_tasks_qwen_benchmark_v1_all_conditions.jsonl`: experiment results for all conditions tested on Benchmark V1 using `qwen-3.7-max` model.
- `experiment_tasks_qwen_benchmark_v2_two_conditions.jsonl`: experiment results for `full-ver` and `vanilla-cc` conditions tested on Benchmark V2 using `qwen-3.7-max` model.
- `experiment_tasks_glm_benchmark_v1_two_conditions.jsonl`: experiment results for `full-ver` and `vanilla-cc` conditions tested on Benchmark V1 using `glm-5.2` model.
- `experiment_tasks_glm_benchmark_v2_two_conditions.jsonl`: experiment results for `full-ver` and `vanilla-cc` conditions tested on Benchmark V2 using `glm-5.2` model.


### 5.4 Reading results

Loads result JSONs from the experiment-tasks log (a JSONL file written by run_experiment.py that records every (task, repeat) actually executed in a sweep), prints the summary table, and reports the pre-registered primary comparisons:
```bash
python3 test/harness/print_primary_comparisons.py
```
`--experiment-tasks test/experiment_tasks.jsonl`: Path to the JSONL log written by the sweep driver; each line records one (task, repeat) actually executed. |
`--conditions`: Comma-separated condition names to filter by (e.g. `full-ver,vanilla-cc`). |
`--models`: Comma-separated model keys to filter by (e.g. `claude-opus-5`). |
`--metric cost_usd` or `--metric wall_clock_total_s`: Metric for the budget axis of the success-at-budget plot.
`--budgets` | *(none)* | Comma-separated budget thresholds for the optional point-estimate table (e.g. `0.1,0.5,2,10`). The largest value is also the plot's exact x-axis maximum, and any trial that ran past it is dropped from the plot — a warning names how many. When omitted, the axis spans every trial executed, success or failure, plus 5%. |

To plot the score distributions, run:
```bash
python test/harness/print_score_distribution.py \
        --experiment-tasks /path/to/experiment_tasks.jsonl
```

Check the following files for output that we get from running the above command:
- `print_primary_comparisons_deepseek_benchmark_v1_usd_stdout_aug_27_1142.txt`: The stdout of `print_primary_comparisons.py` when experiment task file is `experiment_tasks_deepseek_benchmark_v1_all_conditions.jsonl` and metric is `cost_usd`, tested on Benchmark V1.
- `print_primary_comparisons_deepseek_benchmark_v1_wall_clock_total_s_stdout_aug_27_1142.txt`: The stdout of `print_primary_comparisons.py` when experiment task file is `experiment_tasks_deepseek_benchmark_v1_all_conditions.jsonl` and metric is `wall_clock_total_s`, tested on Benchmark V1.
- `print_primary_comparisons_deepseek_benchmark_v2_usd_stdout_aug_22_1000.txt`: The stdout of `print_primary_comparisons.py` when experiment task file is `experiment_tasks_deepseek_benchmark_v2_all_conditions.jsonl` and metric is `cost_usd`, tested on Benchmark V2.
- `print_primary_comparisons_deepseek_benchmark_v2_wall_clock_total_s_stdout_aug_22_1000.txt`: The stdout of `print_primary_comparisons.py` when experiment task file is `experiment_tasks_deepseek_benchmark_v2_all_conditions.jsonl` and metric is `wall_clock_total_s`, tested on Benchmark V2.
- `print_primary_comparisons_qwen_benchmark_v1_usd_stdout_aug_26_1937.txt`: The stdout of `print_primary_comparisons.py` when experiment task file is `experiment_tasks_qwen_benchmark_v1_all_conditions.jsonl` and metric is `cost_usd`, tested on Benchmark V1.
- `print_primary_comparisons_qwen_benchmark_v1_wall_clock_total_s_stdout_aug_26_1937.txt`: The stdout of `print_primary_comparisons.py` when experiment task file is `experiment_tasks_qwen_benchmark_v1_all_conditions.jsonl` and metric is `wall_clock_total_s`, tested on Benchmark V1.
- `print_primary_comparisons_qwen_benchmark_v2_cost_usd_stdout_aug_29_0816.txt`: The stdout of `print_primary_comparisons.py` when experiment task file is `experiment_tasks_qwen_benchmark_v2_all_conditions.jsonl` and metric is `cost_usd`, tested on Benchmark V2.
- `print_primary_comparisons_qwen_benchmark_v2_wall_clock_total_s_stdout_aug_29_0816.txt`: The stdout of `print_primary_comparisons.py` when experiment task file is `experiment_tasks_qwen_benchmark_v2_all_conditions.jsonl` and metric is `wall_clock_total_s`, tested on Benchmark V2.
- `print_primary_comparisons_glm_benchmark_v1_usd_stdout_aug_26_1000.txt`: The stdout of `print_primary_comparisons.py` when experiment task file is `experiment_tasks_glm_benchmark_v1_two_conditions.jsonl` and metric is `cost_usd`, tested on Benchmark V1.
- `print_primary_comparisons_glm_benchmark_v1_wall_clock_total_s_stdout_aug_26_1000.txt`: The stdout of `print_primary_comparisons.py` when experiment task file is `experiment_tasks_glm_benchmark_v1_two_conditions.jsonl` and metric is `wall_clock_total_s`, tested on Benchmark V1.
- `print_primary_comparisons_glm_benchmark_v1_usd_stdout_aug_26_1000.txt`: The stdout of `print_primary_comparisons.py` when experiment task file is `experiment_tasks_glm_benchmark_v2_two_conditions.jsonl` and metric is `cost_usd`, tested on Benchmark V2.
- `print_primary_comparisons_glm_benchmark_v2_wall_clock_total_s_stdout_aug_22_1000.txt`: The stdout of `print_primary_comparisons.py` when experiment task file is `experiment_tasks_glm_benchmark_v2_two_conditions.jsonl` and metric is `wall_clock_total_s`, tested on Benchmark V2.
- `score_distribution_deepseek_benchmark_v2.pdf`: the score distribution when SimSkill LLM is `deepseek-v4-pro` tested on Benchmark V2.
- `score_distribution_qwen_benchmark_v2.pdf`: the score distribution when SimSkill LLM is `qwen-3.7-max` tested on Benchmark V2.

