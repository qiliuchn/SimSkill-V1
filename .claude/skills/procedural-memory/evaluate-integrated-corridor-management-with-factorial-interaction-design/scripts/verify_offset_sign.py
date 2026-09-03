#!/usr/bin/env python3
"""
Verify SUMO's tlLogic offset sign convention via live TraCI observation,
per design-arterial-signal-progression-and-verify-bandwidth's discipline:
never assume (t-offset) vs (t+offset) mod C.

Picks a discriminating signal (offset not 0 or C/2), records the actual
green-onset time of its first phase over one full cycle, and checks which
convention predicts it.
"""
import os
import sys

SUMO_HOME = os.environ.get("SUMO_HOME", "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo")
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402

NET = "network/build/corridor.net.xml"
TLS = "network/build/tls.add.xml"
SIGNAL = "ax2"       # base offset 45 = C/2 -- NOT discriminating; use ax4 incident program instead (43.3)


def main():
    cmd = ["sumo", "-n", NET, "-a", TLS, "--begin", "0", "--end", "200",
           "--step-length", "1.0", "--no-step-log", "true"]
    traci.start(cmd)
    # force the "incident" program on ax4, whose offset (43.3) is non-degenerate
    traci.trafficlight.setProgram("ax4", "incident")
    logic = [l for l in traci.trafficlight.getAllProgramLogics("ax4") if l.programID == "incident"][0]
    phases = [(p.duration, p.state) for p in logic.phases]
    cycle = sum(d for d, s in phases)
    offset = 43.3

    prev_state = None
    onset_times = []
    for t in range(0, 190):
        traci.simulationStep()
        st = traci.trafficlight.getRedYellowGreenState("ax4")
        if prev_state is not None and st != prev_state and "G" in st and "G" not in (prev_state or ""):
            onset_times.append(traci.simulation.getTime())
        prev_state = st
    traci.close()

    print("observed green-onset times (any-G transitions):", onset_times[:6])

    # predicted onset times under each convention: phase0 starts at local
    # time 0; find all t in [0, 2*cycle] with (t - offset) % cycle == 0 (sub
    # convention) or (t + offset) % cycle == 0 (add convention), restricted
    # to when phase index 0 (first listed phase, which is a green phase here)
    # is active -- since our phase list's first phase is green (see below).
    print("phase0 state:", phases[0][1], "is green:", "G" in phases[0][1])
    pred_sub = [t for t in range(0, 190) if (t - offset) % cycle < 1.0]
    pred_add = [t for t in range(0, 190) if (t + offset) % cycle < 1.0]
    print("predicted onsets, SUBTRACT convention (t-offset)%C:", pred_sub)
    print("predicted onsets, ADD convention (t+offset)%C:", pred_add)


if __name__ == "__main__":
    main()
