---
name: optimize-signals-by-qlearning
description: Use this skill when the user wants to optimize traffic signal control using reinforcement learning — specifically tabular Q-learning — rather than a static/fixed-time plan (Webster's method, offset coordination) or a deep-RL library. Covers the sumo-rl package's SumoEnvironment (a Gymnasium/PettingZoo-style TraCI wrapper) and its QLAgent. Trigger on mentions of sumo-rl, Q-learning for traffic signals, RL traffic signal control, adaptive signal control via reinforcement learning, or training an agent to control intersections.
---

# Optimize Signals via Q-Learning (sumo-rl)

Trains one tabular Q-learning agent per signalized intersection to choose green phases adaptively, using the `sumo-rl` package's `SumoEnvironment` (a TraCI-based Gymnasium/PettingZoo environment) and its `QLAgent`. Reference: https://lucasalegre.github.io/sumo-rl/documentation/sumo_env/ and https://github.com/LucasAlegre/sumo-rl/blob/main/sumo_rl/agents/ql_agent.py

This is a different kind of optimization from the sibling `optimize-signals-by-tlscycleadaptation`/`optimize-signals-by-tlscoordinator` skills: those produce a *static* fixed-time plan sized to one demand snapshot. This one trains a policy that *adapts* phase selection to real-time traffic state — at the cost of needing a training loop rather than a single command, and of tabular Q-learning's own scaling limits (see Gotchas).

## Setup

```bash
pip install sumo-rl
```

`sumo-rl` imports `traci` internally and **raises an `ImportError` at import time if `SUMO_HOME` isn't set** — make sure that's exported before running either script here, the same requirement as `run-simulation`.

## The MDP sumo-rl defines (what the agent actually sees/does)

- **Observation** (per traffic signal, every `delta_time` seconds): `[phase_one_hot, min_green_elapsed, lane_1_density, ..., lane_n_density, lane_1_queue, ..., lane_n_queue]` — a continuous vector. `SumoEnvironment.encode(obs, ts_id)` discretizes this into a hashable tuple, which is what `QLAgent`'s table actually keys on.
- **Action**: discrete — choose which green phase configuration is active for the next `delta_time` seconds. Every phase change is automatically preceded by a `yellow_time`-second yellow phase.
- **Reward**: `reward_fn` selects among (or a custom callable/dict/list):

  | `reward_fn` value | Meaning |
  | --- | --- |
  | `diff-waiting-time` (default) | change in total cumulative vehicle delay vs. the previous step |
  | `average-speed` | average speed of all vehicles |
  | `queue` | negative total queue length |
  | `pressure` | incoming minus outgoing vehicle counts at the signal |
  | `co2` | CO2 emissions |

  Reward choice matters a lot for what behavior gets learned — `queue`/`diff-waiting-time` optimize for delay, `average-speed` for throughput-like behavior; pick according to what the user actually cares about.

## Quick usage

```bash
# Train, default settings (diff-waiting-time reward, one QLAgent per tlLogic in the network)
python scripts/train_qlearning.py --net-file net.net.xml --route-file routes.rou.xml --out-dir qlearning_run

# More episodes, longer horizon, a different reward
python scripts/train_qlearning.py --net-file net.net.xml --route-file routes.rou.xml --out-dir qlearning_run \
    --episodes 50 --num-seconds 3600 --reward-fn queue

# Tune the Webster-adjacent timing parameters (these constrain the action space, same meaning as elsewhere in SUMO)
python scripts/train_qlearning.py --net-file net.net.xml --route-file routes.rou.xml --out-dir qlearning_run \
    --delta-time 5 --yellow-time 3 --min-green 5 --max-green 50

# Restrict training to specific traffic lights only (rather than every tlLogic in the network)
python scripts/train_qlearning.py --net-file net.net.xml --route-file routes.rou.xml --out-dir qlearning_run --ts-ids tls_A,tls_B

# Watch training happen (much slower)
python scripts/train_qlearning.py --net-file net.net.xml --route-file routes.rou.xml --out-dir qlearning_run --gui

# Evaluate a trained policy greedily (no exploration), for comparison against a fixed-time baseline
python scripts/run_trained_policy.py --net-file net.net.xml --route-file routes.rou.xml \
    --qtables-dir qlearning_run/qtables --out-dir qlearning_eval --num-seconds 3600
```

## `train_qlearning.py` options

| Flag | Meaning | Default |
| --- | --- | --- |
| `--net-file` | input `.net.xml` (required) | — |
| `--route-file` | routed demand `.rou.xml` (required — same routes-not-trips constraint as the tls-optimization skills; use `convert-trips-to-routes` first if needed) | — |
| `--out-dir` | directory for Q-tables, training CSV metrics, and SUMO logs | required |
| `--episodes` | number of training episodes | 5 |
| `--num-seconds` | simulated seconds per episode | 3600 |
| `--alpha` | Q-learning learning rate | 0.1 |
| `--gamma` | discount factor | 0.99 |
| `--delta-time` | seconds between agent decisions | 5 |
| `--yellow-time` | yellow phase duration (s) | 2 |
| `--min-green` / `--max-green` | green-phase duration bounds (s) | 5 / 50 |
| `--reward-fn` | one of the table above | `diff-waiting-time` |
| `--sumo-seed` | `random` or an int, for reproducibility | `random` |
| `--ts-ids` | comma-separated traffic-light ids to control (default: every `tlLogic` in the network) | — |
| `--begin-time` | simulation start time (s) | 0 |
| `--gui` | run with `sumo-gui` instead of headless (much slower, for inspection) | off |
| `--additional-sumo-cmd` | raw extra SUMO command-line args, passed through | — |

Output: `<out-dir>/qtables/<ts_id>.pkl` (one pickled Q-table dict per traffic signal) and `<out-dir>/train_results_<episode>.csv` (sumo-rl's own per-step metrics).

## `run_trained_policy.py` options

Same connection-related flags as training (`--net-file`, `--route-file`, `--gui`, `--sumo-seed`, `--delta-time`/`--yellow-time`/`--min-green`/`--max-green` — **these must match what was used during training**, since they define the action space the Q-table was learned against), plus:

| Flag | Meaning |
| --- | --- |
| `--qtables-dir` | directory of pickled Q-tables from training (required) |
| `--out-dir` | where to write evaluation CSV metrics |
| `--num-seconds` | simulated seconds to run |

Runs one episode with the loaded Q-tables and **no exploration** (pure greedy action selection) — this is the "deploy what was learned" step, distinct from training. A state encountered during evaluation that was never seen in training falls back to a fixed default action (documented in the script) rather than crashing.

## Comparing against the fixed-time skills

Since `optimize-signals-by-tlscycleadaptation`/`optimize-signals-by-tlscoordinator` and this skill both end up controlling the same kind of network, a natural evaluation is: run the *same* route file against (a) the network's original/optimized fixed-time plan via `run-simulation`, and (b) `run_trained_policy.py`'s output here, then compare `run-simulation`'s or sumo's own `--duration-log.statistics`/tripinfo output between the two. Neither this skill nor the fixed-time ones automate that comparison — it's a manual (or scripted) side-by-side using each skill's own output.

## Gotchas

- **Tabular Q-learning does not scale to large networks or fine-grained observations.** Each unique discretized state gets its own table row; with many lanes per signal or many signals, the state space can grow far faster than training episodes can cover it, leading to mostly-unseen states at evaluation time. This approach is best suited to small-to-moderate networks (a handful of intersections) — `create-single-intersection` or a small `create-grid-network` are natural starting points. For larger networks, sumo-rl's Gymnasium/PettingZoo interfaces are also compatible with function-approximation methods (DQN, PPO, etc. via Stable-Baselines3 or similar) — out of scope for this skill, but the same `SumoEnvironment` is the entry point.
- **`max_green` is noted as currently ignored by sumo-rl itself** (per its own docstring) unless `enforce_max_green=True` is also set — this wrapper doesn't expose `enforce_max_green` by default; check the installed sumo-rl version's behavior if `--max-green` doesn't seem to be taking effect.
- **The network's `tlLogic` phases are assumed to alternate `[green, yellow, green, yellow, ...]`** — sumo-rl's `TrafficSignal` class is built around this pattern and doesn't support all-red phases. Networks from `create-grid-network`/`create-single-intersection`/`load-osm-network` with default TLS generation should already follow this; a hand-edited or unusual `tlLogic` might not.
- **Training and evaluation must use matching `delta_time`/`yellow_time`/`min_green`/`max_green`.** These define the action space and phase-duration semantics the Q-table was learned against — changing them between training and evaluation silently produces a mismatched (and likely poorly-performing) policy rather than an error.
- **`num_seconds` per episode should comfortably exceed the route file's demand span** — if the episode ends mid-demand, later-departing vehicles' behavior never gets observed or learned from in that episode.
- **This trains synchronously in one process** — for anything beyond quick experimentation (many episodes on a nontrivial network), expect training to take a while; there's no parallelization built into this wrapper.
- **Q-tables are per-agent Python dicts pickled to disk** — they're tied to the exact observation encoding sumo-rl produces for the given `net_file`/signal configuration; don't expect a Q-table trained on one network to transfer to a different network's signal layout.
