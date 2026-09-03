"""H2 mechanism: where does the bus's time actually go, by stop placement, with
and without TSP?  Uses the same FCD state classification as timespace.py so
"dwell", "signal delay" and "running" are measured, not asserted.
"""
import os
import sys
import json
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg, build_scenario, signal_x  # noqa: E402
from runner import run_cell  # noqa: E402
from timespace import bus_traj, classify, STATES  # noqa: E402

ROOT = os.path.dirname(HERE)
RES = os.path.join(ROOT, "results")
SEEDS = [1, 2, 3, 4, 5, 6]


def one(cfg, d, seed, tsp):
    run_cell(cfg, d, seed, tsp=tsp, keep=("fcdbus",))
    sc = build_scenario(cfg, d, seed)
    rows = sorted([s.attrib for s in ET.parse(os.path.join(d, "stopinfo.xml")).getroot()
                   if s.attrib.get("busStop")], key=lambda r: (r["id"], float(r["started"])))
    sw = defaultdict(list)
    for r in rows:
        sw[r["id"]].append((float(r["started"]), float(r["ended"]), r["busStop"]))
    sigxs = [signal_x(cfg, j) for j in range(1, cfg.n_signals + 1)]
    lab = classify(bus_traj(os.path.join(d, "fcd.xml"), sc["info"]["eb_spans"]),
                   sw, sigxs, cfg.speed_art)
    os.remove(os.path.join(d, "fcd.xml"))
    tot = defaultdict(float)
    n = 0
    for bid, seq in lab.items():
        if not seq or seq[0][0] < cfg.warmup or seq[0][0] >= cfg.demand_end:
            continue
        n += 1
        for t, x, v, st in seq:
            tot[st] += 1.0
    return {st: round(tot[st] / max(n, 1), 2) for st in STATES} | {"n_buses": n,
            "total_s": round(sum(tot.values()) / max(n, 1), 2)}


def main():
    base = dict(lanes_art=2, q_art=1400.0, q_cross=280.0, pax_rate=1200.0,
                headway=150.0, stop_type="inlane")
    out = {}
    for place in ("nearside", "farside", "midblock"):
        for tsp in ("none", "conditional"):
            acc = defaultdict(list)
            for sd in SEEDS:
                r = one(Cfg(stop_placement=place, **base),
                        os.path.join(ROOT, "runs", f"h2mech_{place}_{tsp}"), sd, tsp)
                for k, v in r.items():
                    acc[k].append(v)
            m = {k: round(sum(v) / len(v), 2) for k, v in acc.items()}
            out[f"{place}/{tsp}"] = m
            print(f"{place:9s} tsp={tsp:11s} total={m['total_s']:7.2f} "
                  f"run={m['RUNNING']:6.2f} slow={m['SLOW']:6.2f} "
                  f"SIGNAL_STOP={m['SIGNAL_STOP']:6.2f} other={m['OTHER_STOP']:5.2f} "
                  f"dwell={m['DWELL']:6.2f}")
    for place in ("nearside", "farside", "midblock"):
        a, b = out[f"{place}/none"], out[f"{place}/conditional"]
        print(f"  {place:9s} TSP effect: signal-stop {a['SIGNAL_STOP']:6.2f} -> {b['SIGNAL_STOP']:6.2f} "
              f"({b['SIGNAL_STOP']-a['SIGNAL_STOP']:+6.2f} s/bus), dwell "
              f"{a['DWELL']:6.2f} -> {b['DWELL']:6.2f}")
        out[f"{place}/tsp_signal_stop_delta"] = round(b["SIGNAL_STOP"] - a["SIGNAL_STOP"], 2)
    json.dump({"seeds": SEEDS, "cfg": base, "by_arm": out},
              open(os.path.join(RES, "h2_mechanism.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
