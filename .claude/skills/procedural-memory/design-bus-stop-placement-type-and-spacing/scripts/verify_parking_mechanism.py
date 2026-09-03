"""What does <stop parking="true"> vs parking="false"> ACTUALLY do to the traffic
stream, and what governs a bay bus's re-entry?

Three independent instrument channels (the methodology transferred from
`model-curbside-delivery-and-lane-blocking-externality`):
  1. stop-output's `parking` attribute (cheapest, but only proves intent was parsed)
  2. laneData occupancy on the exact stop lane (does the bus's dwell show up as
     occupied lane-seconds?)
  3. --lanechange-output filtered to reason `strategic|urgent` (SUMO's own tag for
     "forced off my lane because it was blocked")
plus a 4th, transit-specific one:
  4. bus FCD: time from stop `ended` until the bus is moving again = re-entry
     penalty, swept against car flow to find what governs it.
"""
import os
import sys
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg, build_scenario, SUMO  # noqa: E402

ROOT = os.path.dirname(HERE)
RUNS = os.path.join(ROOT, "runs", "verify_parking")
RES = os.path.join(ROOT, "results")


def run(cfg, outdir, seed, want_fcd=True):
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    sc = build_scenario(cfg, outdir, seed)
    ld = os.path.join(outdir, "meas.add.xml")
    open(ld, "w").write(
        '<additional>\n'
        f'  <laneData id="ld" file="{os.path.join(outdir, "lanedata.xml")}" '
        f'begin="{cfg.warmup}" end="{cfg.demand_end}" excludeEmpty="false"/>\n'
        '</additional>\n')
    opts = [SUMO, "-n", sc["net"], "-a", f'{sc["busstops"]},{ld}',
            "-r", f'{sc["cars"]},{sc["buses"]},{sc["persons"]}',
            "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
            "--summary-output", os.path.join(outdir, "summary.xml"),
            "--stop-output", os.path.join(outdir, "stopinfo.xml"),
            "--lanechange-output", os.path.join(outdir, "lanechange.xml"),
            "--tripinfo-output.write-unfinished", "true",
            "--duration-log.statistics", "true", "--no-step-log", "true",
            "--time-to-teleport", "300", "--seed", str(seed),
            "-e", str(int(cfg.sim_end))]
    if want_fcd:
        opts += ["--fcd-output", os.path.join(outdir, "fcd.xml"),
                 "--fcd-output.attributes", "id,x,speed,lane,type"]
    with open(os.path.join(outdir, "err.txt"), "w") as fe:
        r = subprocess.run(opts, stdout=subprocess.DEVNULL, stderr=fe)
    assert r.returncode == 0, open(os.path.join(outdir, "err.txt")).read()[-3000:]
    return sc


def stop_lane_occupancy(outdir, lane_id):
    root = ET.parse(os.path.join(outdir, "lanedata.xml")).getroot()
    for iv in root.findall("interval"):
        for e in iv.findall("edge"):
            for ln in e.findall("lane"):
                if ln.get("id") == lane_id:
                    return {k: ln.get(k) for k in
                            ("sampledSeconds", "density", "occupancy", "waitingTime",
                             "timeLoss", "speed", "laneChangedFrom", "laneChangedTo")}
    return None


def forced_lane_changes(outdir, from_lane, x_lo, x_hi, t_lo, t_hi):
    p = os.path.join(outdir, "lanechange.xml")
    if not os.path.exists(p):
        return 0, 0
    root = ET.parse(p).getroot()
    tot = 0
    forced = 0
    for ch in root.findall("change"):
        t = float(ch.get("time"))
        if not (t_lo <= t <= t_hi):
            continue
        if ch.get("from") != from_lane:
            continue
        tot += 1
        if "strategic" in (ch.get("reason") or "") or "urgent" in (ch.get("reason") or ""):
            forced += 1
    return tot, forced


def bus_reentry(outdir, stopinfo_rows, thresh=2.0):
    """From bus FCD: seconds between the stop ending and the bus exceeding
    `thresh` m/s, and the peak speed reached within 30 s of the stop end."""
    prof = defaultdict(list)
    for _, el in ET.iterparse(os.path.join(outdir, "fcd.xml"), events=("end",)):
        if el.tag == "timestep":
            t = float(el.get("time"))
            for v in el:
                if v.get("type") == "bus":
                    prof[v.get("id")].append((t, float(v.get("speed"))))
            el.clear()
    out = []
    for r in stopinfo_rows:
        bid = r["id"]
        te = float(r["ended"])
        seq = [(t, s) for t, s in prof.get(bid, []) if te - 1 <= t <= te + 90]
        if not seq:
            continue
        rel = None
        for t, s in seq:
            if t >= te and s > thresh:
                rel = t - te
                break
        out.append({"bus": bid, "stop": r["busStop"], "ended": te,
                    "reentry_s": rel, "parking": r["parking"]})
    vals = [o["reentry_s"] for o in out if o["reentry_s"] is not None]
    return {"n": len(vals), "mean_reentry_s": (sum(vals) / len(vals)) if vals else None,
            "max_reentry_s": max(vals) if vals else None,
            "n_never_moved": sum(1 for o in out if o["reentry_s"] is None),
            "events": out}


