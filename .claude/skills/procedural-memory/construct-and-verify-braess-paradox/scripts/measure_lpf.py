#!/usr/bin/env python3
"""
STEP 2 -- MEASURE each Braess link's actual link performance function (LPF) in SUMO.

Rather than *assuming* that "1 lane + low speed" behaves as a flow-dependent link and
"3 lanes + high speed" as a flow-independent one, this runs isolated loading sweeps on the
LINK network with a single fixed route and measures, per demand level:

  * the actual volume that entered each link (from vehroute exit-times, not from the demand
    definition -- they differ once the origin queue spills back),
  * the mean per-vehicle link travel time (exact, from --vehroute-output.exit-times:
    t_link = exit(last edge of link) - exit(edge preceding the link)),
  * the edgeData mean travel time for cross-validation (this is the signal duaIterate's
    router actually uses),
  * departDelay, to detect origin spillback.

Two sweeps, so that each link class is measured while it is the UPSTREAM (hence
demand-unconstrained) element of its route:
  sweep "sa" : route S_in SA_a SA_b AT   T_out  -> flow-dependent  S->A  at full volume
  sweep "bt" : route S_in SB   BT_a BT_b T_out  -> flow-independent S->B at full volume,
                                                   flow-dependent  B->T at full volume
"""
import argparse
import csv
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

SUMO = shutil.which("sumo") or os.path.join(os.environ.get("SUMO_HOME", ""), "..", "bin", "sumo")

# sweep name -> (route edge list, {link label: (predecessor edge, last edge of link)})
SWEEPS = {
    # flow-dependent S->A as the upstream (demand-unconstrained) element
    "sa": ("S_in SA_a SA_b AT T_out",
           {"S->A (flow-dep)": ("S_in", "SA_b"), "A->T (flow-indep)": ("SA_b", "AT")}),
    # flow-dependent B->T; S->B here is upstream but can be contaminated by B->T spillback
    "bt": ("S_in SB BT_a BT_b T_out",
           {"S->B (flow-indep)": ("S_in", "SB"), "B->T (flow-dep)": ("SB", "BT_b")}),
    # flow-INdependent links loaded at the full rate with NO downstream bottleneck at all
    "sb_only": ("S_in SB", {"S->B (flow-indep, isolated)": ("S_in", "SB")}),
    "at_only": ("AT T_out", {"A->T (flow-indep, isolated)": ("", "AT")}),
    # cross link A->B in the zig-zag route: is it really nearly costless?
    "zig": ("S_in SA_a SA_b AB BT_a BT_b T_out",
            {"A->B (cross)": ("SA_b", "AB")}),
}
LINK_EDGES = {
    "S->A (flow-dep)": ["SA_a", "SA_b"],
    "A->T (flow-indep)": ["AT"],
    "S->B (flow-indep)": ["SB"],
    "B->T (flow-dep)": ["BT_a", "BT_b"],
    "S->B (flow-indep, isolated)": ["SB"],
    "A->T (flow-indep, isolated)": ["AT"],
    "A->B (cross)": ["AB"],
}


def run_one(net, out_dir, sweep, q, load_s, seed):
    os.makedirs(out_dir, exist_ok=True)
    edges, _ = SWEEPS[sweep]
    rou = os.path.join(out_dir, "demand.rou.xml")
    with open(rou, "w") as f:
        f.write('<routes>\n')
        f.write(f'  <route id="r" edges="{edges}"/>\n')
        f.write(f'  <flow id="f" route="r" begin="0" end="{load_s}" vehsPerHour="{q}" '
                f'departLane="best" departSpeed="max"/>\n')
        f.write('</routes>\n')
    add = os.path.join(out_dir, "edgedata.add.xml")
    with open(add, "w") as f:
        f.write('<additional>\n'
                '  <edgeData id="whole" file="edgedata.xml" begin="0" end="%d" '
                'excludeEmpty="true"/>\n' % (load_s + 3600) +
                '</additional>\n')
    cmd = [SUMO, "-n", net, "-r", rou, "-a", add, "--no-step-log", "true",
           "--seed", str(seed), "--time-to-teleport", "-1", "--end", "20000",
           "--vehroute-output", os.path.join(out_dir, "vehroutes.xml"),
           "--vehroute-output.exit-times", "true",
           "--tripinfo-output", os.path.join(out_dir, "tripinfo.xml"),
           "--duration-log.statistics", "true"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=out_dir)
    if r.returncode != 0:
        raise SystemExit(f"sumo failed ({sweep}, q={q}):\n{r.stderr}")
    return r.stderr


