---
title: "Sumo Environment - SUMO-RL 1.4.5 documentation"
source: "https://lucasalegre.github.io/sumo-rl/documentation/sumo_env/"
author:
published:
created: 2026-07-21
description:
tags:
  - "clippings"
---
## Sumo Environment

*class* sumo\_rl.environment.env.SumoEnvironment(*net\_file: str*, *route\_file: str*, *out\_csv\_name: str | None = None*, *use\_gui: bool = False*, *virtual\_display: ~typing.Tuple\[int*, *int\] = (3200*, *1800)*, *begin\_time: int = 0*, *num\_seconds: int = 20000*, *max\_depart\_delay: int = -1*, *waiting\_time\_memory: int = 1000*, *time\_to\_teleport: int = -1*, *delta\_time: int = 5*, *yellow\_time: int = 2*, *min\_green: int = 5*, *max\_green: int = 50*, *enforce\_max\_green: bool = False*, *single\_agent: bool = False*, *reward\_fn: str | ~typing.Callable | dict | ~typing.List = 'diff-waiting-time'*, *reward\_weights: ~typing.List\[float\] | None = None*, *observation\_class: type\[~sumo\_rl.environment.observations.ObservationFunction\] = \<class 'sumo\_rl.environment.observations.DefaultObservationFunction'>*, *add\_system\_info: bool = True*, *add\_per\_agent\_info: bool = True*, *sumo\_seed: str | int = 'random'*, *ts\_ids: ~typing.List\[str\] | None = None*, *fixed\_ts: bool = False*, *sumo\_warnings: bool = True*, *additional\_sumo\_cmd: str | None = None*, *render\_mode: str | None = None*) [¶](#sumo_rl.environment.env.SumoEnvironment "Link to this definition")

SUMO Environment for Traffic Signal Control.

Class that implements a gym.Env interface for traffic signal control using the SUMO simulator. See [https://sumo.dlr.de/docs/](https://sumo.dlr.de/docs/) for details on SUMO. See [https://gymnasium.farama.org/](https://gymnasium.farama.org/) for details on gymnasium.

Parameters:

- **net\_file** (*str*) – SUMO.net.xml file
- **route\_file** (*str*) – SUMO.rou.xml file
- **out\_csv\_name** (*Optional* *\[**str**\]*) – name of the.csv output with simulation results. If None, no output is generated
- **use\_gui** (*bool*) – Whether to run SUMO simulation with the SUMO GUI
- **virtual\_display** (*Optional* *\[**Tuple* *\[**int**,**int**\]**\]*) – Resolution of the virtual display for rendering
- **begin\_time** (*int*) – The time step (in seconds) the simulation starts. Default: 0
- **num\_seconds** (*int*) – Number of simulated seconds on SUMO. The duration in seconds of the simulation. Default: 20000
- **max\_depart\_delay** (*int*) – Vehicles are discarded if they could not be inserted after max\_depart\_delay seconds. Default: -1 (no delay)
- **waiting\_time\_memory** (*int*) – Number of seconds to remember the waiting time of a vehicle (see [https://sumo.dlr.de/pydoc/traci.\_vehicle.html#VehicleDomain-getAccumulatedWaitingTime](https://sumo.dlr.de/pydoc/traci._vehicle.html#VehicleDomain-getAccumulatedWaitingTime)). Default: 1000
- **time\_to\_teleport** (*int*) – Time in seconds to teleport a vehicle to the end of the edge if it is stuck. Default: -1 (no teleport)
- **delta\_time** (*int*) – Simulation seconds between actions. Default: 5 seconds
- **yellow\_time** (*int*) – Duration of the yellow phase. Default: 2 seconds
- **min\_green** (*int*) – Minimum green time in a phase. Default: 5 seconds
- **max\_green** (*int*) – Max green time in a phase. Default: 60 seconds. Warning: This parameter is currently ignored!
- **enforce\_max\_green** (*bool*) – If true, it enforces the max green time and selects the next green phase when the max green time is reached. Default: False
- **single\_agent** (*bool*) – If true, it behaves like a regular gym.Env. Else, it behaves like a MultiagentEnv (returns dict of observations, rewards, dones, infos).
- **reward\_fn** (*str/function/dict/List*) – String with the name of the reward function used by the agents, a reward function, dictionary with reward functions assigned to individual traffic lights by their keys, or a List of reward functions.
- **reward\_weights** (*List* *\[**float**\]* */np.ndarray*) – Weights for linearly combining the reward functions, in case reward\_fn is a list. If it is None, the reward returned will be a np.ndarray. Default: None
- **observation\_class** ([*ObservationFunction*](https://lucasalegre.github.io/sumo-rl/documentation/observations/#sumo_rl.environment.observations.ObservationFunction "sumo_rl.environment.observations.ObservationFunction")) – Inherited class which has both the observation function and observation space.
- **add\_system\_info** (*bool*) – If true, it computes system metrics (total queue, total waiting time, average speed) in the info dictionary.
- **add\_per\_agent\_info** (*bool*) – If true, it computes per-agent (per-traffic signal) metrics (average accumulated waiting time, average queue) in the info dictionary.
- **sumo\_seed** (*int/string*) – Random seed for sumo. If ‘random’ it uses a randomly chosen seed.
- **ts\_ids** (*Optional* *\[**List* *\[**str**\]**\]*) – List of traffic light IDs to be controlled by SUMO-RL. If None, all traffic lights in the simulation are controlled.
- **fixed\_ts** (*bool*) – If true, it will follow the phase configuration in the route\_file and ignore the actions given in the method.
- **sumo\_warnings** (*bool*) – If true, it will print SUMO warnings.
- **additional\_sumo\_cmd** (*str*) – Additional SUMO command line arguments.
- **render\_mode** (*str*) – Mode of rendering. Can be ‘human’ or ‘rgb\_array’. Default: None

*property* action\_space [¶](#sumo_rl.environment.env.SumoEnvironment.action_space "Link to this definition")

Return the action space of a traffic signal.

Only used in case of single-agent environment.

action\_spaces(*ts\_id: str*) → Discrete [¶](#sumo_rl.environment.env.SumoEnvironment.action_spaces "Link to this definition")

Return the action space of a traffic signal.

close() [¶](#sumo_rl.environment.env.SumoEnvironment.close "Link to this definition")

Close the environment and stop the SUMO simulation.

encode(*state*, *ts\_id*) [¶](#sumo_rl.environment.env.SumoEnvironment.encode "Link to this definition")

Encode the state of the traffic signal into a hashable object.

*property* observation\_space [¶](#sumo_rl.environment.env.SumoEnvironment.observation_space "Link to this definition")

Return the observation space of a traffic signal.

Only used in case of single-agent environment.

observation\_spaces(*ts\_id: str*) [¶](#sumo_rl.environment.env.SumoEnvironment.observation_spaces "Link to this definition")

Return the observation space of a traffic signal.

render() [¶](#sumo_rl.environment.env.SumoEnvironment.render "Link to this definition")

Render the environment.

If render\_mode is “human”, the environment will be rendered in a GUI window using pyvirtualdisplay.

reset(*seed: int | None = None*, *\*\*kwargs*) [¶](#sumo_rl.environment.env.SumoEnvironment.reset "Link to this definition")

Reset the environment.

*property* reward\_dim [¶](#sumo_rl.environment.env.SumoEnvironment.reward_dim "Link to this definition")

Return the reward dimension of a traffic signal.

Only used in case of single-agent environment.

*property* reward\_space [¶](#sumo_rl.environment.env.SumoEnvironment.reward_space "Link to this definition")

Return the reward space of a traffic signal.

Only used in case of single-agent environment.

save\_csv(*out\_csv\_name*, *episode*) [¶](#sumo_rl.environment.env.SumoEnvironment.save_csv "Link to this definition")

Save metrics of the simulation to a.csv file.

Parameters:

- **out\_csv\_name** (*str*) – Path to the output.csv file. E.g.: “results/my\_results
- **episode** (*int*) – Episode number to be appended to the output file name.

*property* sim\_step*: float* [¶](#sumo_rl.environment.env.SumoEnvironment.sim_step "Link to this definition")

Return current simulation second on SUMO.

step(*action: dict | int*) [¶](#sumo_rl.environment.env.SumoEnvironment.step "Link to this definition")

Apply the action(s) and then step the simulation for delta\_time seconds.

Parameters:

- **action** (*Union* *\[**dict**,* *int**\]*) – action(s) to be applied to the environment.
- **True** (*If single\_agent is*)
- **int** (*action is an*)
- **ids.** (*otherwise it expects a dict with keys corresponding to traffic signal*)