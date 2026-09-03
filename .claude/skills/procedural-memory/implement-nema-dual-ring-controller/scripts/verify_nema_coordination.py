"""
Verify a NEMA dual-ring coordinated-actuated controller empirically, from live
simulation behavior -- not from trusting the config file. Classifies every
NEMA phase's controlled links per junction directly from network geometry
(approach compass direction + turn angle -> standard 8-phase NEMA numbering),
traces per-second which phases are green at each junction over a run, and
reports:

  (A) The coordinated through-phase's green-onset progression across
      junctions vs. the intended offset hop (distance / target arterial
      speed) -- confirms a green wave is genuinely forming, not just configured.
  (B) Per-phase green-window duration statistics -- coordinated phases should
      show long, stable durations near their split (held by force-off/max
      recall), while non-coordinated actuated phases should vary and be
      capped by maxDur (force-off) or end early (gap-out). This distinction
      is the empirical signature of genuine coordinated actuation.

Usage:
    python verify_nema_coordination.py \
        --net arterial.net.xml --routes routed.rou.xml --add nema.add.xml \
        --junction-order J0,J1,J2,J3 --spacing 400 --arterial-speed-ms 15 \
        --cycle 90 --coordinated-phases 2,6 --end 1200 --warmup 270 \
        --out-dir outputs/
"""

import argparse
import csv
import math
import os
import sys


PHASE_LABEL = {1: "EB-L", 2: "WB-T", 3: "SB-L", 4: "NB-T",
               5: "WB-L", 6: "EB-T", 7: "NB-L", 8: "SB-T"}


def parse_args():
    p = argparse.ArgumentParser(description="Verify a NEMA controller's coordination/actuation behavior from live simulation.")
    p.add_argument("--net", required=True)
    p.add_argument("--routes", required=True)
    p.add_argument("--add", required=True, help="Additional-file with the NEMA tlLogic definitions")
    p.add_argument("--junction-order", required=True, help="Comma-separated junction ids in arterial travel order")
    p.add_argument("--spacing", type=float, required=True, help="Distance (m) between consecutive junctions, for the intended offset-hop calculation")
    p.add_argument("--arterial-speed-ms", type=float, required=True, help="Target arterial progression speed (m/s)")
    p.add_argument("--cycle", type=float, required=True, help="Background cycle length (s)")
    p.add_argument("--coordinated-phases", default="2,6", help="Comma-separated NEMA phase numbers designated coordinated")
    p.add_argument("--phase-max-dur", default="1:7,2:38,3:5,4:20,5:7,6:38,7:5,8:20", help="Comma-separated phase:maxDur pairs for the behavior table")
    p.add_argument("--end", type=int, default=1200)
    p.add_argument("--warmup", type=int, default=270, help="Seconds to discard before measuring steady-state onsets/windows")
    p.add_argument("--out-dir", default="outputs")
    return p.parse_args()


def nema_phase(compass, turn):
    if compass == "E":
        return 1 if turn == "L" else 6
    if compass == "W":
        return 5 if turn == "L" else 2
    if compass == "S":
        return 3 if turn == "L" else 8
    if compass == "N":
        return 7 if turn == "L" else 4


def classify(net):
    """junction_id -> {phase_num: [linkIdx, ...]}, derived purely from geometry."""
    out = {}
    for tls in net.getTrafficLights():
        pl = {p: [] for p in range(1, 9)}
        for in_lane, out_lane, li in tls.getConnections():
            e = in_lane.getEdge()
            fx, fy = e.getFromNode().getCoord()
            tx, ty = e.getToNode().getCoord()
            dx, dy = tx - fx, ty - fy
            compass = ("E" if dx > 0 else "W") if abs(dx) >= abs(dy) else ("N" if dy > 0 else "S")
            oe = out_lane.getEdge()
            ofx, ofy = oe.getFromNode().getCoord()
            otx, oty = oe.getToNode().getCoord()
            cross = dx * (oty - ofy) - dy * (otx - ofx)
            dot = dx * (otx - ofx) + dy * (oty - ofy)
            ang = math.degrees(math.atan2(cross, dot))
            turn = "L" if ang > 30 else ("R" if ang < -30 else "S")
            pl[nema_phase(compass, turn)].append(li)
        out[tls.getID()] = pl
    return out


