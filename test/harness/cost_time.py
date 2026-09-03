"""Cost/time instrumentation for test/experiments.md §3.2 ("Fair Comparison: Controlling
for Compute Budget").

Two independent things happen here:

1. Token/cost accounting (§3.2.1, §3.2.2): normalize `claude -p --output-format json`'s
   result object into separate input/output/cache-read/cache-write token fields (never
   pre-summed), and convert to dollar cost via price_table.yaml.

2. Agent-vs-simulation wall-clock split (§3.2.3): best-effort parse of the session's
   JSONL transcript to classify each Bash tool call as "simulation" (it invoked a
   SUMO binary/tool) or "agent" (everything else), so a task with a long simulation
   doesn't make an efficient agent look slow, and vice versa.

The transcript format is Claude Code's internal session-log schema, which isn't a
public/versioned contract — this module is deliberately defensive (every field access
is a `.get()`, parsing failures degrade to `None` fields with a warning) rather than
assuming a specific schema will hold forever. Before relying on this for a real batch
of runs, spot-check `find_transcript_path` + `agent_vs_simulation_split` against one
real session on the installed Claude Code version.


## Time Interpretation
Cost time is stored in task execution results, which is extracted from `claude -p` return;
Example:
```
  "wall_clock_ms": {
    "total": 242002,
    "total_measured_by_harness": 242954,
    "agent": 240836,
    "simulation": 1166,
    "duration_api_ms": 241244
  }
```

Field	                    Meaning	                                            Add to total?
total	                    The chosen duration for analysis. Prefers           It is the total
                            Claude CLI’s duration_ms; falls back to the 
                            Python harness measurement.	
agent	                    Residual time after subtracting recognized           Yes, with simulation
                            simulation calls. Includes LLM waiting, 
                            orchestration, file operations, non-SUMO 
                            commands, CLI overhead, and idle gaps.	
simulation	                Sum of transcript tool-call durations whose          Yes, with agent
                            command matches the SUMO command regex.	 
total_measured_by_harness	Independent stopwatch around                          No
                            subprocess.run(["claude", ...]). It is an 
                            alternative measurement of the same invocation.	
duration_api_ms	            Value copied directly from Claude CLI’s JSON.          No
                            Approximately API-request time, but this code 
                            does not interpret or use it. It may overlap 
                            across requests.	

So we have:
    total = agent + simulation
Consequently, “agent” means “everything that was not recognized as simulation,” not strictly “time 
when the LLM was actively thinking.”

The harness measures the actual subprocess interval here:
    run_start_wall = time.time()
    subprocess.run(...)
    wall_ms_measured = time.time() - run_start_wall

gives priority to the CLI-reported duration:
total_ms = (
    usage.duration_ms
    if usage.duration_ms is not None
    else raw["wall_clock_ms_measured"]
)

This distinction matters. One existing result has:
    total                       = 185,993 ms  # Claude duration_ms
    total_measured_by_harness   = 283,933 ms  # actual Python wait
    duration_api_ms             = 284,956 ms

So in that run, the field currently named total is clearly not the user-observed subprocess wall time. 
For real wall-clock analysis, total_measured_by_harness is the safer measurement; duration_ms should 
be treated as a CLI/provider metric until the discrepancy is understood.



## Cost Interpretation
The dollar-cost formula is:

    cost_usd =
        input_tokens       x input_rate        / 1,000,000
    + output_tokens        x output_rate       / 1,000,000
    + cache_creation       x cache_write_rate  / 1,000,000
    + cache_read           x cache_read_rate   / 1,000,000
    
PS: The raw CLI's total_cost_usd is parsed but not used. The reported cost_usd is recomputed using the 
repository's price table. Like time, this cost covers only the task invocation—not the independent 
verification call.
"""

from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

