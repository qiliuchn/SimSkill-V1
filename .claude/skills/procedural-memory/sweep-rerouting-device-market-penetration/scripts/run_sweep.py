#!/usr/bin/env python3
"""Drive the rerouting-device market-penetration sweep.

Cells = scenario x penetration x seed.

Scenarios
  incident_fast    incident ON,  aggressive/fast-updating device
                   (adaptation-interval 1 s, adaptation-steps 4 -> ~4 s memory)
  incident_smooth  incident ON,  smoothed device
                   (adaptation-interval 60 s, adaptation-steps 10 -> ~600 s memory)
  incident_rnd     incident ON,  fast device + --weights.random-factor 1.4
                   (herding-mitigation test: randomizes each vehicle's perceived
                   edge weights so they do not all compute the same "best" route)
  noincident_fast  incident OFF, aggressive device (honest control: with no
                   disruption, information should confer little or no benefit)

Replication / CRN
  Departure times are byte-identical in every cell.  A seed does two things:
  it selects which vehicles are equipped (nested in penetration) and it seeds
  SUMO itself.  The same seed list is reused in every cell, i.e. Common Random
  Numbers, so paired comparisons across penetration levels share their noise.

Per-run isolation
  Every run gets its OWN directory and its OWN copy of the edgeData additional
  file.  edgeData's `file=` resolves relative to the additional file's own
  directory, so sharing one additional file across parallel workers would make
  them silently overwrite each other's edge output.

Outputs per run: tripinfo.xml, edgedata.xml (30 s), summary.xml, stats.xml, and
vehroutes.xml (kept only for the designated raw-keep seed; parsed then deleted
otherwise, since 240 vehroute files is several hundred MB of bulk trace).
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, "gen_demand.py")

SCENARIOS = {
    # name           : (incident?, extra sumo args)
    "incident_fast":   (True, ["--device.rerouting.adaptation-interval", "1",
                               "--device.rerouting.adaptation-steps", "4"]),
    "incident_smooth": (True, ["--device.rerouting.adaptation-interval", "60",
                               "--device.rerouting.adaptation-steps", "10"]),
    "incident_rnd":    (True, ["--device.rerouting.adaptation-interval", "1",
                               "--device.rerouting.adaptation-steps", "4",
                               "--weights.random-factor", "1.4"]),
    "noincident_fast": (False, ["--device.rerouting.adaptation-interval", "1",
                                "--device.rerouting.adaptation-steps", "4"]),
}

INCIDENT_BEGIN, INCIDENT_END = 900.0, 2400.0


def edgedata_add(path, period=30):
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<additional>\n')
        f.write('  <edgeData id="ed" file="edgedata.xml" period="%d" excludeEmpty="false"/>\n' % period)
        f.write('</additional>\n')


def classify_last_route(veh):
    """The route a vehicle ACTUALLY drove is the LAST <route> of its <routeDistribution>.

    Reading the first one instead is the classic misclassification bug: it makes
    every rerouted vehicle look like it stayed on its original (main) route.
    """
    rd = veh.find("routeDistribution")
    routes = rd.findall("route") if rd is not None else [veh.find("route")]
    seq = ["alt" if " AP " in " " + r.get("edges") + " " else "main" for r in routes]
    switches = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
    return seq[-1], switches, len(seq)


def run_one(job):
    (workdir, net, cfgdir, scenario, pen, seed, vph, end, keep_raw) = job
    inc, extra = SCENARIOS[scenario]
    tag = "%s_p%03d_s%02d" % (scenario, int(round(pen * 100)), seed)
    d = os.path.join(workdir, scenario, tag)
    os.makedirs(d, exist_ok=True)

    rou = os.path.join(d, "demand.rou.xml")
    subprocess.run([sys.executable, GEN, "--out", rou, "--penetration", str(pen),
                    "--seed", str(seed), "--veh-per-hour", str(vph)],
                   check=True, capture_output=True)
    eadd = os.path.join(d, "edgedata.add.xml")
    edgedata_add(eadd)
    incadd = os.path.join(cfgdir, "incident.add.xml" if inc else "noincident.add.xml")

    cmd = ["sumo", "-n", net, "-r", rou, "-a", incadd + "," + eadd,
           "--tripinfo-output", os.path.join(d, "tripinfo.xml"),
           "--summary-output", os.path.join(d, "summary.xml"),
           "--statistic-output", os.path.join(d, "stats.xml"),
           "--vehroute-output", os.path.join(d, "vehroutes.xml"),
           "--vehroute-output.exit-times", "true",
           "--device.rerouting.period", "30",
           "--device.rerouting.pre-period", "10",
           "--begin", "0", "--end", str(end),
           "--time-to-teleport", "300", "--no-step-log", "true",
           "--seed", str(seed)] + extra
    with open(os.path.join(d, "cmd.txt"), "w") as f:
        f.write(" ".join(cmd) + "\n")
    r = subprocess.run(cmd, capture_output=True, text=True)
    with open(os.path.join(d, "sumo.stderr.txt"), "w") as f:
        f.write(r.stderr)
    if r.returncode != 0:
        return {"scenario": scenario, "penetration": pen, "seed": seed, "error": r.stderr[-500:]}

    # ---- route classification per vehicle (from vehroute) ----
    route_of, switch_of = {}, {}
    n_route_entries = {}
    for v in ET.parse(os.path.join(d, "vehroutes.xml")).getroot().findall("vehicle"):
        rt, sw, nr = classify_last_route(v)
        route_of[v.get("id")] = rt
        switch_of[v.get("id")] = sw
        n_route_entries[v.get("id")] = nr

    # ---- tripinfo partitioned by vType (= equipped / unequipped) ----
    agg = {}
    for grp in ("equipped", "unequipped", "all", "cohort_equipped",
                "cohort_unequipped", "cohort_all"):
        agg[grp] = []
    div = {"equipped": [0, 0], "unequipped": [0, 0]}      # [alt, total]
    cohort_div = {"equipped": [0, 0], "unequipped": [0, 0]}
    dev_mismatch = 0
    switches_eq = []
    for ti in ET.parse(os.path.join(d, "tripinfo.xml")).getroot().findall("tripinfo"):
        vid = ti.get("id")
        vt = ti.get("vType")
        devices = ti.get("devices") or ""
        has_dev = "routing_" in devices
        if (vt == "equipped") != has_dev:
            dev_mismatch += 1
        dur = float(ti.get("duration"))
        dd = float(ti.get("departDelay"))
        tot = dur + dd                 # total experienced time
        dep = float(ti.get("depart"))
        agg[vt].append(tot)
        agg["all"].append(tot)
        div[vt][1] += 1
        if route_of.get(vid) == "alt":
            div[vt][0] += 1
        if INCIDENT_BEGIN <= dep < INCIDENT_END:
            agg["cohort_" + vt].append(tot)
            agg["cohort_all"].append(tot)
            cohort_div[vt][1] += 1
            if route_of.get(vid) == "alt":
                cohort_div[vt][0] += 1
        if vt == "equipped":
            switches_eq.append(switch_of.get(vid, 0))

    # ---- route-split time series (for the oscillation metric) ----
    ts = []
    for iv in ET.parse(os.path.join(d, "edgedata.xml")).getroot().findall("interval"):
        tb = float(iv.get("begin"))
        ent = {"AC": 0.0, "AP": 0.0}
        for ed in iv.findall("edge"):
            if ed.get("id") in ent:
                ent[ed.get("id")] = float(ed.get("entered") or 0)
        tot = ent["AC"] + ent["AP"]
        ts.append((tb, ent["AP"], ent["AC"], (ent["AP"] / tot) if tot > 0 else None))
    with open(os.path.join(d, "route_split_timeseries.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_begin", "alt_entered", "main_entered", "alt_share"])
        for row in ts:
            w.writerow([row[0], row[1], row[2], "" if row[3] is None else "%.6f" % row[3]])

    tel = 0
    try:
        st = ET.parse(os.path.join(d, "stats.xml")).getroot().find("teleports")
        tel = int(st.get("total")) if st is not None else 0
    except Exception:
        pass

    def mean(x):
        return sum(x) / len(x) if x else float("nan")

    res = {
        "scenario": scenario, "penetration": pen, "seed": seed,
        "n_all": len(agg["all"]), "n_equipped": len(agg["equipped"]),
        "n_unequipped": len(agg["unequipped"]),
        "mean_tt_all": mean(agg["all"]),
        "mean_tt_equipped": mean(agg["equipped"]),
        "mean_tt_unequipped": mean(agg["unequipped"]),
        "total_tt_all": sum(agg["all"]),
        "mean_tt_cohort_all": mean(agg["cohort_all"]),
        "mean_tt_cohort_equipped": mean(agg["cohort_equipped"]),
        "mean_tt_cohort_unequipped": mean(agg["cohort_unequipped"]),
        "n_cohort": len(agg["cohort_all"]),
        "alt_share_equipped": (div["equipped"][0] / div["equipped"][1]) if div["equipped"][1] else float("nan"),
        "alt_share_unequipped": (div["unequipped"][0] / div["unequipped"][1]) if div["unequipped"][1] else float("nan"),
        "alt_share_overall": (div["equipped"][0] + div["unequipped"][0]) / max(1, len(agg["all"])),
        "cohort_alt_share_equipped": (cohort_div["equipped"][0] / cohort_div["equipped"][1]) if cohort_div["equipped"][1] else float("nan"),
        "mean_route_switches_equipped": mean(switches_eq),
        "teleports": tel,
        "device_vtype_mismatches": dev_mismatch,
        "error": "",
    }

    if not keep_raw:
        os.remove(os.path.join(d, "vehroutes.xml"))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--cfgdir", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scenarios", nargs="+", default=list(SCENARIOS))
    ap.add_argument("--penetrations", type=float, nargs="+",
                    default=[0.0, 0.1, 0.25, 0.5, 0.75, 1.0])
    ap.add_argument("--seeds", type=int, nargs="+", default=list(range(1, 11)))
    ap.add_argument("--vph", type=float, default=2500.0)
    ap.add_argument("--end", type=int, default=14400)
    ap.add_argument("--keep-raw-seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=10)
    a = ap.parse_args()

    net = os.path.abspath(a.net)
    cfg = os.path.abspath(a.cfgdir)
    work = os.path.abspath(a.workdir)
    os.makedirs(work, exist_ok=True)
    jobs = [(work, net, cfg, sc, p, sd, a.vph, a.end, sd == a.keep_raw_seed)
            for sc in a.scenarios for p in a.penetrations for sd in a.seeds]
    print("running %d cells on %d workers" % (len(jobs), a.jobs))

    cols = ["scenario", "penetration", "seed", "n_all", "n_equipped", "n_unequipped",
            "mean_tt_all", "mean_tt_equipped", "mean_tt_unequipped", "total_tt_all",
            "mean_tt_cohort_all", "mean_tt_cohort_equipped", "mean_tt_cohort_unequipped",
            "n_cohort", "alt_share_equipped", "alt_share_unequipped", "alt_share_overall",
            "cohort_alt_share_equipped", "mean_route_switches_equipped",
            "teleports", "device_vtype_mismatches", "error"]
    rows, done = [], 0
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for r in ex.map(run_one, jobs):
            rows.append(r)
            done += 1
            if r.get("error"):
                print("  ERROR %s p=%s s=%s : %s" % (r["scenario"], r["penetration"], r["seed"], r["error"]))
            if done % 20 == 0:
                print("  %d/%d" % (done, len(jobs)))
                sys.stdout.flush()
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    bad = sum(r.get("device_vtype_mismatches", 0) or 0 for r in rows)
    print("wrote %s (%d rows). total vType-vs-device mismatches across ALL runs: %d" % (a.out, len(rows), bad))


if __name__ == "__main__":
    main()