def parse_run(out_dir, sweep, load_s):
    _, links = SWEEPS[sweep]
    veh_tt = {k: [] for k in links}
    enter_t = {k: [] for k in links}
    exit_t = {k: [] for k in links}
    root = ET.parse(os.path.join(out_dir, "vehroutes.xml")).getroot()
    for v in root.iter("vehicle"):
        r = v.find("route")
        if r is None:
            continue
        elist = r.get("edges").split()
        ex = [float(x) for x in r.get("exitTimes").split()]
        pos = {e: i for i, e in enumerate(elist)}
        for label, (pred, last) in links.items():
            if last not in pos:
                continue
            t0 = float(v.get("depart")) if pred == "" else (ex[pos[pred]] if pred in pos else None)
            if t0 is None:
                continue
            veh_tt[label].append(ex[pos[last]] - t0)
            enter_t[label].append(t0)
            exit_t[label].append(ex[pos[last]])
    # departDelay lives in tripinfo, NOT in vehroute-output
    dd = [float(t.get("departDelay", 0.0))
          for t in ET.parse(os.path.join(out_dir, "tripinfo.xml")).getroot().iter("tripinfo")]
    # edgeData cross-check (this is the router-visible signal)
    ed = {}
    for iv in ET.parse(os.path.join(out_dir, "edgedata.xml")).getroot().iter("interval"):
        for e in iv.iter("edge"):
            ed[e.get("id")] = {"tt": float(e.get("traveltime", "nan")),
                               "left": float(e.get("left", 0)),
                               "entered": float(e.get("entered", 0))}
    out = {}
    for label in links:
        tts = veh_tt[label]
        eids = LINK_EDGES[label]
        ed_tt = sum(ed.get(e, {}).get("tt", float("nan")) for e in eids)
        span = (max(exit_t[label]) - min(enter_t[label])) if tts else float("nan")
        out[label] = {
            "n": len(tts),
            "tt_mean": sum(tts) / len(tts) if tts else float("nan"),
            "tt_edgedata": ed_tt,
            "served_rate_vph": 3600.0 * len(tts) / span if span and span == span else float("nan"),
        }
    out["_departDelay"] = sum(dd) / len(dd) if dd else float("nan")
    out["_departDelay_max"] = max(dd) if dd else float("nan")
    out["_n_veh"] = len(dd)
    # S_in travel time (free-flow 20 s) is the origin-spillback indicator
    out["_s_in_tt"] = ed.get("S_in", {}).get("tt", float("nan"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--load-s", type=int, default=1800)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--flows", type=int, nargs="+",
                    default=[300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2700, 3000, 3600])
    a = ap.parse_args()

    rows = []
    for sweep in SWEEPS:
        for q in a.flows:
            d = os.path.join(a.work, f"lpf_{sweep}_{q}")
            run_one(a.net, d, sweep, q, a.load_s, a.seed)
            res = parse_run(d, sweep, a.load_s)
            for label, r in res.items():
                if label.startswith("_"):
                    continue
                rows.append({"sweep": sweep, "link": label, "demand_vph": q,
                             "assigned_volume_vph": q,
                             "served_rate_vph": round(r["served_rate_vph"], 1),
                             "tt_veh_s": round(r["tt_mean"], 2),
                             "tt_edgedata_s": round(r["tt_edgedata"], 2),
                             "n_veh": r["n"],
                             "mean_departDelay_s": round(res["_departDelay"], 2),
                             "max_departDelay_s": round(res["_departDelay_max"], 2),
                             "S_in_tt_s": round(res["_s_in_tt"], 2),
                             "origin_spillback": "yes" if res["_departDelay"] > 5 else "no"})
            print(f"{sweep} q={q:5d}  " + "  ".join(
                f"{l}: served={res[l]['served_rate_vph']:6.0f} t={res[l]['tt_mean']:7.1f}s"
                for l in res if not l.startswith("_")) +
                f"   dDelay={res['_departDelay']:7.1f}s  S_in_tt={res['_s_in_tt']:6.1f}s")
    with open(a.out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote", a.out_csv)


if __name__ == "__main__":
    main()