# Tools/binaries that mean "the simulation itself is running," per §3.2.3's definition —
# deliberately narrow: post-processing/plotting scripts are agent-side analysis, not
# simulation execution, even though they read simulation output.
SIM_COMMAND_RE = re.compile(
    r"\b("
    r"sumo|sumo-gui|netconvert|netgenerate|duarouter|od2trips|jtrrouter|marouter|"
    r"dfrouter|activitygen|randomTrips\.py|routeSampler\.py|duaIterate\.py|"
    r"tlsCycleAdaptation\.py|tlsCoordinator\.py|osmGet\.py|osmBuild\.py"
    r")\b"
)

TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
""" 
cache_creation_input_tokens and cache_read_input_tokens are Claude's prompt-caching counters, 
returned alongside plain input_tokens/output_tokens in the API response usage block:
- cache_creation_input_tokens — tokens written to the prompt cache for the first time in this call 
(e.g. the first time a worktree's CLAUDE.md + skills + memory files get loaded). Billed at a premium over 
the base input rate (~1.25× for the 5-min TTL, more for 1-hour TTL), since the model still has to process 
them and the system does extra work to store them.
- cache_read_input_tokens — tokens served from an existing cache entry (a cache hit — e.g. a later call 
in the same session reusing the same CLAUDE.md/skills prefix). Billed at a steep discount (~0.1× base input 
rate) since they don't need to be reprocessed.

cache_creation_input_tokens = cache write, cache_read_input_tokens = cache read. 
That's also the naming price_table.yaml uses (cache_write, cache_read rate keys) 
"""

