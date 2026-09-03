#!/usr/bin/env python3
"""VERIFY the event log and the controller, independently of the log itself.

Four checks, all against sources the event log does NOT use:

 V1  NEMA phase-name cross-check. SUMO's NEMA controller exposes its own
     internal active phase pair via traci.trafficlight.getPhaseName()
     (e.g. "2+6"). We compare that INDEPENDENT source against the
     link-state-derived begin-green / begin-yellow events the logger writes.
     Every logged code-1 (begin green) for phase p must coincide (within one
     0.1 s step) with p appearing in the controller's own phase-name string.

 V2  Coordinated-vs-actuated signature (the barrier2Phases ambiguity).
     Coordinated phases 2/6 must show long, stable green windows; the
     non-coordinated group (4/8, 3/7, 1/5) must vary and be capped by maxDur.

 V3  Offset / cycle-reference convention. Measured coordinated-phase
     begin-green time-in-cycle at each junction is compared against the
     configured offset, to establish empirically what SUMO's NEMA `offset`
     means (needed before any PCD or retiming arithmetic).

 V4  Detector event fidelity. Advance-detector 82 (Detector On) event counts
     are compared against SUMO's own induction-loop passage counters
     (getIntervalVehicleNumber), an independent count.
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402
import traci  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_signals import build_states, PHASE_ORDER, PHASE_LABEL  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
STEP = 0.1
J = ["J0", "J1", "J2", "J3"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--tls-add", required=True)
    ap.add_argument("--end", type=float, default=1600.0)
    ap.add_argument("--warmup", type=float, default=400.0)
    args = ap.parse_args()

    plan = json.load(open(args.plan))
    C = plan["cycle"]
    net_f = os.path.join(ROOT, "outputs", "net", "arterial.net.xml")
    rou_f = os.path.join(ROOT, "outputs", "demand", "demand.rou.xml")
    det_f = os.path.join(ROOT, "outputs", "det", "detectors.add.xml")

    net = sumolib.net.readNet(net_f)
    phase_links = {}
    for tls in net.getTrafficLights():
        jid = tls.getID()
        _, _, _, pl = build_states(tls, plan["junctions"][jid].get("permissive_left", False))
        phase_links[jid] = pl

    det_cfg = list(csv.DictReader(open(os.path.join(ROOT, "outputs", "det", "detector_config.csv"))))
    adv = [(r["det_id"], r["signal_id"], int(r["channel"]), r["approach_dir"])
           for r in det_cfg if r["det_class"] == "advance"]

    traci.start(["sumo", "-n", net_f, "-r", rou_f, "-a", f"{det_f},{args.tls_add}",
                 "--step-length", str(STEP), "--end", str(args.end), "--seed", "42",
                 "--no-step-log", "true", "--time-to-teleport", "300"])

    ph_state = {j: {p: "R" for p in range(1, 9)} for j in J}
    g0 = {j: {p: None for p in range(1, 9)} for j in J}
    windows = defaultdict(list)          # (j,p) -> [green durations]
    onsets = defaultdict(list)           # (j,p) -> [absolute onset times]
    v1_checked = v1_bad = 0
    det_on = {d: False for d, _, _, _ in adv}
    on_counts = defaultdict(int)

    t = 0.0
    for _ in range(int(round(args.end / STEP))):
        traci.simulationStep()
        t = round(t + STEP, 1)
        for jid in J:
            st = traci.trafficlight.getRedYellowGreenState(jid)
            pname = traci.trafficlight.getPhaseName(jid)      # NEMA's OWN phase pair
            active = {int(x) for x in pname.replace("+", " ").split() if x.strip().isdigit()}
            for p in PHASE_ORDER:
                idxs = phase_links[jid][p]
                has_G = any(st[i] == "G" for i in idxs)
                if has_G and ph_state[jid][p] != "G":
                    ph_state[jid][p] = "G"
                    g0[jid][p] = t
                    if t >= args.warmup:
                        onsets[(jid, p)].append(t)
                    # V1: at a logged begin-green, NEMA's own phase name must contain p
                    v1_checked += 1
                    if p not in active:
                        v1_bad += 1
                elif ph_state[jid][p] == "G" and not has_G:
                    if t >= args.warmup and g0[jid][p] is not None:
                        windows[(jid, p)].append(round(t - g0[jid][p], 1))
                    ph_state[jid][p] = "R"
        for did, _, _, _ in adv:
            occ = traci.inductionloop.getLastStepVehicleNumber(did) > 0
            if occ and not det_on[did]:
                on_counts[did] += 1
            det_on[did] = occ

    # V4 independent counts before closing
    indep = {did: traci.inductionloop.getIntervalVehicleNumber(did) for did, _, _, _ in adv}
    traci.close()

    print("=" * 78)
    print("V1  NEMA phase-name cross-check (logger's link-state green vs controller's own phase name)")
    print(f"    begin-green transitions checked : {v1_checked}")
    print(f"    disagreements                   : {v1_bad}")
    print(f"    -> {'PASS' if v1_bad == 0 else 'FAIL'}")

    print()
    print("V2  Coordinated-vs-actuated green-window signature")
    print(f"    {'junction':9s} {'phase':16s} {'n':>4s} {'mean':>7s} {'sd':>6s} {'min':>6s} {'max':>6s} {'maxDur':>7s}")
    import statistics as stats
    for jid in J:
        for p in PHASE_ORDER:
            w = windows[(jid, p)]
            if not w:
                continue
            md = plan["junctions"][jid]["splits"][str(p)] - 5
            tagp = "COORD" if p in (2, 6) else "act"
            print(f"    {jid:9s} {str(p)+' '+PHASE_LABEL[p]+' '+tagp:16s} {len(w):4d} "
                  f"{stats.mean(w):7.2f} {(stats.pstdev(w) if len(w)>1 else 0):6.2f} "
                  f"{min(w):6.1f} {max(w):6.1f} {md:7.1f}")

    print()
    print("V3  Offset / cycle-reference convention (coordinated phase 6 = EBT)")
    print(f"    {'junction':9s} {'offset':>7s} {'mean onset mod C':>18s} {'sd':>6s}  "
          f"{'(onset - offset) mod C':>23s}")
    for jid in J:
        o = plan["junctions"][jid]["offset"]
        os_ = [x % C for x in onsets[(jid, 6)]]
        if not os_:
            continue
        # circular mean
        import math
        ang = [2 * math.pi * x / C for x in os_]
        mx = sum(math.cos(a) for a in ang) / len(ang)
        my = sum(math.sin(a) for a in ang) / len(ang)
        cm = (math.atan2(my, mx) * C / (2 * math.pi)) % C
        dev = [((x - cm + C / 2) % C) - C / 2 for x in os_]
        print(f"    {jid:9s} {o:7.1f} {cm:18.2f} {stats.pstdev(dev) if len(dev)>1 else 0:6.2f}  "
              f"{(cm - o) % C:23.2f}")

    print()
    print("V4  Advance-detector event fidelity (82 'Detector On' rising edges vs SUMO's own counter)")
    tot_ev = tot_in = 0
    worst = 0
    for did, sig, ch, d in adv:
        a, b = on_counts[did], indep[did]
        tot_ev += a
        tot_in += b
        worst = max(worst, abs(a - b))
    print(f"    detectors={len(adv)}  rising edges={tot_ev}  SUMO interval counter={tot_in}  "
          f"max per-detector |diff|={worst}")
    print(f"    -> {'PASS' if worst == 0 else 'CHECK'}")


if __name__ == "__main__":
    main()
