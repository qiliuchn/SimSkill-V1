"""
Analyze a one-shot (all-or-nothing) baseline vs. a duaIterate.py dynamic-user-equilibrium
(DUE) run, classify vehicles by which of several parallel paths they used (via marker edges),
and test Wardrop's first principle: at equilibrium, do all USED paths have approximately equal
mean experienced travel time?

Computes the Wardrop check TWICE, on two different cost definitions, side by side:
  (A) IN-NETWORK duration -- the router-visible cost duaIterate actually optimizes against.
  (B) TOTAL experienced time = in-network duration + departDelay -- what a traveler actually
      experiences, including any time spent queued at the origin waiting to be inserted.
These can disagree: duaIterate's route choice is driven by edge-weight dumps that only see
vehicles already on an edge, so a vehicle queued at the origin (departDelay) is invisible to it.
An equilibrium can therefore satisfy Wardrop for (A) while still showing a real, non-trivial gap
for (B) -- always check BOTH, don't assume in-network equality implies total-time equality.

Usage:
    python analyze_due.py --baseline-routes baseline/vehroutes.xml --baseline-trips baseline/tripinfo.xml \
        --equilibrium-routes equilibrium/vehroutes.xml --equilibrium-trips equilibrium/tripinfo.xml \
        --dua-dir dua/ --path "freeway=fw_2" --path "arterial=art_2" \
        --threshold-pct 5 --out-dir analysis/
"""

import argparse
import csv
import glob
import gzip
import os
import xml.etree.ElementTree as ET


def parse_args():
    p = argparse.ArgumentParser(description="Compare one-shot vs duaIterate DUE assignment and test Wardrop's first principle.")
    p.add_argument("--baseline-routes", required=True, help="vehroutes.xml (or .rou.xml with routes) from the one-shot baseline")
    p.add_argument("--baseline-trips", required=True, help="tripinfo.xml from the one-shot baseline")
    p.add_argument("--equilibrium-routes", required=True, help="vehroutes.xml from the final duaIterate iteration")
    p.add_argument("--equilibrium-trips", required=True, help="tripinfo.xml from the final duaIterate iteration")
    p.add_argument("--dua-dir", help="duaIterate.py working directory (numbered iteration subfolders) for the convergence trace; omit to skip")
    p.add_argument(
        "--path",
        action="append",
        required=True,
        dest="paths",
        help='"<label>=<marker-edge-id>", repeatable (2+). A vehicle is classified by the first path whose marker edge appears in its route.',
    )
    p.add_argument("--threshold-pct", type=float, default=5.0, help="Wardrop 'approximately equal' threshold, as %% of the pair mean (default: 5)")
    p.add_argument("--out-dir", default="analysis", help="Output directory (default: analysis/)")
    return p.parse_args()


def classify(edges, path_markers):
    for label, marker in path_markers:
        if marker in edges:
            return label
    return "other"


def load_routes(vehroute_xml, path_markers):
    m = {}
    root = ET.parse(vehroute_xml).getroot()
    for v in root.iter("vehicle"):
        r = v.find("route")
        if r is None:
            rd = v.find("routeDistribution")
            if rd is not None:
                r = rd.findall("route")[-1]
        if r is not None:
            m[v.get("id")] = classify(r.get("edges", ""), path_markers)
    return m


def load_trips(tripinfo_xml):
    m = {}
    for t in ET.parse(tripinfo_xml).getroot().iter("tripinfo"):
        d = float(t.get("duration"))
        dd = float(t.get("departDelay", 0.0))
        m[t.get("id")] = {"duration": d, "timeLoss": float(t.get("timeLoss", 0.0)), "departDelay": dd, "total": d + dd}
    return m


def summarize(tag, vehroute_xml, tripinfo_xml, path_markers, labels):
    paths = load_routes(vehroute_xml, path_markers)
    trips = load_trips(tripinfo_xml)
    ids = list(trips)

    def mean(key, subset=None):
        s = [trips[i][key] for i in ids if subset is None or paths.get(i) == subset]
        return (sum(s) / len(s)) if s else float("nan")

    res = {"tag": tag, "arrived": len(ids), "mean_duration": mean("duration"), "mean_timeLoss": mean("timeLoss"),
           "mean_departDelay": mean("departDelay"), "mean_total": mean("total")}
    for label in labels:
        n = sum(1 for i in ids if paths.get(i) == label)
        res[f"n_{label}"] = n
        res[f"dur_{label}"] = mean("duration", label)
        res[f"dd_{label}"] = mean("departDelay", label)
        res[f"total_{label}"] = mean("total", label)
    return res