@dataclass
class RunUsage:
    """Data class to hold the usage information for a single run of `claude -p`."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    total_cost_usd: Optional[float] = None
    duration_ms: Optional[int] = None
    duration_api_ms: Optional[int] = None
    num_turns: Optional[int] = None
    session_id: Optional[str] = None
    is_error: Optional[bool] = None
    subtype: Optional[str] = None
    result_text: Optional[str] = None
    # Claude Code's result-level ``usage`` covers only the top-level agent loop.
    # ``modelUsage`` is the whole-tree roll-up and includes subagents.  Keep the
    # per-model entries so cost calculation can select the correct price row for
    # every model rather than flattening mixed-model sessions onto one rate.
    model_usage: dict[str, dict[str, Any]] = field(default_factory=dict)
    usage_source: str = "usage"
    warnings: list = field(default_factory=list)


MODEL_USAGE_TOKEN_FIELDS = {
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "cache_creation_input_tokens": "cacheCreationInputTokens",
    "cache_read_input_tokens": "cacheReadInputTokens",
}


def _as_nonnegative_int(value: Any) -> int:
    """Normalize one provider token counter without accepting negative usage."""
    try:
        normalized = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(normalized, 0)


def _set_usage_totals_from_model_usage(usage: RunUsage, model_usage: dict) -> bool:
    """Populate aggregate counters from Claude Code's whole-tree ``modelUsage``.

    Returns ``True`` when at least one well-formed per-model entry was found.  A
    present-but-empty/malformed mapping must not erase the usable top-level
    fallback counters.
    

    Example:
        "modelUsage": {
        "deepseek-v4-pro": {
            "inputTokens": 100,
            "outputTokens": 20,
            "cacheReadInputTokens": 500,
        },
        "deepseek-v4-flash": {
            "inputTokens": 50,
            "outputTokens": 10,
            "cacheReadInputTokens": 200,
        },
        }

    `usage` will get:  
        usage.input_tokens = 150
        usage.output_tokens = 30
        usage.cache_read_input_tokens = 700
        usage.model_usage = { ...original per-model entries... }
        usage.usage_source = "modelUsage"
    
    Note: It returns only a boolean because it modifies the `usage` object passed into it.
    """
    valid_entries: dict[str, dict[str, Any]] = {}
    totals = {field_name: 0 for field_name in MODEL_USAGE_TOKEN_FIELDS}

    for raw_model_name, raw_model_usage in model_usage.items():
        if not isinstance(raw_model_usage, dict):
            continue
        model_name = str(raw_model_name)
        valid_entries[model_name] = raw_model_usage
        for field_name, raw_field_name in MODEL_USAGE_TOKEN_FIELDS.items():
            totals[field_name] += _as_nonnegative_int(
                raw_model_usage.get(raw_field_name)
            )

    if not valid_entries:
        return False

    usage.input_tokens = totals["input_tokens"]
    usage.output_tokens = totals["output_tokens"]
    usage.cache_creation_input_tokens = totals["cache_creation_input_tokens"]
    usage.cache_read_input_tokens = totals["cache_read_input_tokens"]
    usage.model_usage = valid_entries
    usage.usage_source = "modelUsage"
    return True


def parse_claude_json_result(raw: dict) -> RunUsage:
    """ 
    We can get a JSON result from `claude -p --output-format json`
    and we can extract the usage information from it. This function takes the raw JSON result and returns a 
    RunUsage object.
    
    Normalize `claude -p --output-format json`'s stdout (already json.loads'd)
    into a RunUsage. Never pre-sums token fields — §3.2.1 requires them separate.
    
    Args:
        raw (dict): invoke_one_task function returns `raw`; but here `raw` is actually raw["raw_result"]!
            the claude code direct output - namely,
            the raw JSON result from `claude -p --output-format json`
    """
    usage = RunUsage()
    usage_block = raw.get("usage") or {}
    usage.input_tokens = _as_nonnegative_int(usage_block.get("input_tokens"))
    usage.output_tokens = _as_nonnegative_int(usage_block.get("output_tokens"))
    usage.cache_creation_input_tokens = _as_nonnegative_int(
        usage_block.get("cache_creation_input_tokens")
    )
    usage.cache_read_input_tokens = _as_nonnegative_int(
        usage_block.get("cache_read_input_tokens")
    )

    # ``usage`` excludes subagents.  Claude Code documents ``modelUsage`` as
    # the whole-agent-tree accounting source, so prefer it whenever available.
    # The top-level block remains a compatibility fallback for older CLI output.
    raw_model_usage = raw.get("modelUsage")
    if isinstance(raw_model_usage, dict):
        _set_usage_totals_from_model_usage(usage, raw_model_usage)

    # ===== get llm token usage and cost from Claude code raw JSON result =====
    # NOTE: Claude Code's JSON result has a "usage" block with token counts and cost, 
    # but the field names have changed over time. This code handles both old and new field names.
    # Different CLI versions have used both `cost_usd` and `total_cost_usd` — accept either.
    usage.total_cost_usd = raw.get("total_cost_usd", raw.get("cost_usd"))
    usage.duration_ms = raw.get("duration_ms")
    usage.duration_api_ms = raw.get("duration_api_ms")
    usage.num_turns = raw.get("num_turns")
    usage.session_id = raw.get("session_id")
    usage.is_error = raw.get("is_error")
    usage.subtype = raw.get("subtype")
    usage.result_text = raw.get("result")
    # ===== end of get llm token usage and cost from Claude code raw JSON result =====

    if usage.usage_source != "modelUsage":
        if not usage_block:
            usage.warnings.append(
                "no usable 'modelUsage' or 'usage' block in claude result JSON "
                "— token fields default to 0"
            )
        else:
            usage.warnings.append(
                "no usable 'modelUsage' block in claude result JSON — using "
                "top-level 'usage', which excludes subagent tokens"
            )
    return usage


def load_price_table(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _rates_for_raw_model(
    raw_model_name: str, default_model_key: str, price_table: dict, *,
    allow_default: bool,
) -> tuple[Optional[dict], Optional[str]]:
    """Resolve a Claude ``modelUsage`` key to one repository price row.
    translates a model name reported by Claude Code into the corresponding entry in price_table.yaml

    Args:
        raw_model_name (str): Name reported in modelUsage
        default_model_key (str): Model configured by user
        price_table (dict): the price table to use
        allow_default (bool): whether to allow the default model key to be used
    Returns:
        A tuple of (rates, model_key), where model_key is the key in price_table.yaml that was used to resolve the model name.
    
    For example:
        raw_model_name = "deepseek-v4-pro[1m]"
        default_model_key = "deepseek-v4-pro"
        
    It tries five matching strategies, in order:
    1. Exact match on ``modelUsage`` key
        If the price table directly contains the raw model name, that entry wins
    2. Explicit alias match
        Each price entry may list alternative provider model names under model_ids:
    3. Namespace-stripped exact match
        A provider-qualified name such as kimi/kimi-k3 can use the kimi-k3 row.
    4. Bracket-suffix prefix match
        The function handles names such as:
        deepseek-v4-pro[1m]
        when the price table only contains:
        deepseek-v4-pro
    5. Optional fallback to the configured model
        If none of those strategies work, it may fall back to default_model_key
        rates = all_rates.get(default_model_key)
    
    Exact keys win, followed by explicit ``model_ids`` aliases, a lookup after
    removing a provider namespace, and then a boundary-aware prefix match (for
    example ``deepseek-v4-pro[1m]`` maps to ``deepseek-v4-pro``).  A
    single-model result may safely fall back to the harness model selected for
    the run.
    """
    all_rates = price_table.get("rates") or {}
    # 1. Exact match on ``modelUsage`` key
    if raw_model_name in all_rates:
        return all_rates[raw_model_name], raw_model_name

    # 2. Explicit alias match by making use of model_ids
    for price_key, rates in all_rates.items():
        aliases = (rates.get("model_ids") or []) if isinstance(rates, dict) else []
        if raw_model_name in aliases:
            return rates, price_key

    # 3. Exact match after removing a provider namespace such as ``kimi/``.
    unqualified_model_name = raw_model_name.rsplit("/", 1)[-1]
    if (
        unqualified_model_name != raw_model_name
        and unqualified_model_name in all_rates
    ):
        return all_rates[unqualified_model_name], unqualified_model_name

    # 4. Prefix match
    prefix_matches = []
    for price_key, rates in all_rates.items():
        if not isinstance(rates, dict):
            continue
        if raw_model_name.startswith(f"{price_key}["):
            prefix_matches.append((price_key, rates))
    if len(prefix_matches) == 1:
        price_key, rates = prefix_matches[0]
        return rates, price_key
    
    # 5. Optional fallback to the configured model
    if allow_default:
        rates = all_rates.get(default_model_key)
        if isinstance(rates, dict):
            return rates, default_model_key
    return None, None


def _cost_for_token_counts(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int,
    cache_read_input_tokens: int,
    rates: dict,
    price_key: str,
) -> tuple[Optional[float], list[str]]:
    needed = {
        "input": input_tokens,
        "output": output_tokens,
        "cache_write": cache_creation_input_tokens,
        "cache_read": cache_read_input_tokens,
    }
    total = 0.0
    for rate_key, n_tokens in needed.items():
        rate = rates.get(rate_key)
        if rate is None:
            if n_tokens:
                return None, [
                    f"missing '{rate_key}' rate for '{price_key}' with "
                    f"{n_tokens} such tokens"
                ]
            continue
        total += (n_tokens / 1_000_000) * float(rate)
    return total, []


def compute_dollar_cost(usage: RunUsage, model_key: str, price_table: dict) -> tuple[Optional[float], list]:
    """Returns (cost_usd, warnings). Cost is None (not 0) if any needed rate is missing —
    §3.2.2/§6: a missing rate must never be silently treated as free.
    
    compute_dollar_cost chooses between two ways of calculating the cost:
        1. Preferred: calculate each model’s cost separately using usage.model_usage.
        2. Fallback: calculate the aggregate token cost using the run’s configured model_key.
    """
    warns: list[str] = []
    total = 0.0
    if usage.model_usage:  # modelUsage includes the whole agent tree, including subagents
        for raw_model_name, raw_model_usage in usage.model_usage.items():
            rates, price_key = _rates_for_raw_model(
                raw_model_name,
                model_key,
                price_table,
                allow_default=len(usage.model_usage) == 1,
            )
            if rates is None or price_key is None:
                return None, [
                    f"no price_table entry for raw model '{raw_model_name}' "
                    f"(run model '{model_key}')"
                ]
            model_cost, model_warns = _cost_for_token_counts(
                input_tokens=_as_nonnegative_int(raw_model_usage.get("inputTokens")),
                output_tokens=_as_nonnegative_int(raw_model_usage.get("outputTokens")),
                cache_creation_input_tokens=_as_nonnegative_int(
                    raw_model_usage.get("cacheCreationInputTokens")
                ),
                cache_read_input_tokens=_as_nonnegative_int(
                    raw_model_usage.get("cacheReadInputTokens")
                ),
                rates=rates,
                price_key=price_key,
            )
            if model_cost is None:
                return None, model_warns
            total += model_cost
    else:  # assumes all aggregate tokens belong to model_key and calculates: 
        # cost =
        # input tokens      × input rate
        # + output tokens     × output rate
        # + cache-write tokens × cache-write rate
        # + cache-read tokens  × cache-read rate
        print("\n [Warning: using fallback pricing for model '{model_key}'.]")
        rates = (price_table.get("rates") or {}).get(model_key)
        if not isinstance(rates, dict):
            return None, [f"no price_table entry for model '{model_key}'"]
        fallback_cost, fallback_warns = _cost_for_token_counts(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            rates=rates,
            price_key=model_key,
        )
        if fallback_cost is None:
            return None, fallback_warns
        total = fallback_cost
    if not price_table.get("price_table_date"):
        warns.append("price_table.yaml has no price_table_date set — see experiments.md §7")
    return total, warns


def sanitize_cwd_for_transcripts(cwd: Path) -> str:
    """Mirrors Claude Code's ~/.claude/projects/<sanitized-cwd>/ directory naming.

    Claude Code replaces every non-alphanumeric character with `-`, not just `/` —
    confirmed empirically (a worktree path containing `_` produces a project directory
    with `-`, not `_`; same for `.`). Replacing only `/` silently never matches the real
    directory for any path containing `_`, `.`, or similar, which is exactly what every
    worktree path in this harness looks like (e.g. `full-ver_claude-haiku-4-5`)."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd.resolve()))

