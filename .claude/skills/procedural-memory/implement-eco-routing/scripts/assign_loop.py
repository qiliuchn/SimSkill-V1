"""Iterative (MSA) duarouter assignment loop with a switchable cost surface.

One loop serves both arms of the study, so the travel-time user equilibrium and
the emissions ("eco") assignment differ ONLY in which attribute of the edge
weight file `duarouter --weight-attribute` is pointed at:

    cost_e = alpha * traveltime_e  +  beta * fuel_perVeh_e          [gcost]

    alpha=1, beta=0      -> conventional travel-time UE
    alpha=0, beta=1      -> pure eco (minimum-fuel) assignment
    in between           -> generalized eco cost

Iteration k:
  1. simulate the current assignment, dumping `edgeData type="emissions"`
     in intervals of WEIGHT_INTERVAL seconds (this single dump carries BOTH
     `traveltime` and `fuel_perVeh`/`CO2_perVeh`),
  2. write a weight file covering EVERY edge and EVERY interval in
     [0, SIM_END] -- zero-flow edges fall back to the free-flow probe table,
  3. all-or-nothing re-route with duarouter against that weight file,
  4. move a 1/k share of vehicles onto the new route (method of successive
     averages), which is what makes the loop converge instead of flip-flopping.

Convergence is reported with two independent criteria:
  * relative gap  = (C_current - C_allOrNothing) / C_current   on the cost
    surface actually being minimised, and
  * route-share stability = max |share_k - share_{k-1}| over the three route
    classes (arterial / bypass / hybrid).
"""
import argparse
import json
import os
import random
import statistics
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import NET, WORK, SIM_END, run, sumo_bin, classify_route  # noqa: E402
import simlib  # noqa: E402
import probe_freeflow  # noqa: E402

WEIGHT_INTERVAL = 600          # s; weight-file aggregation window
COST_ATTRS = ("traveltime", "CO2_perVeh", "fuel_perVeh", "gcost")


# --------------------------------------------------------------- weights ---

def smooth_intervals(prev, new, s):
    """Exponential smoothing of the measured cost surface across iterations:
    w_k = (1-s)*w_{k-1} + s*w_measured, applied cell-wise on the raw edgeData
    attributes. Damps single-simulation measurement noise, which otherwise
    makes the relative gap bounce around instead of decaying."""
    if prev is None or s >= 1.0:
        return new
    out = []
    for i, iv in enumerate(new):
        p = prev[i]["edges"] if i < len(prev) else {}
        edges = {}
        for eid, d in iv["edges"].items():
            pd = p.get(eid, {})
            edges[eid] = {k: (1 - s) * pd[k] + s * v if k in pd else v for k, v in d.items()}
        out.append(dict(begin=iv["begin"], end=iv["end"], edges=edges))
    return out


def build_weight_file(edge_emis_intervals, ff_ref, alpha, beta, path,
                      interval=WEIGHT_INTERVAL, horizon=SIM_END, metric="perveh"):
    """Write a duarouter weight file covering every edge in every interval.

    `edge_emis_intervals` is the parsed edgeData dump. Any (edge, interval)
    with no sample -- i.e. missing the `traveltime`/`*_perVeh` attributes --
    is filled from the free-flow probe reference.
    """
    n_fallback = 0
    n_cells = 0
    with open(path, "w") as f:
        f.write('<meandata>\n')
        for iv in edge_emis_intervals:
            f.write('    <interval begin="%.1f" end="%.1f">\n' % (iv["begin"], iv["end"]))
            for eid, ref in ff_ref.items():
                d = iv["edges"].get(eid, {})
                n_cells += 1
                if "traveltime" not in d:          # zero-flow cell
                    n_fallback += 1
                    tt = ref["traveltime"]
                    co2 = ref["CO2_perVeh"]
                    fuel = ref["fuel_perVeh"]
                else:
                    tt = d["traveltime"]
                    co2 = d.get("CO2_perVeh", ref["CO2_perVeh"])
                    fuel = d.get("fuel_perVeh", ref["fuel_perVeh"])
                if metric == "abs":
                    # PITFALL DEMO: per-edge TOTAL emissions instead of per-vehicle.
                    # An edge nobody uses has abs==0, so the cheapest "eco" route is
                    # by construction the one nobody is on -> the assignment chases
                    # emptiness, not cleanliness.
                    fuel = d.get("fuel_abs", 0.0) if "traveltime" in d else 0.0
                g = alpha * tt + beta * fuel
                f.write('        <edge id="%s" traveltime="%.4f" CO2_perVeh="%.4f" '
                        'fuel_perVeh="%.4f" gcost="%.6f"/>\n' % (eid, tt, co2, fuel, g))
            f.write('    </interval>\n')
        f.write('</meandata>\n')
    return dict(cells=n_cells, fallback=n_fallback, frac_fallback=n_fallback / max(n_cells, 1))