def arm(name, cfg, seed, q):
    cfg = Cfg(**{**cfg.__dict__, "q_art": q})
    d = os.path.join(RUNS, f"{name}_q{int(q)}")
    sc = run(cfg, d, seed)
    stop = sc["stops"][2]
    rows = [s.attrib for s in ET.parse(os.path.join(d, "stopinfo.xml")).getroot()
            if s.attrib.get("busStop") == stop["id"]]
    occ = stop_lane_occupancy(d, stop["lane"])
    tot, forced = forced_lane_changes(d, stop["lane"], 0, 1e9, cfg.warmup, cfg.demand_end)
    re = bus_reentry(d, rows)
    ti = ET.parse(os.path.join(d, "tripinfo.xml")).getroot()
    loss = [float(t.get("timeLoss")) for t in ti.findall("tripinfo")
            if t.get("vType") == "car" and cfg.warmup <= float(t.get("depart")) < cfg.demand_end
            and t.get("id").startswith("eb")]
    res = {"arm": name, "q_art": q, "stop": stop["id"], "stop_lane": stop["lane"],
           "stopinfo_parking_values": sorted({r["parking"] for r in rows}),
           "n_stop_events": len(rows),
           "mean_dwell": sum(float(r["ended"]) - float(r["started"]) for r in rows) / max(len(rows), 1),
           "lanedata_stop_lane": occ,
           "lane_changes_off_stop_lane": tot, "forced_off_stop_lane": forced,
           "reentry": {k: v for k, v in re.items() if k != "events"},
           "reentry_events": re["events"],
           "eb_car_mean_timeloss": sum(loss) / max(len(loss), 1), "n_eb_cars": len(loss)}
    shutil.rmtree(os.path.join(d), ignore_errors=False) if False else None
    fp = os.path.join(d, "fcd.xml")
    if os.path.exists(fp):
        os.remove(fp)
    return res


if __name__ == "__main__":
    os.makedirs(RES, exist_ok=True)
    base = Cfg(stop_placement="midblock", lanes_art=2, headway=180.0,
               pax_rate=700.0, demand_end=2400.0, sim_end=4200.0, warmup=600.0)
    out = {"arms": [], "sumo_yield_option_scan": {}}
    for q in (600, 1200, 1800):
        for name, stype in (("inlane", "inlane"), ("bay", "bay"), ("geobay", "geobay")):
            c = Cfg(**{**base.__dict__, "stop_type": stype})
            r = arm(name, c, 7, q)
            out["arms"].append(r)
            print(f"{name:8s} q={q:5d} parking={r['stopinfo_parking_values']} "
                  f"laneOccSec={r['lanedata_stop_lane']['sampledSeconds'] if r['lanedata_stop_lane'] else None} "
                  f"forcedLC={r['forced_off_stop_lane']} reentry={r['reentry']['mean_reentry_s']} "
                  f"ebLoss={r['eb_car_mean_timeloss']:.2f}")
    # single-lane variant: the blocking case where there is no escape lane
    for q in (400, 800):
        for name, stype in (("inlane1L", "inlane"), ("bay1L", "bay")):
            c = Cfg(**{**base.__dict__, "stop_type": stype, "lanes_art": 1})
            r = arm(name, c, 7, q)
            out["arms"].append(r)
            print(f"{name:8s} q={q:5d} parking={r['stopinfo_parking_values']} "
                  f"laneOccSec={r['lanedata_stop_lane']['sampledSeconds'] if r['lanedata_stop_lane'] else None} "
                  f"reentry={r['reentry']['mean_reentry_s']} ebLoss={r['eb_car_mean_timeloss']:.2f}")

    # does SUMO expose ANY yield-to-bus rule?
    h = subprocess.run([SUMO, "--help"], capture_output=True, text=True).stdout
    hits = [l.strip() for l in h.splitlines()
            if ("yield" in l.lower() or "bus" in l.lower()) and "--" in l]
    out["sumo_yield_option_scan"] = {"matching_option_lines": hits}
    json.dump(out, open(os.path.join(RES, "verify_parking_mechanism.json"), "w"), indent=1)
    print("\nSUMO option lines mentioning yield/bus:")
    for l in hits:
        print("  ", l)
