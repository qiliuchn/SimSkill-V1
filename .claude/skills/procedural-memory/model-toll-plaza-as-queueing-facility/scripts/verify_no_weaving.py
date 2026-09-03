#!/usr/bin/env python3
"""
STEP 1 verification (behavioural, not just structural): confirm that the compiled
changeLeft/changeRight="authority" attributes on the `lock` edge actually PREVENT a lane
change inside the plaza, while the same forced change on the `fan` taper (where changing is
permitted) succeeds.

Method: drive the scenario with TraCI, and for every vehicle observed on `lock` (and, as a
positive control, on `fan`) issue traci.vehicle.changeLane() towards a neighbouring lane
with a long duration and all safety checks off, then check whether the lane index actually
changed within the next 20 steps.
"""
import json
import os
import sys

sys.path.insert(0, os.environ.get("SUMO_HOME", "") + "/tools")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import traci
import plaza_lib as P

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NET = os.path.join(EP, "outputs", "network", "plaza_c6.net.xml")
RUN = os.path.join(EP, "attempts", "attempt-1", "runs", "weavetest")

cfg, meta = P.write_scenario(RUN, NET, 6, 900.0, 900.0, seed=5, step_length=0.5, end_pad=900)
traci.start([P.find_bin("sumo"), "-c", cfg, "--seed", "5", "--no-warnings", "true"])

pending = {}          # vid -> (edge, target_lane, deadline_step, start_lane)
result = {"lock": {"attempts": 0, "succeeded": 0}, "fan": {"attempts": 0, "succeeded": 0}}
tried = set()
step = 0
while traci.simulation.getMinExpectedNumber() > 0 and step < 4000:
    traci.simulationStep()
    step += 1
    for vid, (edge, tgt, dead, l0) in list(pending.items()):
        if vid not in traci.vehicle.getIDList():
            del pending[vid]
            continue
        if traci.vehicle.getRoadID(vid) == edge and traci.vehicle.getLaneIndex(vid) == tgt:
            result[edge]["succeeded"] += 1
            del pending[vid]
        elif step > dead or traci.vehicle.getRoadID(vid) != edge:
            del pending[vid]
    for vid in traci.vehicle.getIDList():
        e = traci.vehicle.getRoadID(vid)
        if e not in ("lock", "fan") or (vid, e) in tried or vid in pending:
            continue
        li = traci.vehicle.getLaneIndex(vid)
        tgt = li + 1 if li < 5 else li - 1
        tried.add((vid, e))
        result[e]["attempts"] += 1
        traci.vehicle.setLaneChangeMode(vid, 0)         # all autonomous logic + safety OFF
        traci.vehicle.changeLane(vid, tgt, 60.0)
        pending[vid] = (e, tgt, step + 20, li)
traci.close()

result["verdict_lock_blocked"] = result["lock"]["succeeded"] == 0
result["verdict_fan_permits"] = result["fan"]["succeeded"] > 0
print(json.dumps(result, indent=1))
json.dump(result, open(os.path.join(EP, "outputs", "step1_no_weaving_verification.json"), "w"), indent=1)
