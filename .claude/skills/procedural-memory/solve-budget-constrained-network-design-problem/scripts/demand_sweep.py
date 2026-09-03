#!/usr/bin/env python3
"""
Step 1b: locate the flow-vs-demand knee on the DO-NOTHING network and pick the
loading level that puts mean v/c on the loaded corridors in the 0.85-1.05 band.

Capacity of a signalised approach edge is computed from the COMPILED network:
    cap_e = numLanes * SAT_FLOW * (green time for that edge's links / cycle)
read out of the tlLogic of the edge's downstream junction.  Flow is the peak
30-min edgeData count scaled to veh/h.  The knee is the peak of the
served-throughput-vs-demand curve (per quantify-sumo-run-to-run-variability).
"""
import os, sys, csv, json, shutil
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from testbed import build_net, write_trips, DEMAND_END
import evaluate as EV

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
WORK = os.path.join(ROOT, "work", "sweep")
OUT = os.path.join(ROOT, "outputs")
SAT_FLOW = 1900.0        # veh/h/lane saturation flow assumption (stated, not measured)
AGG = 1800               # edgeData aggregation interval (s)


def edge_green_ratios(netfile):
    """green-time fraction per edge, from the compiled tlLogic of its to-junction."""
    root = ET.parse(netfile).getroot()
    # link index -> (from edge) per tls
    tl_links = {}
    for c in root.findall("connection"):
        tl = c.get("tl")
        if tl is None:
            continue
        tl_links.setdefault(tl, []).append((int(c.get("linkIndex")), c.get("from")))
    ratios = {}
    for t in root.findall("tlLogic"):
        tid = t.get("id")
        phases = [(float(p.get("duration")), p.get("state")) for p in t.findall("phase")]
        cyc = sum(d for d, _ in phases)
        per_edge = {}
        for idx, frm in tl_links.get(tid, []):
            g = 0.0
            for d, st in phases:
                if idx < len(st) and st[idx] in "gG":
                    g += d
            per_edge[frm] = max(per_edge.get(frm, 0.0), g / cyc if cyc else 0.0)
        for e, r in per_edge.items():
            ratios[e] = max(ratios.get(e, 0.0), r)
    # non-tls edges (access edges into gate nodes): uncontrolled
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        ratios.setdefault(e.get("id"), 1.0)
    return ratios


def edge_lanes(netfile):
    root = ET.parse(netfile).getroot()
    return {e.get("id"): len(e.findall("lane")) for e in root.findall("edge")
            if e.get("function") != "internal"}


def peak_flows(edgedata_file):
    """max per-interval `entered+departed` count per edge, scaled to veh/h."""
    best = {}
    for _, iv in ET.iterparse(edgedata_file, events=("end",)):
        if iv.tag != "interval":
            continue
        b, e = float(iv.get("begin")), float(iv.get("end"))
        dur = max(1.0, e - b)
        for ed in iv.findall("edge"):
            n = float(ed.get("entered", 0)) + float(ed.get("departed", 0))
            f = n * 3600.0 / dur
            k = ed.get("id")
            if f > best.get(k, -1):
                best[k] = f
        iv.clear()
    return best