def weights_lookup(weight_file):
    """-> list of (begin, end, {edge: {attr: val}}) for offline cost evaluation."""
    out = []
    root = ET.parse(weight_file).getroot()
    for iv in root.findall("interval"):
        d = {e.get("id"): {a: float(v) for a, v in e.attrib.items() if a != "id"}
             for e in iv.findall("edge")}
        out.append((float(iv.get("begin")), float(iv.get("end")), d))
    return out


def route_cost(edges, depart, wl, attr):
    """Time-dependent route cost, advancing the clock edge by edge exactly the
    way duarouter does (this is what makes interval alignment matter)."""
    t = depart
    total = 0.0
    for e in edges:
        cell = None
        for b, en, d in wl:
            if b <= t < en:
                cell = d
                break
        if cell is None:
            cell = wl[-1][2]
        v = cell.get(e)
        if v is None:
            continue
        total += v[attr]
        t += v["traveltime"]
    return total


# ------------------------------------------------------------- route i/o ---

def read_trips(path):
    """-> ordered list of (id, type, depart, from, to)"""
    root = ET.parse(path).getroot()
    return [(t.get("id"), t.get("type"), float(t.get("depart")),
             t.get("from"), t.get("to")) for t in root.findall("trip")]


def write_routes(path, trips, assignment):
    with open(path, "w") as f:
        f.write('<routes>\n')
        for vid, ty, dep, _fr, _to in trips:
            e = assignment.get(vid)
            if not e:
                continue
            f.write('    <vehicle id="%s" type="%s" depart="%.2f" departLane="best" '
                    'departSpeed="max">\n        <route edges="%s"/>\n    </vehicle>\n'
                    % (vid, ty, dep, " ".join(e)))
        f.write('</routes>\n')


def duarouter_aon(trips_file, out_file, weight_file=None, attr=None, seed=42):
    cmd = [sumo_bin("duarouter"), "-n", NET, "-r", trips_file,
           "-a", os.path.join(WORK, "vtypes.add.xml"),
           "-o", out_file, "--ignore-errors", "--no-step-log", "true",
           "--xml-validation", "never", "--seed", str(seed),
           "--routing-algorithm", "dijkstra"]
    if weight_file:
        cmd += ["--weight-files", weight_file, "--weight-attribute", attr]
    run(cmd)
    return simlib.parse_routes(out_file)


# ------------------------------------------------------------------ loop ---

