"""Bus time-space diagram from FCD + per-stop delay decomposition table.

Every second of every bus trajectory is classified into exactly one of
    DWELL           inside a stop-output [started, ended] window
    SIGNAL_STOP     halted (v < 0.3 m/s) within `SIG_ZONE` m upstream of a signal
    OTHER_STOP      halted anywhere else (mid-block queueing / following)
    SLOW            moving below 80% of free-flow speed
    RUNNING         moving at >= 80% of free-flow speed
so running time, dwell time and signal delay are separated per segment rather
than asserted.  Signal green windows for the EB through movement are drawn from
the COMPILED plan's offsets, using SUMO's (t - offset) mod C convention.
"""
import os
import sys
import json
import csv
import xml.etree.ElementTree as ET
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg, build_scenario, signal_x  # noqa: E402
from runner import run_cell  # noqa: E402

ROOT = os.path.dirname(HERE)
FIG = os.path.join(ROOT, "figures")
RES = os.path.join(ROOT, "results")
SIG_ZONE = 130.0
STATES = ["RUNNING", "SLOW", "SIGNAL_STOP", "OTHER_STOP", "DWELL"]
COLORS = {"RUNNING": "#2b7bba", "SLOW": "#7fb3d5", "SIGNAL_STOP": "#d1495b",
          "OTHER_STOP": "#f4a259", "DWELL": "#2a9d8f"}


def bus_traj(fcd, spans):
    """id -> [(t, x_corridor, v)] for buses only."""
    off = {e: xa for e, xa, xb, _ in spans}
    tr = defaultdict(list)
    for _, el in ET.iterparse(fcd, events=("end",)):
        if el.tag != "timestep":
            continue
        t = float(el.get("time"))
        for v in el:
            if v.get("type") != "bus":
                continue
            lane = v.get("lane") or ""
            e = lane.rsplit("_", 1)[0]
            if e not in off:
                continue
            # FCD x is the network x coordinate, which IS the corridor coordinate
            tr[v.get("id")].append((t, float(v.get("x")), float(v.get("speed"))))
        el.clear()
    for k in tr:
        tr[k].sort()
    return tr


def classify(tr, stopwins, sigxs, vmax):
    out = {}
    for bid, seq in tr.items():
        wins = stopwins.get(bid, [])
        lab = []
        for t, x, v in seq:
            st = None
            for (s0, s1, sid) in wins:
                if s0 - 0.5 <= t <= s1 + 0.5:
                    st = "DWELL"
                    break
            if st is None:
                if v < 0.3:
                    near = any(0 <= sx - x <= SIG_ZONE for sx in sigxs)
                    st = "SIGNAL_STOP" if near else "OTHER_STOP"
                elif v < 0.8 * vmax:
                    st = "SLOW"
                else:
                    st = "RUNNING"
            lab.append((t, x, v, st))
        out[bid] = lab
    return out