def find_transcript_path(cwd: Path, session_id: str, claude_home: Optional[Path] = None) -> Path:
    """
    'Transcript' here means the JSONL log file Claude Code writes per session at ~/.claude/projects/<sanitized-cwd>/<session_id>.jsonl —
    one JSON line per event (each assistant message, tool call, tool result) making up a full turn-by-turn record of that session.
    `agent_vs_simulation_split` will parses it to classify each Bash tool call as "simulation" (it invoked a SUMO binary) or
    "agent" (everything else) and sum up the time spent in each, for the §3.2.3 agent-vs-simulation wall-clock split.

    Always returns the candidate path, whether or not it actually exists — the caller checks
    `.exists()` itself. This is deliberate: when the transcript is missing, the caller (and
    its warning message) can still say exactly where it looked, rather than just "not found"
    with no way to tell whether that means a sanitization bug, a wrong session id, or the
    file genuinely never being written.

    The transcript id is the session_id itself — Claude Code names each session's
    JSONL log <session_id>.jsonl under ~/.claude/projects/<sanitized-cwd>/.

    run_experiment.py generates session_id = str(uuid.uuid4()) before ever calling claude,
    then passes that same UUID in as --session-id <uuid> when building the command (build_claude_command, line 178).
    Claude Code doesn't get to pick its own session id here; we dictate it.
    The flow is:
    - Harness mints a UUID.
    - Harness invokes claude -p --session-id <uuid> ..., which forces Claude Code to write its transcript to <uuid>.jsonl.
    - After the run, annotate_with_cost_time (line 297-298) calls find_transcript_path(worktree_path, usage.session_id) —
    passing back the same UUID it already had, just to build the path ~/.claude/projects/<sanitized-cwd>/<uuid>.jsonl and confirm
    the file exists.
    """
    claude_home = claude_home or (Path.home() / ".claude")
    return claude_home / "projects" / sanitize_cwd_for_transcripts(cwd) / f"{session_id}.jsonl"