def run_assignment(tag, trips_file, alpha, beta, n_iter=12, sim_seed=1, rng_seed=7,
                   outdir=None, interval=WEIGHT_INTERVAL, smooth=0.5, metric="perveh"):
    outdir = outdir or os.path.join(WORK, "assign_" + tag)
    os.makedirs(outdir, exist_ok=True)
    ff = probe_freeflow.load()
    trips = read_trips(trips_file)
    rng = random.Random(rng_seed)
    attr = "gcost"

    # iteration 0: free-flow all-or-nothing on the SAME cost definition
    ff_ivs = [dict(begin=0.0, end=float(SIM_END), edges={})]
    w0 = os.path.join(outdir, "w_000.xml")
    build_weight_file(ff_ivs, ff, alpha, beta, w0, horizon=SIM_END)  # iter-0 always free-flow
    cur = {v: e for v, (t, e) in duarouter_aon(
        trips_file, os.path.join(outdir, "aon_000.rou.xml"), w0, attr).items()}

    history = []
    prev_share = None
    prev_ivs = None
    for k in range(1, n_iter + 1):
        rou = os.path.join(outdir, "cur_%03d.rou.xml" % k)
        write_routes(rou, trips, cur)
        files = simlib.run_sumo(rou, os.path.join(outdir, "sim_%03d" % k), seed=sim_seed,
                                emissions_edgedata=True, edge_period=interval)
        ivs = simlib.parse_edge_emissions(files["edge_emissions"])
        ivs = smooth_intervals(prev_ivs, ivs, smooth)
        prev_ivs = ivs
        wf = os.path.join(outdir, "w_%03d.xml" % k)
        fb = build_weight_file(ivs, ff, alpha, beta, wf, interval=interval, metric=metric)
        wl = weights_lookup(wf)

        aon = {v: e for v, (t, e) in duarouter_aon(
            trips_file, os.path.join(outdir, "aon_%03d.rou.xml" % k), wf, attr).items()}

        # relative gap on the minimised cost surface (main OD only)
        c_cur = c_aon = 0.0
        for vid, ty, dep, _f, _t in trips:
            if not vid.startswith("main."):
                continue
            c_cur += route_cost(cur[vid], dep, wl, attr)
            c_aon += route_cost(aon.get(vid, cur[vid]), dep, wl, attr)
        gap = (c_cur - c_aon) / c_cur

        ti = simlib.parse_tripinfo(files["tripinfo"])
        m = [t for t in ti if t["id"].startswith("main.")]
        share, cnt, tot = simlib.route_shares({v: ("", e) for v, e in cur.items()})
        d_share = None if prev_share is None else max(
            abs(share.get(k2, 0) - prev_share.get(k2, 0)) for k2 in ("arterial", "bypass", "hybrid"))
        rec = dict(iter=k, gap=gap, share=share, d_share=d_share,
                   mean_dur=statistics.mean(t["duration"] for t in m),
                   mean_total=statistics.mean(t["duration"] + t["departDelay"] for t in m),
                   mean_CO2_g=statistics.mean(t["CO2"] for t in m) / 1000.0,
                   net_CO2_kg=sum(t["CO2"] for t in ti) / 1e6,
                   net_fuel_kg=sum(t["fuel"] for t in ti) / 1e6,
                   arrived=len(ti), main_arrived=len(m),
                   fallback_frac=fb["frac_fallback"],
                   teleports=simlib.count_teleports(files["stderr"]))
        history.append(rec)
        print("[%s] it%02d gap=%+.4f share=%s dshare=%s dur=%.1f CO2=%.1fkg fb=%.2f tp=%d"
              % (tag, k, gap, {a: round(b, 3) for a, b in share.items()},
                 "n/a" if d_share is None else round(d_share, 4),
                 rec["mean_dur"], rec["net_CO2_kg"], rec["fallback_frac"], rec["teleports"]))
        prev_share = share

        # MSA flow update
        n_sw = 0
        for vid in list(cur):
            if vid in aon and aon[vid] != cur[vid] and rng.random() < 1.0 / k:
                cur[vid] = aon[vid]
                n_sw += 1
        history[-1]["switched"] = n_sw

    final = os.path.join(outdir, "final.rou.xml")
    write_routes(final, trips, cur)
    with open(os.path.join(outdir, "history.json"), "w") as f:
        json.dump(dict(tag=tag, alpha=alpha, beta=beta, interval=interval,
                       smooth=smooth, history=history), f, indent=1)
    return final, history


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--trips", required=True)
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--beta", type=float, default=0.0)
    ap.add_argument("--iters", type=int, default=12)
    ap.add_argument("--sim-seed", type=int, default=1)
    ap.add_argument("--interval", type=int, default=WEIGHT_INTERVAL)
    ap.add_argument("--smooth", type=float, default=0.5)
    ap.add_argument("--metric", default="perveh", choices=["perveh", "abs"])
    a = ap.parse_args()
    run_assignment(a.tag, a.trips, a.alpha, a.beta, n_iter=a.iters,
                   sim_seed=a.sim_seed, interval=a.interval, smooth=a.smooth,
                   metric=a.metric)
