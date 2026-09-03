#!/usr/bin/env python3
"""
Analyze the SUMO rail-road grade-crossing simulation.

Verifies the coupling between train passages and road-vehicle stopping, quantifies
per-closure and total train-induced road delay, and compares with-trains vs
without-trains on identical road demand.

Outputs (to ../outputs):
  - queue_timeseries.png : road queue length vs time, train-in-block bands marked
  - results.md           : text summary a critic can read

Run:  python3 analyze.py
"""
import os, sys
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "outputs"))

X_CROSS = 1200.0                 # compiled x-coordinate of crossing junction X
RAIL_LANES = {"W_X_0", "X_E_0", "E_X_0", "X_W_0"}
ROAD_APPROACH_LANES = {"N_X_0", "S_X_0"}
# Train "in crossing block": front position within this band around X so the
# 120 m train body overlaps the junction.
BLOCK_LO, BLOCK_HI = X_CROSS - 60.0, X_CROSS + 120.0
HALT_SPEED = 0.1                 # m/s below which a road vehicle is "stopped"


def parse_fcd(path):
    """Return per-timestep: {t: {'trains': {id: x}, 'road_halted': int, 'road_on_appr': int}}."""
    series = {}
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag != "timestep":
            continue
        t = float(elem.get("time"))
        trains = {}
        road_halted = 0
        for v in elem.findall("vehicle"):
            lane = v.get("lane")
            vid = v.get("id")
            if v.get("type") == "train":
                trains[vid] = float(v.get("x"))
            elif lane in ROAD_APPROACH_LANES:
                if float(v.get("speed")) < HALT_SPEED:
                    road_halted += 1
        series[t] = {"trains": trains, "road_halted": road_halted}
        elem.clear()
    return series


def train_block_windows(series):
    """Per train: (enter_t, exit_t) while its front x is within the crossing block."""
    active = {}   # tid -> enter_t
    windows = {}  # tid -> (enter, exit)
    for t in sorted(series):
        present = set()
        for tid, x in series[t]["trains"].items():
            if BLOCK_LO <= x <= BLOCK_HI:
                present.add(tid)
                if tid not in active:
                    active[tid] = t
        for tid in list(active):
            if tid not in present:
                windows[tid] = (active[tid], t - 1.0)
                del active[tid]
    for tid, enter in active.items():
        windows[tid] = (enter, max(series))
    return windows


def road_halt_intervals(series):
    """Contiguous [t0,t1] intervals where >=1 road approach vehicle is stopped."""
    intervals = []
    cur = None
    for t in sorted(series):
        halted = series[t]["road_halted"] > 0
        if halted and cur is None:
            cur = t
        elif not halted and cur is not None:
            intervals.append((cur, t - 1.0))
            cur = None
    if cur is not None:
        intervals.append((cur, max(series)))
    return intervals


def overlap(a, b):
    lo = max(a[0], b[0]); hi = min(a[1], b[1])
    return max(0.0, hi - lo)


def parse_tripinfo(path):
    """Road-vehicle (car) trips: list of dicts with waitingTime, timeLoss, duration."""
    rows = []
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag != "tripinfo":
            continue
        if elem.get("vType") == "car":
            rows.append({
                "id": elem.get("id"),
                "waitingTime": float(elem.get("waitingTime")),
                "timeLoss": float(elem.get("timeLoss")),
                "duration": float(elem.get("duration")),
                "depart": float(elem.get("depart")),
            })
        elem.clear()
    return rows


def parse_e2_queue(path):
    """Sum maxJamLengthInVehicles across both approach detectors per 1s interval."""
    q = {}
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag != "interval":
            continue
        t = float(elem.get("begin"))
        n = int(elem.get("maxJamLengthInVehicles"))
        q[t] = q.get(t, 0) + n
        elem.clear()
    return q