def _parse_ts(value) -> Optional[datetime]:
    """Parse a timestamp string from the transcript into a datetime, or return None if it's missing or invalid."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class TimeSplit:
    """Data class to hold the agent vs simulation time split information for a single run of `claude -p`."""
    agent_ms: Optional[int] = None
    simulation_ms: Optional[int] = None
    matched_tool_calls: int = 0
    unmatched_tool_calls: int = 0
    warnings: list = field(default_factory=list)


def agent_vs_simulation_split(transcript_path: Optional[Path], total_wall_ms: Optional[int]) -> TimeSplit:
    """Best-effort §3.2.3 split. Falls back to (agent=total, simulation=0) with a
    warning if the transcript can't be found or parsed — never raises.

    Args:
        transcript_path: the candidate path from find_transcript_path (always a concrete
            path, whether or not it exists), or None if no session_id was available to
            build one from in the first place.
        total_wall_ms: the run's total wall-clock time in ms, used both as the
            fallback (transcript missing/unparseable) and to derive agent_ms as
            total_wall_ms - simulation_ms once the transcript-derived split is known.
    """
    split = TimeSplit()
    if transcript_path is None or not transcript_path.exists():
        if transcript_path is None:
            split.warnings.append("no session_id available — agent/simulation split unavailable")
        else:
            split.warnings.append(f"transcript not found at {transcript_path} — agent/simulation split unavailable")
        split.agent_ms = total_wall_ms
        split.simulation_ms = 0 if total_wall_ms is not None else None
        return split

    tool_use_starts: dict[str, tuple[datetime, str]] = {}
    sim_ms = 0
    agent_accounted_ms = 0

    # ===== Parse transcript and get the total time spent in simulation vs agent =====
    # NOTE: core part on parsing the transcript and classifying tool calls as simulation vs agent.
    # and computing the total time spent in each category.
    try:
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                message = record.get("message") or {}
                content = message.get("content")
                if not isinstance(content, list):
                    continue

                ts = _parse_ts(record.get("timestamp"))

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use" and ts is not None:
                        name = block.get("name", "")
                        command = ""
                        if isinstance(block.get("input"), dict):
                            command = str(block["input"].get("command", ""))
                        tool_use_starts[block.get("id", "")] = (ts, f"{name} {command}")
                    elif block.get("type") == "tool_result" and ts is not None:
                        tool_use_id = block.get("tool_use_id", "")
                        started = tool_use_starts.pop(tool_use_id, None)
                        if started is None:
                            continue
                        start_ts, label = started
                        duration_ms = int((ts - start_ts).total_seconds() * 1000)
                        if duration_ms < 0:
                            continue
                        if SIM_COMMAND_RE.search(label):
                            sim_ms += duration_ms
                            split.matched_tool_calls += 1
                        else:
                            agent_accounted_ms += duration_ms
                            split.unmatched_tool_calls += 1
    except OSError as exc:
        split.warnings.append(f"failed reading transcript: {exc}")
        split.agent_ms = total_wall_ms
        split.simulation_ms = 0 if total_wall_ms is not None else None
        return split
    # ===== End of parsing transcript and classifying tool calls =====
    
    split.simulation_ms = sim_ms
    if total_wall_ms is not None:
        # Agent time = everything not spent inside a recognized simulation tool call,
        # including LLM thinking time between tool calls (not captured by tool-call
        # durations alone).
        split.agent_ms = max(total_wall_ms - sim_ms, 0)
    else:
        split.agent_ms = agent_accounted_ms
    return split


def warn_all(warnings_list: list, prefix: str = "") -> None:
    for w in warnings_list:
        warnings.warn(f"{prefix}{w}")
