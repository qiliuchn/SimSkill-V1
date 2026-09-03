#!/usr/bin/env python3
"""
Parse every completed run directory into two tidy CSVs:
  results_runs.csv    - one row per run (network-level + crossover instrumentation)
  results_classes.csv - one row per (run, OD movement class)

Discipline applied:
  * completed  = tripinfo arrival >= 0 ; still-running = arrival == -1
    (--tripinfo-output.write-unfinished true writes BOTH)
  * loaded / inserted / arrived read from summary.xml's LAST step
  * teleports read as the LAST cumulative value, never summed
  * both travel DISTANCE (routeLength) and travel TIME are reported so the
    VMT-up / VHT-down trade-off is explicit
  * total experienced time = duration + departDelay is reported separately from
    in-network duration (see semantic-memory/dynamic-user-equilibrium-and-wardrop)
"""
import csv
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from demand import movement_class  # noqa: E402


def _open_maybe_gz(p):
    """Open an XML file that may have been gzipped by prune_runs/archival."""
    import gzip as _gz, os as _os
    if not _os.path.exists(p) and _os.path.exists(p + ".gz"):
        return _gz.open(p + ".gz", "rb")
    if p.endswith(".gz"):
        return _gz.open(p, "rb")
    return open(p, "rb")



LOAD_WINDOW = 4200.0     # crossover instrumentation window (demand hour + drain)
UTURN_PAIRS = {("W_J_XW", "E_XW_J"): "XW", ("E_J_XE", "W_XE_J"): "XE"}
_route_cache = {}
_lane_len_cache = {}


def load_routes(rf):
    if rf in _route_cache:
        return _route_cache[rf]
    out = {}
    for _, v in ET.iterparse(_open_maybe_gz(rf), events=("end",)):
        if v.tag != "vehicle":
            continue
        r = v.find("route")
        edges = r.get("edges").split() if r is not None else []
        ut = [UTURN_PAIRS[p] for p in zip(edges, edges[1:]) if p in UTURN_PAIRS]
        out[v.get("id")] = (v.get("fromTaz"), v.get("toTaz"), edges, ut)
        v.clear()
    _route_cache[rf] = out
    return out


def lane_lengths(netfile):
    if netfile not in _lane_len_cache:
        n = sumolib.net.readNet(netfile)
        _lane_len_cache[netfile] = {l.getID(): l.getLength()
                                    for e in n.getEdges() for l in e.getLanes()}
    return _lane_len_cache[netfile]


def last_summary(p):
    last = None
    for _, s in ET.iterparse(p, events=("end",)):
        if s.tag == "step":
            last = dict(s.attrib)
            s.clear()
    return last or {}


def crossover_metrics(rundir, netfile):
    p = os.path.join(rundir, "lanearea.xml")
    if not os.path.exists(p):
        return {}
    LL = lane_lengths(netfile)
    agg = {}
    for _, iv in ET.iterparse(p, events=("end",)):
        if iv.tag != "interval":
            continue
        if float(iv.get("end")) > LOAD_WINDOW:
            iv.clear()
            continue
        did = iv.get("id")[3:]
        a = agg.setdefault(did, {"maxjam": 0.0, "jamsum": 0.0, "n": 0, "ovf": 0,
                                 "seen": 0, "tl_w": 0.0, "tl_n": 0, "haltmax": 0.0})
        mj = float(iv.get("maxJamLengthInMeters"))
        a["maxjam"] = max(a["maxjam"], mj)
        a["jamsum"] += float(iv.get("meanMaxJamLengthInVehicles")) * 0 + mj
        a["n"] += 1
        L = LL.get(did, 1.0)
        if mj >= 0.90 * L:
            a["ovf"] += 1
        seen = int(iv.get("nVehSeen"))
        a["seen"] += seen
        tl = float(iv.get("meanTimeLoss"))
        if tl >= 0 and seen > 0:
            a["tl_w"] += tl * seen
            a["tl_n"] += seen
        a["haltmax"] = max(a["haltmax"], float(iv.get("maxHaltingDuration")))
        iv.clear()
    out = {}
    for did, a in agg.items():
        L = LL.get(did, 1.0)
        out[did] = {"maxjam_m": a["maxjam"], "meanjam_m": a["jamsum"] / max(a["n"], 1),
                    "storage_m": L, "jam_ratio": a["maxjam"] / L if L else 0.0,
                    "overflow_frac": a["ovf"] / max(a["n"], 1),
                    "veh_seen": a["seen"],
                    "mean_timeloss_s": a["tl_w"] / a["tl_n"] if a["tl_n"] else 0.0,
                    "max_halt_s": a["haltmax"]}
    return out