def main():
    fcd = parse_fcd(os.path.join(OUT, "fcd_with.xml"))
    tw = train_block_windows(fcd)
    halts = road_halt_intervals(fcd)
    queue = parse_e2_queue(os.path.join(OUT, "e2_with.xml"))

    trip_with = parse_tripinfo(os.path.join(OUT, "tripinfo_with.xml"))
    trip_without = parse_tripinfo(os.path.join(OUT, "tripinfo_without.xml"))

    # ---- Coupling: match each road-halt interval to an overlapping train window
    lines = []
    def P(s=""):
        print(s); lines.append(s)

    P("# Rail-Road Grade Crossing - Analysis Results")
    P()
    P("## (a) Compiled junction type")
    net = open(os.path.join(HERE, "cross.net.xml")).read()
    import re
    m = re.search(r'<junction id="X" type="([^"]+)"', net)
    jt = m.group(1) if m else "NOT FOUND"
    n_tls = net.count("tlLogic")
    P(f"- Junction X compiled type = **{jt}**  (tlLogic elements in net: {n_tls})")
    P()

    P("## (b) Train-in-crossing-block windows (from FCD, front x in "
      f"[{BLOCK_LO:.0f},{BLOCK_HI:.0f}] around X@{X_CROSS:.0f})")
    for tid in sorted(tw, key=lambda k: tw[k][0]):
        e, x = tw[tid]
        P(f"- {tid}: block occupied {e:.0f}s -> {x:.0f}s  (dur {x-e:.0f}s)")
    P()

    P("## (b) Road-approach stop intervals and their overlap with a train window")
    per_closure = []
    matched = 0
    for (h0, h1) in halts:
        # halted vehicle-seconds during this closure
        vs = sum(fcd[t]["road_halted"] for t in fcd if h0 <= t <= h1)
        # best-overlapping train
        best_tid, best_ov = None, 0.0
        for tid, w in tw.items():
            ov = overlap((h0, h1), w)
            if ov > best_ov:
                best_ov, best_tid = ov, tid
        if best_tid is not None:
            matched += 1
        per_closure.append({"h0": h0, "h1": h1, "veh_sec": vs,
                            "train": best_tid, "ov": best_ov})
        P(f"- road stopped {h0:.0f}s->{h1:.0f}s (dur {h1-h0:.0f}s, "
          f"{vs:.0f} veh-s halted) <=> {best_tid} (overlap {best_ov:.0f}s)")
    P()
    P(f"=> {matched}/{len(halts)} road-stop intervals coincide with a train-in-block window")
    P()

    # ---- Per-closure and total delay
    tot_veh_sec = sum(c["veh_sec"] for c in per_closure)
    nclos = len(per_closure)
    P("## (c) Train-induced road delay")
    P(f"- Gate closures observed: {nclos}")
    P(f"- Total halted vehicle-seconds at the approach (FCD): {tot_veh_sec:.0f} veh-s")
    if nclos:
        P(f"- Mean halted vehicle-seconds per closure: {tot_veh_sec/nclos:.1f} veh-s")
    P()

    # tripinfo-based (robust, whole-network) delay attributable to trains
    def agg(rows):
        n = len(rows)
        wsum = sum(r["waitingTime"] for r in rows)
        lsum = sum(r["timeLoss"] for r in rows)
        return n, wsum, lsum
    nW, wW, lW = agg(trip_with)
    nN, wN, lN = agg(trip_without)
    P("## (d) With-trains vs without-trains (identical road demand, seed=42)")
    P(f"- Road vehicles completed:      with={nW}   without={nN}")
    P(f"- Mean waiting time / veh:      with={wW/nW:.2f}s   without={wN/nN:.2f}s")
    P(f"- Mean time loss / veh:         with={lW/nW:.2f}s   without={lN/nN:.2f}s")
    P(f"- Total road waiting time:      with={wW:.0f}s   without={wN:.0f}s")
    train_induced_total = wW - wN
    P(f"- Train-induced TOTAL road waiting (with-without): {train_induced_total:.0f}s")
    if nclos:
        P(f"- Train-induced waiting PER closure: {train_induced_total/nclos:.1f}s")
    P(f"- Extra mean waiting per vehicle due to crossing: {wW/nW - wN/nN:.2f}s")
    P()

    # ---- Plot
    ts = sorted(queue)
    qv = [queue[t] for t in ts]
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(ts, qv, color="#1f77b4", lw=1.2, label="Road queue (max jam veh, both approaches)")
    for tid in sorted(tw, key=lambda k: tw[k][0]):
        e, x = tw[tid]
        ax.axvspan(e, x, color="#d62728", alpha=0.25)
    # legend proxy for train bands
    ax.axvspan(-10, -9, color="#d62728", alpha=0.25, label="Train in crossing block")
    ax.set_xlim(0, max(ts))
    ax.set_xlabel("Simulation time (s)")
    ax.set_ylabel("Queued road vehicles")
    ax.set_title("Road-approach queue vs. train passages at the rail_crossing")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    png = os.path.join(OUT, "queue_timeseries.png")
    fig.savefig(png, dpi=130)
    P(f"[plot written] {png}")

    with open(os.path.join(OUT, "results.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n[results written]", os.path.join(OUT, "results.md"))


if __name__ == "__main__":
    main()
