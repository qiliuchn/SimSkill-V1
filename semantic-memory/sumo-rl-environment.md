---
summary: sumo-rl's SumoEnvironment wraps TraCI as a Gymnasium/PettingZoo-style environment for traffic signal control, defining a discrete phase-selection action space, a per-signal density/queue observation vector, and a choice of reward functions.
keywords:
  - sumo-rl
  - SumoEnvironment
  - Gymnasium
  - PettingZoo
  - reward-function
created: 2026-07-21T14:00:00
last_updated: 2026-07-21T14:00:00
sources:
  - "[[raw-materials/Sumo Environment - SUMO-RL 1.4.5 documentation.md]]"
  - https://lucasalegre.github.io/sumo-rl/documentation/sumo_env/
related_pages:
  - "[[q-learning-agent]]"
  - "[[traci]]"
  - "[[change-vehicle-state]]"
related_skills:
  - optimize-signals-by-qlearning
related_skills_for_graph_view:
  - "[[optimize-signals-by-qlearning]]"
---

# SUMO RL Environment

`sumo_rl.environment.env.SumoEnvironment` wraps [[traci]] as a reinforcement-learning environment for traffic signal control, following the Gymnasium interface (or a multi-agent PettingZoo-style dict interface when `single_agent=False`, the default). It's the environment underlying [[q-learning-agent]] and any other RL approach built on `sumo-rl`.

## Constructing an environment

Key constructor parameters: `net_file`, `route_file`, `out_csv_name` (metrics output, `None` disables it), `use_gui`, `begin_time`, `num_seconds` (episode length), `delta_time` (seconds between agent decisions, default 5), `yellow_time` (default 2), `min_green`/`max_green` (default 5/60 — **`max_green` is currently ignored by sumo-rl unless `enforce_max_green=True`** is also set), `single_agent`, `reward_fn`, `reward_weights`, `observation_class`, `sumo_seed` (`'random'` or an int), `ts_ids` (restrict which traffic lights are controlled; `None` means every `tlLogic` in the network), `fixed_ts` (ignore RL actions and just follow the network's own phase timing — useful as a baseline), `sumo_warnings`, and `additional_sumo_cmd` (raw extra SUMO CLI args).

## The MDP

- **Observation**, per traffic signal, every `delta_time` seconds: `[phase_one_hot, min_green_elapsed, lane_1_density, ..., lane_n_density, lane_1_queue, ..., lane_n_queue]` — `phase_one_hot` marks the currently active green phase, `min_green_elapsed` is a binary flag for whether the minimum green time has passed, and density/queue are per-incoming-lane vehicle counts normalized by lane capacity (queue = vehicles below 0.1 m/s). This is a continuous vector by default; a custom `ObservationFunction` subclass can replace it entirely.
- **Action**: discrete — every `delta_time` seconds, each signal agent picks which green phase configuration is active next. Every phase change is automatically preceded by a `yellow_time`-second yellow phase.
- **Reward**: selected via `reward_fn`, either a string naming a built-in, a custom callable `fn(traffic_signal) -> float`, or a dict/list combining several (with optional `reward_weights`). Built-ins: `diff-waiting-time` (default — change in total cumulative vehicle delay vs. the previous step), `average-speed`, `queue` (negative total queue length), `pressure` (incoming minus outgoing vehicle counts), `co2`.

## Key methods

- `reset(seed=None, **kwargs)` — start a new episode; returns `{ts_id: observation}` in multi-agent mode.
- `step(action)` — apply action(s) (a single int if `single_agent=True`, else a `{ts_id: action}` dict) and advance `delta_time` seconds.
- `encode(state, ts_id)` — discretize a raw observation into a hashable object, needed for anything with a tabular representation like [[q-learning-agent]].
- `action_spaces(ts_id)` / `observation_spaces(ts_id)` — per-signal Gym spaces (multi-agent); `action_space`/`observation_space` properties cover the single-agent case.
- `save_csv(out_csv_name, episode)` — write the episode's metrics; note `reset()` only auto-saves the *previous* episode's metrics, so the final episode needs an explicit call after the training loop ends.
- `close()` — stop the SUMO subprocess.

## Practical notes

- `sumo-rl` imports `traci` at import time and raises `ImportError` immediately if `SUMO_HOME` isn't set — guard imports lazily if RL is an optional feature of a larger codebase.
- `add_system_info`/`add_per_agent_info` control whether system-wide (total queue, waiting time, average speed) and per-signal metrics get computed into `step()`'s info dict.