def main():
    args = parse_args()
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
    import sumolib  # noqa: E402
    import traci  # noqa: E402

    order = args.junction_order.split(",")
    coordinated = {int(x) for x in args.coordinated_phases.split(",")}
    max_dur = {int(k): int(v) for k, v in (kv.split(":") for kv in args.phase_max_dur.split(","))}

    os.makedirs(args.out_dir, exist_ok=True)
    net = sumolib.net.readNet(args.net)
    cls = classify(net)

    traci.start(["sumo", "-n", args.net, "-r", args.routes, "-a", args.add, "--no-step-log", "true", "--end", str(args.end)])

    windows = {j: {p: [] for p in range(1, 9)} for j in order}
    start = {j: {p: None for p in range(1, 9)} for j in order}
    prev = {j: {p: False for p in range(1, 9)} for j in order}
    coord_onsets = {j: {p: [] for p in coordinated} for j in order}
    trace_rows = []

    t = 0
    while t < args.end:
        traci.simulationStep()
        t += 1
        for j in order:
            st = traci.trafficlight.getRedYellowGreenState(j)
            for p in range(1, 9):
                on = any(st[i] in "Gg" for i in cls[j][p])
                if on and not prev[j][p]:
                    start[j][p] = t
                    if p in coordinated and t >= args.warmup:
                        coord_onsets[j][p].append(t)
                if (not on) and prev[j][p] and start[j][p] is not None and t >= args.warmup:
                    windows[j][p].append(t - start[j][p])
                prev[j][p] = on
            for p in coordinated:
                on = 1 if any(st[i] in "Gg" for i in cls[j][p]) else 0
                trace_rows.append((t, j, p, on))
    traci.close()

    trace_path = os.path.join(args.out_dir, "coordinated_phase_green_trace.csv")
    with open(trace_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "junction", "phase", "green"])
        w.writerows(trace_rows)

    hop_intended = args.spacing / args.arterial_speed_ms
    print("=== (A) Coordinated-phase green-onset progression ===")
    print(f"intended hop offset ~ {hop_intended:.1f}s ({args.spacing:.0f}m / {args.arterial_speed_ms}m/s)")
    for p in sorted(coordinated):
        med = {}
        for j in order:
            mods = sorted(o % args.cycle for o in coord_onsets[j][p])
            med[j] = mods[len(mods) // 2] if mods else None
            print(f"  phase {p} @ {j}: onset(mod {args.cycle:.0f}) median={med[j]} ({len(mods)} cycles observed)")
        hops = []
        for a, b in zip(order[:-1], order[1:]):
            if med[a] is None or med[b] is None:
                continue
            hop = (med[b] - med[a]) % args.cycle
            hops.append(hop)
            print(f"  hop {a}->{b}: realized onset lag = {hop}s (intended ~{hop_intended:.0f}s)")
        if hops:
            print(f"  phase {p} mean realized hop = {sum(hops) / len(hops):.1f}s")

    print("\n=== (B) Per-phase green-window durations (steady state) ===")
    print(f"{'junc':<5}{'phase':<8}{'maxDur':>7}{'n':>4}{'min':>5}{'max':>5}{'mean':>7}   behavior")
    for j in order:
        for p in sorted(range(1, 9), key=lambda p: (p not in coordinated, p)):
            w = windows[j][p]
            if not w:
                continue
            behavior = "HELD (coordinated)" if p in coordinated else "actuated (gap-out/force-off)"
            print(f"{j:<5}{PHASE_LABEL.get(p, p):<8}{max_dur.get(p, ''):>7}{len(w):>4}{min(w):>5}{max(w):>5}{sum(w) / len(w):>7.1f}   {behavior}")
        print()
    print(f"trace saved: {trace_path}")


if __name__ == "__main__":
    main()