def edge_timeloss(rundir):
    p = os.path.join(rundir, "edgedata.xml")
    out = {}
    if not os.path.exists(p):
        return out
    for _, e in ET.iterparse(p, events=("end",)):
        if e.tag != "edge":
            continue
        out[e.get("id")] = {"timeLoss": float(e.get("timeLoss", 0)),
                            "entered": float(e.get("entered", 0)),
                            "speed": float(e.get("speed", 0))}
        e.clear()
    return out


def analyze_run(rundir):
    meta = json.load(open(os.path.join(rundir, "meta.json")))
    routes = load_routes(meta["route_file"])
    cls = {}
    allv = {"completed": [], "unfinished": []}
    for _, t in ET.iterparse(os.path.join(rundir, "tripinfo.xml"), events=("end",)):
        if t.tag != "tripinfo":
            continue
        vid = t.get("id")
        o, d, edges, ut = routes.get(vid, (None, None, [], []))
        c = movement_class(o, d) if o else "UNKNOWN"
        arr = float(t.get("arrival"))
        rec = {"dur": float(t.get("duration")), "len": float(t.get("routeLength")),
               "tl": float(t.get("timeLoss")), "dd": float(t.get("departDelay")),
               "wt": float(t.get("waitingTime")), "ut": len(ut), "arrived": arr >= 0}
        cls.setdefault(c, []).append(rec)
        allv["completed" if arr >= 0 else "unfinished"].append(rec)
        t.clear()

    # routed-demand accounting (per class) straight from the route file
    routed = {}
    for vid, (o, d, e, ut) in routes.items():
        routed[movement_class(o, d)] = routed.get(movement_class(o, d), 0) + 1

    summ = last_summary(os.path.join(rundir, "summary.xml"))
    xo = crossover_metrics(rundir, meta["net"])
    ed = edge_timeloss(rundir)
    plan = meta["plan"]

    def agg(recs, only_done=True):
        r = [x for x in recs if x["arrived"]] if only_done else recs
        n = len(r)
        if n == 0:
            return dict(n=0, dur=float("nan"), dist=float("nan"), tl=float("nan"),
                        dd=float("nan"), tot=float("nan"), vmt=0.0, vht=0.0)
        return dict(n=n,
                    dur=sum(x["dur"] for x in r) / n,
                    dist=sum(x["len"] for x in r) / n,
                    tl=sum(x["tl"] for x in r) / n,
                    dd=sum(x["dd"] for x in r) / n,
                    tot=sum(x["dur"] + x["dd"] for x in r) / n,
                    vmt=sum(x["len"] for x in r) / 1000.0,
                    vht=sum(x["dur"] for x in r) / 3600.0)

    A = agg([x for v in cls.values() for x in v])
    run_row = {
        "run": os.path.basename(rundir), "tag": meta["tag"], "variant": meta["variant"],
        "D": meta["D"], "Q": meta["Q"], "m": meta["m"], "seed": meta["seed"],
        "ttt": meta["ttt"], "ssm": meta["ssm"],
        "n_phases": plan["n_phases"], "cycle_s": round(plan["cycle_s"], 1),
        "Y_flow_ratio": round(plan["Y"], 4),
        "routed": len(routes),
        "loaded": int(float(summ.get("loaded", 0))),
        "inserted": int(float(summ.get("inserted", 0))),
        "arrived": int(float(summ.get("arrived", 0))),
        "running_end": int(float(summ.get("running", 0))),
        "teleports": int(float(summ.get("teleports", 0))),
        "collisions": int(float(summ.get("collisions", 0))),
        "completed": A["n"], "unfinished": len(allv["unfinished"]),
        "never_inserted": int(float(summ.get("loaded", 0))) - int(float(summ.get("inserted", 0))),
        "mean_duration_s": A["dur"], "mean_distance_m": A["dist"],
        "mean_timeloss_s": A["tl"], "mean_departdelay_s": A["dd"],
        "mean_totaltime_s": A["tot"], "VMT_km": A["vmt"], "VHT_h": A["vht"],
        "n_uturn_users": sum(1 for v in routes.values() if v[3]),
    }
    for node, lane in (("XW", "W_J_XW_2"), ("XE", "E_J_XE_2")):
        x = xo.get(lane, {})
        run_row[f"ut_{node}_maxjam_m"] = x.get("maxjam_m", 0.0)
        run_row[f"ut_{node}_meanjam_m"] = x.get("meanjam_m", 0.0)
        run_row[f"ut_{node}_storage_m"] = x.get("storage_m", 0.0)
        run_row[f"ut_{node}_jamratio"] = x.get("jam_ratio", 0.0)
        run_row[f"ut_{node}_overflow_frac"] = x.get("overflow_frac", 0.0)
        run_row[f"ut_{node}_timeloss_s"] = x.get("mean_timeloss_s", 0.0)
        run_row[f"ut_{node}_maxhalt_s"] = x.get("max_halt_s", 0.0)
        run_row[f"ut_{node}_veh"] = x.get("veh_seen", 0)
    for node, lanes in (("XW", ["W_J_XW_0", "W_J_XW_1"]), ("XE", ["E_J_XE_0", "E_J_XE_1"])):
        mj = max((xo.get(l, {}).get("maxjam_m", 0.0) for l in lanes), default=0.0)
        of = max((xo.get(l, {}).get("overflow_frac", 0.0) for l in lanes), default=0.0)
        run_row[f"thru_{node}_maxjam_m"] = mj
        run_row[f"thru_{node}_overflow_frac"] = of
    for e in ("W_J_XW", "E_J_XE", "E_XW_J", "W_XE_J"):
        run_row[f"edge_tl_{e}"] = ed.get(e, {}).get("timeLoss", 0.0)

    class_rows = []
    for c in sorted(set(list(cls) + list(routed))):
        a = agg(cls.get(c, []))
        u = [x for x in cls.get(c, []) if not x["arrived"]]
        class_rows.append({**{k: run_row[k] for k in ("run", "tag", "variant", "D", "Q", "m", "seed", "ttt")},
                           "movement_class": c, "routed": routed.get(c, 0),
                           "completed": a["n"], "unfinished": len(u),
                           "mean_distance_m": a["dist"], "mean_duration_s": a["dur"],
                           "mean_timeloss_s": a["tl"], "mean_departdelay_s": a["dd"],
                           "mean_totaltime_s": a["tot"],
                           "VMT_km": a["vmt"], "VHT_h": a["vht"],
                           "uses_uturn": (sum(x["ut"] for x in cls.get(c, [])) /
                                          max(len(cls.get(c, [])), 1))})
    return run_row, class_rows


def main(runroot, outdir):
    runs, classes = [], []
    for name in sorted(os.listdir(runroot)):
        d = os.path.join(runroot, name)
        if not os.path.exists(os.path.join(d, "DONE")):
            continue
        try:
            r, cr = analyze_run(d)
        except Exception as e:  # noqa: BLE001
            print("FAILED", name, e)
            continue
        runs.append(r)
        classes += cr
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "results_runs.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(runs[0].keys()))
        w.writeheader()
        w.writerows(runs)
    with open(os.path.join(outdir, "results_classes.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(classes[0].keys()))
        w.writeheader()
        w.writerows(classes)
    print(f"wrote {len(runs)} runs, {len(classes)} class rows -> {outdir}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