def main():
    cfg = Cfg(stop_placement="farside", stop_type="inlane", lanes_art=2,
              q_art=1200.0, q_cross=250.0, pax_rate=1200.0, headway=180.0)
    d = os.path.join(ROOT, "runs", "timespace_farside")
    m = run_cell(cfg, d, 1, keep=("fcdbus",))
    sc = build_scenario(cfg, d, 1)   # rebuild metadata (same seed, same files)

    rows = sorted([s.attrib for s in ET.parse(os.path.join(d, "stopinfo.xml")).getroot()
                   if s.attrib.get("busStop")], key=lambda r: (r["id"], float(r["started"])))
    stopwins = defaultdict(list)
    for r in rows:
        stopwins[r["id"]].append((float(r["started"]), float(r["ended"]), r["busStop"]))
    spans = sc["info"]["eb_spans"]
    sigxs = [signal_x(cfg, j) for j in range(1, cfg.n_signals + 1)]
    tr = bus_traj(os.path.join(d, "fcd.xml"), spans)
    lab = classify(tr, stopwins, sigxs, cfg.speed_art)

    # ---------------- per-stop / per-segment decomposition -------------------
    stops = sc["stops"]
    stop_x = {s["id"]: s["x"] for s in stops}
    order = sorted(stops, key=lambda s: s["x"])
    dec = defaultdict(lambda: defaultdict(float))
    counts = defaultdict(int)
    for bid, seq in lab.items():
        # segment i = [end of stop i-1 (or trip start), end of stop i]; it therefore
        # contains the approach running/slow/signal time AND the dwell at stop i.
        wins = sorted(stopwins.get(bid, []), key=lambda w: w[0])
        bounds = []
        prev = seq[0][0] - 1 if seq else 0.0
        for (s0, s1, sid) in wins:
            bounds.append((prev, s1, sid))
            prev = s1
            counts[sid] += 1
        bounds.append((prev, float("inf"), "after_last_stop"))
        for t, x, v, st in seq:
            seg = next((sid for (a, b, sid) in bounds if a < t <= b), "after_last_stop")
            dec[seg][st] += 1.0
            dec[seg]["total"] += 1.0
    nbus = len(lab)
    table = []
    for s in order + [{"id": "after_last_stop", "x": None}]:
        sid = s["id"]
        dd = dec.get(sid)
        if not dd:
            continue
        tot = dd["total"]
        row = {"segment_ending_at": sid, "stop_x_m": s["x"], "n_bus_services": counts.get(sid, 0),
               "mean_segment_time_s": round(tot / max(nbus, 1), 2)}
        for st in STATES:
            row[f"{st}_s"] = round(dd.get(st, 0.0) / max(nbus, 1), 2)
            row[f"{st}_pct"] = round(100.0 * dd.get(st, 0.0) / tot, 1) if tot else 0.0
        table.append(row)
    with open(os.path.join(RES, "per_stop_decomposition.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0].keys()))
        w.writeheader()
        w.writerows(table)
    json.dump({"cfg": cfg.__dict__, "n_buses_traced": nbus, "table": table,
               "state_definitions": {
                   "DWELL": "inside a stop-output [started,ended] window",
                   "SIGNAL_STOP": f"v<0.3 m/s within {SIG_ZONE} m upstream of a signal",
                   "OTHER_STOP": "v<0.3 m/s elsewhere",
                   "SLOW": "0.3 <= v < 0.8*free-flow",
                   "RUNNING": "v >= 0.8*free-flow"}},
              open(os.path.join(RES, "per_stop_decomposition.json"), "w"), indent=1)
    print("per-stop decomposition:")
    for r in table:
        print(f"  {r['segment_ending_at']:18s} T={r['mean_segment_time_s']:7.2f}s "
              f"run={r['RUNNING_s']:6.2f} slow={r['SLOW_s']:6.2f} "
              f"sig={r['SIGNAL_STOP_s']:6.2f} other={r['OTHER_STOP_s']:6.2f} "
              f"dwell={r['DWELL_s']:6.2f}")

    # ------------------------------- figure ---------------------------------
    os.makedirs(FIG, exist_ok=True)
    fig, ax = plt.subplots(figsize=(14, 8))
    t0, t1 = 900.0, 1900.0
    C = cfg.cycle
    for j in range(1, cfg.n_signals + 1):
        off = sc["plan"][f"J{j}"]["offset"]
        sx = signal_x(cfg, j)
        k = int((t0 - off) // C) - 1
        while off + k * C < t1:
            g0 = off + k * C
            g1 = g0 + cfg.art_green
            if g1 > t0 and g0 < t1:
                ax.plot([max(g0, t0), min(g1, t1)], [sx-14, sx-14], color="#26a269", lw=5,
                        solid_capstyle="butt", alpha=.85, zorder=1)
            r0, r1 = g1, off + (k + 1) * C
            if r1 > t0 and r0 < t1:
                ax.plot([max(r0, t0), min(r1, t1)], [sx-14, sx-14], color="#c01c28", lw=5,
                        solid_capstyle="butt", alpha=.55, zorder=1)
            k += 1
    for s in stops:
        ax.axhline(s["x"], color="#999", ls=":", lw=.8, zorder=0)
        ax.text(t1 + 8, s["x"], s["id"], fontsize=8, va="center", color="#555")
    for bid, seq in lab.items():
        seq = [p for p in seq if t0 <= p[0] <= t1]
        if len(seq) < 2:
            continue
        for i in range(len(seq) - 1):
            t, x, v, st = seq[i]
            t2, x2, _, _ = seq[i + 1]
            ax.plot([t, t2], [x, x2], color=COLORS[st], lw=2.6, solid_capstyle="round", zorder=3)
    ax.set_xlim(t0, t1 + 60)
    ax.set_ylim(-80, signal_x(cfg, cfg.n_signals) + 340)
    ax.set_xlabel("simulation time (s)")
    ax.set_ylabel("corridor position x (m), eastbound")
    ax.set_title("Bus time-space diagram (far-side in-lane stops, 2 lanes/dir, "
                 "q=1200 veh/h/dir, 20 bus/h)\ncolour = state; thick bars = EB through-green (green) / red")
    handles = [Line2D([], [], color=COLORS[s], lw=3, label=s) for s in STATES]
    handles += [Line2D([], [], color="#26a269", lw=6, label="EB green"),
                Line2D([], [], color="#c01c28", lw=6, alpha=.55, label="EB red")]
    ax.legend(handles=handles, loc="upper left", fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "bus_time_space.png"), dpi=150)
    print("wrote", os.path.join(FIG, "bus_time_space.png"))

    # ---- a second panel: near-side vs far-side, same seed --------------------
    fig2, axs = plt.subplots(1, 3, figsize=(18, 6), sharey=True)
    for ax2, place in zip(axs, ("nearside", "farside", "midblock")):
        c2 = Cfg(**{**cfg.__dict__, "stop_placement": place})
        d2 = os.path.join(ROOT, "runs", f"timespace_{place}")
        run_cell(c2, d2, 1, keep=("fcdbus",))
        sc2 = build_scenario(c2, d2, 1)
        rows2 = sorted([s.attrib for s in ET.parse(os.path.join(d2, "stopinfo.xml")).getroot()
                        if s.attrib.get("busStop")], key=lambda r: (r["id"], float(r["started"])))
        sw2 = defaultdict(list)
        for r in rows2:
            sw2[r["id"]].append((float(r["started"]), float(r["ended"]), r["busStop"]))
        tr2 = bus_traj(os.path.join(d2, "fcd.xml"), sc2["info"]["eb_spans"])
        lab2 = classify(tr2, sw2, sigxs, c2.speed_art)
        for j in range(1, c2.n_signals + 1):
            off = sc2["plan"][f"J{j}"]["offset"]
            sx = signal_x(c2, j)
            k = int((t0 - off) // C) - 1
            while off + k * C < t1:
                g0, g1 = off + k * C, off + k * C + c2.art_green
                if g1 > t0 and g0 < t1:
                    ax2.plot([max(g0, t0), min(g1, t1)], [sx, sx], color="#26a269", lw=5, alpha=.8)
                r0, r1 = g1, off + (k + 1) * C
                if r1 > t0 and r0 < t1:
                    ax2.plot([max(r0, t0), min(r1, t1)], [sx, sx], color="#c01c28", lw=5, alpha=.5)
                k += 1
        for s in sc2["stops"]:
            ax2.axhline(s["x"], color="#999", ls=":", lw=.8)
        for bid, seq in lab2.items():
            seq = [p for p in seq if t0 <= p[0] <= t1]
            for i in range(len(seq) - 1):
                t, x, v, st = seq[i]
                t2b, x2, _, _ = seq[i + 1]
                ax2.plot([t, t2b], [x, x2], color=COLORS[st], lw=2.2)
        ax2.set_title(place)
        ax2.set_xlabel("time (s)")
        ax2.set_xlim(t0, t1)
    axs[0].set_ylabel("corridor position x (m)")
    axs[0].legend(handles=[Line2D([], [], color=COLORS[s], lw=3, label=s) for s in STATES],
                  fontsize=8, loc="upper left")
    fig2.suptitle("Bus trajectories: near-side vs far-side vs mid-block stops (identical seed and demand)")
    fig2.tight_layout()
    fig2.savefig(os.path.join(FIG, "bus_time_space_placements.png"), dpi=140)
    print("wrote", os.path.join(FIG, "bus_time_space_placements.png"))


if __name__ == "__main__":
    main()