def gap(a, b):
    d = a - b
    rel = 100 * abs(d) / ((a + b) / 2) if (a + b) else float("nan")
    return d, rel


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    path_markers = [tuple(spec.split("=", 1)) for spec in args.paths]
    labels = [label for label, _ in path_markers]

    base = summarize("one_shot", args.baseline_routes, args.baseline_trips, path_markers, labels)
    equi = summarize("equilibrium", args.equilibrium_routes, args.equilibrium_trips, path_markers, labels)

    keys = ["tag", "arrived"] + [f"n_{l}" for l in labels] + ["mean_duration", "mean_timeLoss", "mean_departDelay", "mean_total"]
    keys += [f"dur_{l}" for l in labels] + [f"dd_{l}" for l in labels] + [f"total_{l}" for l in labels]
    with open(os.path.join(args.out_dir, "comparison.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys)
        for r in (base, equi):
            w.writerow([r.get(k) for k in keys])

    if args.dua_dir:
        conv = []
        prev = None
        for it_dir in sorted(glob.glob(os.path.join(args.dua_dir, "[0-9][0-9][0-9]"))):
            itn = os.path.basename(it_dir)
            rou_gz = glob.glob(os.path.join(it_dir, "*.rou.xml.gz"))
            if not rou_gz:
                continue
            with gzip.open(rou_gz[0]) as fh:
                paths = {v.get("id"): classify(v.find("route").get("edges", ""), path_markers) for v in ET.parse(fh).getroot().iter("vehicle")}
            trip_files = glob.glob(os.path.join(it_dir, "tripinfo_*.xml")) or glob.glob(os.path.join(it_dir, "tripinfo.xml"))
            if not trip_files:
                continue
            trips = load_trips(trip_files[0])
            ids = list(trips)
            n = len(ids)
            if n == 0:
                continue
            md = sum(trips[i]["duration"] for i in ids) / n
            mt = sum(trips[i]["total"] for i in ids) / n
            chg = (100 * sum(1 for k in paths if prev and prev.get(k) != paths[k]) / len(paths)) if prev else 0.0
            prev = paths
            row = {"it": int(itn), "mean_duration": md, "mean_total": mt, "route_change_pct": chg}
            for label in labels:
                row[f"n_{label}"] = sum(1 for p in paths.values() if p == label)
            conv.append(row)
        if conv:
            with open(os.path.join(args.out_dir, "convergence.csv"), "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(conv[0].keys()))
                w.writeheader()
                w.writerows(conv)

    with open(os.path.join(args.out_dir, "wardrop.txt"), "w") as f:
        def pr(*a):
            line = " ".join(str(x) for x in a)
            print(line)
            f.write(line + "\n")

        pr("================ Wardrop's first principle at the duaIterate DUE ================")
        used = [l for l in labels if equi.get(f"n_{l}", 0) > 0]
        pr(f"Equilibrium split: " + ", ".join(f"{l}={equi[f'n_{l}']}" for l in labels) + f" (total {equi['arrived']})")
        pr(f"Paths used: {used}" + (" -- all paths used, no cheaper unused alternative" if len(used) == len(labels) else " -- some paths UNUSED, check why"))
        pr("")
        if len(used) == 2:
            l1, l2 = used
            d, rel = gap(equi[f"dur_{l1}"], equi[f"dur_{l2}"])
            pr(f"(A) IN-NETWORK duration: {l1}={equi[f'dur_{l1}']:.1f}s  {l2}={equi[f'dur_{l2}']:.1f}s  "
               f"gap={d:+.1f}s ({rel:.1f}%)  -> {'EQUAL' if rel < args.threshold_pct else 'NOT equal'} (<{args.threshold_pct:.0f}%)")
            dt, trel = gap(equi[f"total_{l1}"], equi[f"total_{l2}"])
            pr(f"(B) TOTAL experienced time (duration+departDelay): {l1}={equi[f'total_{l1}']:.1f}s  {l2}={equi[f'total_{l2}']:.1f}s  "
               f"gap={dt:+.1f}s ({trel:.1f}%)  -> {'EQUAL' if trel < args.threshold_pct else 'NOT equal'} (<{args.threshold_pct:.0f}%)")
            pr("")
            pr("VERDICT: Wardrop's first principle is satisfied for whichever of (A)/(B) shows 'EQUAL' above.")
            pr("If (A) is equal but (B) is not, the gap is departDelay (origin insertion queueing) that")
            pr("duaIterate's edge-weight route choice cannot see -- investigate whether it's a genuine split")
            pr("error or a departure-time/insertion-ordering artifact (see the skill's Gotchas) before concluding")
            pr("the equilibrium itself is wrong.")
        else:
            pr("Wardrop check requires exactly 2 used paths for this script's pairwise comparison; extend for 3+.")

        pr("")
        pr("================ Network performance: one-shot vs equilibrium ================")
        for k, label in [("mean_total", "mean total time (departDelay + in-network)"),
                          ("mean_duration", "mean in-network duration"),
                          ("mean_timeLoss", "mean time loss"),
                          ("mean_departDelay", "mean departure delay")]:
            b, e = base[k], equi[k]
            ch = 100 * (e - b) / b if b else float("nan")
            pr(f"  {label:42s}: one-shot={b:8.1f}  equilibrium={e:8.1f}  ({ch:+.1f}%)")

    print(f"\nWrote {args.out_dir}/comparison.csv, wardrop.txt" + (", convergence.csv" if args.dua_dir else ""))


if __name__ == "__main__":
    main()
