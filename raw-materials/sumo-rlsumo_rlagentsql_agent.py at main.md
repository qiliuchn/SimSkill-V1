---
title: "sumo-rl/sumo_rl/agents/ql_agent.py at main"
source: "https://github.com/LucasAlegre/sumo-rl/blob/main/sumo_rl/agents/ql_agent.py"
author:
published:
created: 2026-07-21
description: "Reinforcement Learning environments for Traffic Signal Control with SUMO. Compatible with Gymnasium, PettingZoo, and popular RL libraries. - sumo-rl/sumo_rl/agents/ql_agent.py at main · LucasAlegre/sumo-rl"
tags:
  - "clippings"
---
1

2

3

4

5

6

7

8

9

10

11

12

13

14

15

16

17

18

19

20

21

22

23

24

25

26

27

28

29

30

31

32

33

34

35

36

37

38

"""Q-learning Agent class."""

from sumo\_rl.exploration.epsilon\_greedy import EpsilonGreedy

class QLAgent:

"""Q-learning Agent class."""

def \_\_init\_\_(self, starting\_state, state\_space, action\_space, alpha=0.5, gamma=0.95, exploration\_strategy=EpsilonGreedy()):

"""Initialize Q-learning agent."""

self.state = starting\_state

self.state\_space = state\_space

self.action\_space = action\_space

self.action = None

self.alpha = alpha

self.gamma = gamma

self.q\_table = {self.state: \[0 for \_ in range(action\_space.n)\]}

self.exploration = exploration\_strategy

self.acc\_reward = 0

def act(self):

"""Choose action based on Q-table."""

self.action = self.exploration.choose(self.q\_table, self.state, self.action\_space)

return self.action

def learn(self, next\_state, reward, done=False):

"""Update Q-table with new experience."""

if next\_state not in self.q\_table:

self.q\_table\[next\_state\] = \[0 for \_ in range(self.action\_space.n)\]

s = self.state

s1 = next\_state

a = self.action

self.q\_table\[s\]\[a\] = self.q\_table\[s\]\[a\] + self.alpha \* (

reward + self.gamma \* max(self.q\_table\[s1\]) - self.q\_table\[s\]\[a\]

)

self.state = s1

self.acc\_reward += reward