---
summary: sumo-rl's QLAgent is a minimal tabular Q-learning implementation with epsilon-greedy exploration and a standard Bellman update, intended to be paired one-per-traffic-signal with SumoEnvironment.
keywords:
  - QLAgent
  - Q-learning
  - tabular-RL
  - epsilon-greedy
  - Bellman-update
created: 2026-07-21T14:00:00
last_updated: 2026-07-21T14:00:00
sources:
  - "[[raw-materials/sumo-rlsumo_rlagentsql_agent.py at main.md]]"
  - https://github.com/LucasAlegre/sumo-rl/blob/main/sumo_rl/agents/ql_agent.py
related_pages:
  - "[[sumo-rl-environment]]"
related_skills:
  - optimize-signals-by-qlearning
related_skills_for_graph_view:
  - "[[optimize-signals-by-qlearning]]"
---

# Q-Learning Agent

`sumo_rl.agents.QLAgent` is a small, dependency-light tabular Q-learning implementation meant to be instantiated once per traffic signal (`ts_id`) alongside a [[sumo-rl-environment]] instance.

## Constructor

```python
QLAgent(starting_state, state_space, action_space, alpha=0.5, gamma=0.95, exploration_strategy=EpsilonGreedy())
```

- `starting_state`: a hashable state, normally `env.encode(obs, ts_id)`
- `state_space` / `action_space`: the signal's observation/action spaces from the environment (`env.observation_spaces(ts_id)` / `env.action_spaces(ts_id)` in multi-agent mode)
- `alpha`: learning rate (default 0.5)
- `gamma`: discount factor (default 0.95)
- `exploration_strategy`: defaults to `EpsilonGreedy()` from `sumo_rl.exploration.epsilon_greedy`

The Q-table (`self.q_table`) is a plain dict keyed by state, each value a list of one Q-value per discrete action, lazily initialized to zeros for any state seen for the first time.

## Core loop

```python
action = agent.act()                                    # epsilon-greedy pick from q_table[state]
next_obs, reward, done, info = env.step({ts_id: action})
agent.learn(next_state=env.encode(next_obs[ts_id], ts_id), reward=reward, done=done)
```

`act()` delegates to the exploration strategy's `choose(q_table, state, action_space)` and records the chosen action on the agent.

`learn(next_state, reward, done=False)` performs the standard tabular Q-learning (Bellman) update:

```
Q(s, a) ← Q(s, a) + α · (reward + γ · max(Q(s', ·)) − Q(s, a))
```

then sets `self.state = next_state` and accumulates `reward` into `self.acc_reward`. If `next_state` hasn't been seen before, its row is initialized to zeros first.

## Practical notes for multi-signal training

For a network with multiple signals, one `QLAgent` per `ts_id` is the natural setup (matching [[sumo-rl-environment]]'s multi-agent dict interface). Between episodes, an already-created agent's Q-table should be kept while its transient per-episode fields (`state`, `action`, `acc_reward`) get reset to align with the new episode's starting observation — the agent itself has no built-in episode-boundary handling, so this reset is the training loop's responsibility.

Because states are looked up by exact dict key, an evaluation-time state never encountered during training simply won't be in `q_table` — calling code needs to handle that case explicitly (e.g. falling back to a default action) rather than expecting `KeyError` protection from the agent itself.