def one_level(args):
    nveh, wd = args
    os.makedirs(wd, exist_ok=True)
    tf = os.path.join(wd, "trips.xml")
    write_trips(nveh, tf)
    netfile = build_net(0, wd)
    # NOTE: run with the COLD protocol; evaluate.run_dua returns (duadir, steps)
    duadir, steps = EV.run_dua(netfile, tf, wd, last_step=12)
    dua = dict(duadir=duadir, route_file=steps[-1]["rou"],
               rel_gap=EV.rel_gap_from_alt(steps[-1]["alt"]) if steps[-1]["alt"] else float("nan"),
               tt_stab=float("nan"), n_steps=len(steps))
    out = os.path.join(wd, "rec")
    os.makedirs(out, exist_ok=True)
    add = os.path.join(out, "ed.add.xml")
    with open(add, "w") as f:
        f.write('<additional><edgeData id="ed" file="edgedata.xml" begin="0" end="%d" '
                'period="%d" excludeEmpty="true"/></additional>\n' % (int(EV.SIM_END), AGG))
    import subprocess
    tri = os.path.join(out, "tripinfo.xml"); summ = os.path.join(out, "summary.xml")
    cmd = ["sumo", "-n", netfile, "-r", dua["route_file"], "-a", add,
           "--tripinfo-output", tri, "--tripinfo-output.write-unfinished", "true",
           "--summary-output", summ, "--begin", "0", "--end", str(int(EV.SIM_END)),
           "--time-to-teleport", str(int(EV.TIME_TO_TELEPORT)), "--seed", "1",
           "--no-step-log", "true", "--no-warnings", "true", "--xml-validation", "never"]
    subprocess.run(cmd, check=True, capture_output=True)

    departs = EV.parse_trip_departs(tf)
    routed = set(EV.parse_rou_ids(dua["route_file"]))
    arrived, running = EV.parse_tripinfo(tri)
    seen = set(r["id"] for r in arrived) | set(r["id"] for r in running)
    ni = sorted(routed - seen); dis = sorted(set(departs) - routed)
    tstt = sum(r["arrival"] - (r["depart"] - r["departDelay"]) for r in arrived)
    tstt += sum(EV.SIM_END - (r["depart"] - r["departDelay"]) for r in running)
    tstt += sum(EV.SIM_END - departs[v] for v in ni + dis)
    last = EV.parse_summary_last(summ)

    ratios = edge_green_ratios(netfile); lanes = edge_lanes(netfile)
    flows = peak_flows(os.path.join(out, "edgedata.xml"))
    vc = {}
    for e, f in flows.items():
        cap = lanes.get(e, 1) * SAT_FLOW * ratios.get(e, 1.0)
        if cap > 0:
            vc[e] = f / cap
    grid = {e: v for e, v in vc.items() if not (e.startswith(("W", "E", "S", "N"))
                                               or e.split("_")[1][0] in "WESN")}
    loaded = sorted(grid.items(), key=lambda kv: -kv[1])
    top = loaded[:12]
    res = dict(nveh=nveh, arrived=len(arrived), running=len(running),
               not_inserted=len(ni), discarded=len(dis),
               accounting_ok=(len(arrived)+len(running)+len(ni)+len(dis)) == nveh,
               teleports=int(last.get("teleports", 0)),
               tstt=round(tstt, 1),
               mean_dur=round(sum(r["duration"] for r in arrived)/max(1,len(arrived)), 2),
               mean_departdelay=round(sum(r["departDelay"] for r in arrived)/max(1,len(arrived)), 2),
               served_veh_h=round(len(arrived)*3600.0/EV.SIM_END, 1),
               peak_served_flow_sum=round(sum(flows.get(e, 0) for e, _ in top), 1),
               mean_vc_top12=round(sum(v for _, v in top)/len(top), 4),
               mean_vc_grid=round(sum(grid.values())/len(grid), 4),
               n_grid_edges=len(grid),
               top_vc=[[e, round(v, 3)] for e, v in top],
               rel_gap=dua["rel_gap"], tt_stab=dua["tt_stab"], dua_iter=dua["n_steps"])
    shutil.rmtree(dua["duadir"], ignore_errors=True)
    return res


def main():
    os.makedirs(WORK, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    levels = [1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 6000]
    jobs = [(n, os.path.join(WORK, "n%d" % n)) for n in levels]
    with ProcessPoolExecutor(max_workers=9) as ex:
        res = list(ex.map(one_level, jobs))
    with open(os.path.join(OUT, "demand_sweep.json"), "w") as f:
        json.dump(res, f, indent=2)
    keys = ["nveh", "arrived", "running", "not_inserted", "discarded", "teleports",
            "tstt", "mean_dur", "mean_departdelay", "served_veh_h",
            "peak_served_flow_sum", "mean_vc_top12", "mean_vc_grid",
            "rel_gap", "tt_stab", "dua_iter", "accounting_ok"]
    with open(os.path.join(OUT, "demand_sweep.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader(); w.writerows(res)
    print("%6s %7s %7s %6s %8s %9s %9s %9s %8s %8s" %
          ("nveh", "arrived", "notins", "telep", "meandur", "sumflow", "vc_top12",
           "vc_grid", "relgap", "iters"))
    for r in res:
        print("%6d %7d %7d %6d %8.1f %9.1f %9.3f %9.3f %8.4f %8d" %
              (r["nveh"], r["arrived"], r["not_inserted"], r["teleports"], r["mean_dur"],
               r["peak_served_flow_sum"], r["mean_vc_top12"], r["mean_vc_grid"],
               r["rel_gap"], r["dua_iter"]))


if __name__ == "__main__":
    main()
