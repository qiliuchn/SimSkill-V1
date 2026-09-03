#!/usr/bin/env python3
"""
behavioral.py -- paired (Common Random Numbers) behavioural comparison of an
original SUMO net against one or more round-tripped versions of the same net.

Design (follows quantify-sumo-run-to-run-variability):
  * demand seed is the dominant variance source -> N replications, seeds 1..N;
  * PAIRED / CRN: replication i uses the SAME randomTrips seed and the SAME
    `sumo --seed` in every arm, so the paired difference removes seed noise;
  * demand is generated ONCE per replication on the ORIGINAL net and then
    TRANSLATED onto each round-trip net through the geometric edge map
    (mapdemand.py) -- so every arm gets the same *geographic* OD pairs even
    though edge ids were renamed by the conversion;
  * routing is done per-arm by duarouter WITHOUT --repair/--ignore-errors, so the
    unroutable-trip count is itself a reported outcome, not silently masked.

Metrics per run: completed trips, mean duration, mean timeLoss, mean waitingTime,
total teleports (last summary step -- the field is cumulative), inserted/running.

Usage:
  python behavioral.py --orig N.net.xml --arm name=NET.net.xml [--arm ...] \
      --out-dir ../runs/x --reps 10 --insertion-rate 900 --end 3600
"""
import argparse
import json
import math
import os
import shutil
import statistics as st
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mapdemand  # noqa: E402


def bin_(n):
    f = shutil.which(n)
    if f:
        return f
    s = shutil.which("sumo")
    if s and os.path.isfile(os.path.join(os.path.dirname(s), n)):
        return os.path.join(os.path.dirname(s), n)
    sys.exit("missing " + n)


SUMO, DUAROUTER = bin_("sumo"), bin_("duarouter")
RT = os.path.join(os.environ["SUMO_HOME"], "tools", "randomTrips.py")


def sh(cmd, log):
    p = subprocess.run(cmd, capture_output=True, text=True)
    open(log, "w").write(" ".join(map(str, cmd)) + "\n\n" + (p.stdout or "") + (p.stderr or ""))
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def parse_tripinfo(f):
    if not os.path.exists(f):
        return None
    dur, tl, wt, rl = [], [], [], []
    for _, el in ET.iterparse(f, events=("end",)):
        if el.tag == "tripinfo":
            dur.append(float(el.get("duration")))
            tl.append(float(el.get("timeLoss")))
            wt.append(float(el.get("waitingTime")))
            rl.append(float(el.get("routeLength")))
            el.clear()
    if not dur:
        return {"completed": 0}
    return {"completed": len(dur), "mean_duration": st.mean(dur),
            "mean_timeloss": st.mean(tl), "mean_waiting": st.mean(wt),
            "mean_routelen": st.mean(rl),
            "total_traveltime": sum(dur)}


def parse_summary(f):
    tel = ins = 0
    last = {}
    if not os.path.exists(f):
        return {}
    for _, el in ET.iterparse(f, events=("end",)):
        if el.tag == "step":
            tel = max(tel, int(el.get("teleports", 0)))
            ins = max(ins, int(el.get("inserted", 0)))
            last = dict(el.attrib)
            el.clear()
    return {"teleports": tel, "inserted": ins, "ended": int(last.get("ended", 0))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig", required=True)
    ap.add_argument("--arm", action="append", default=[], help="name=net.net.xml")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--insertion-rate", type=float, default=900)
    ap.add_argument("--end", type=int, default=3600)
    ap.add_argument("--fringe-factor", default="5")
    ap.add_argument("--vehicle-class", default="passenger")
    ap.add_argument("--edge-tol", type=float, default=25.0)
    ap.add_argument("--common-od", action="store_true",
                    help="keep only trips whose from AND to edge map successfully in "
                         "EVERY arm, so all arms carry an identical trip set "
                         "(strictly paired); otherwise unmapped trips are dropped "
                         "per-arm and offered demand differs between arms.")
    a = ap.parse_args()

    od = os.path.abspath(a.out_dir)
    os.makedirs(os.path.join(od, "logs"), exist_ok=True)
    orig = os.path.abspath(a.orig)
    arms = {"ORIGINAL": orig}
    adds = {}
    for s in a.arm:
        n, p = s.split("=", 1)
        # "name=net.net.xml[,additional.add.xml]" -- the additional file is how a
        # REPAIR (e.g. transplanted tlLogic from repair_tls.py) is applied.
        if "," in p:
            p, ad = p.split(",", 1)
            adds[n] = os.path.abspath(ad)
        arms[n] = os.path.abspath(p)

    # ---- edge maps (ORIGINAL -> arm), geometric
    maps, mapinfo = {}, {}
    for n, p in arms.items():
        if n == "ORIGINAL":
            continue
        m, info = mapdemand.build_map(orig, p, a.edge_tol)
        maps[n], mapinfo[n] = m, info
        print(f"edge map ORIGINAL->{n}: {info}")

    common = None
    if a.common_od and maps:
        common = set.intersection(*(set(m) for m in maps.values()))
        print(f"common-OD edge set across all arms: {len(common)} edges")

    results = {n: [] for n in arms}
    routing = {n: [] for n in arms}
    for rep in range(1, a.reps + 1):
        base = os.path.join(od, f"rep{rep}")
        trips = base + ".trips.xml"
        rc, out = sh([sys.executable, RT, "-n", orig, "-o", trips,
                      "-b", "0", "-e", str(a.end),
                      "--insertion-rate", str(a.insertion_rate),
                      "--fringe-factor", a.fringe_factor,
                      "--vehicle-class", a.vehicle_class,
                      "--seed", str(rep), "--validate"],
                     os.path.join(od, "logs", f"rep{rep}_trips.log"))
        if rc != 0:
            sys.exit("randomTrips failed rep %d: %s" % (rep, out[-800:]))
        if common is not None:
            tr = ET.parse(trips)
            rt_ = tr.getroot()
            for el in list(rt_):
                if el.tag in ("trip", "vehicle") and not (
                        el.get("from") in common and el.get("to") in common):
                    rt_.remove(el)
            tr.write(trips, encoding="UTF-8", xml_declaration=True)
        for name, net in arms.items():
            t = trips
            if name != "ORIGINAL":
                t = f"{base}_{name}.trips.xml"
                mapdemand.rewrite(trips, t, maps[name])
            rou = f"{base}_{name}.rou.xml"
            rc, out = sh([DUAROUTER, "-n", net, "-r", t, "-o", rou,
                          "--seed", str(rep), "--no-warnings", "true"],
                         os.path.join(od, "logs", f"rep{rep}_{name}_duarouter.log"))
            n_in = sum(1 for _ in ET.parse(t).getroot() if _.tag in ("trip", "vehicle"))
            n_out = 0
            if os.path.exists(rou):
                n_out = sum(1 for _ in ET.parse(rou).getroot() if _.tag == "vehicle")
            routing[name].append({"rep": rep, "trips_in": n_in, "routed": n_out,
                                  "unroutable": n_in - n_out})
            ti = f"{base}_{name}.tripinfo.xml"
            su = f"{base}_{name}.summary.xml"
            extra = ["--additional-files", adds[name]] if name in adds else []
            rc, out = sh([SUMO, "-n", net, "-r", rou, "--tripinfo-output", ti,
                          "--summary-output", su, "-e", str(a.end + 2400),
                          "--seed", str(rep), "--no-step-log", "true",
                          "--time-to-teleport", "300",
                          "--duration-log.statistics", "true",
                          "--no-warnings", "true"] + extra,
                         os.path.join(od, "logs", f"rep{rep}_{name}_sumo.log"))
            r = parse_tripinfo(ti) or {"completed": 0}
            r.update(parse_summary(su))
            r["rep"] = rep
            r["demand_offered"] = n_in
            results[name].append(r)
        print(f"rep {rep}: " + "  ".join(
            f"{n}=completed {results[n][-1].get('completed')}/{results[n][-1].get('demand_offered')}"
            f" dur {results[n][-1].get('mean_duration', float('nan')):.1f}" for n in arms))

    # ---- paired statistics vs ORIGINAL
    METRICS = ["completed", "mean_duration", "mean_timeloss", "mean_waiting",
               "mean_routelen", "teleports"]
    summary = {"mapinfo": mapinfo, "reps": a.reps,
               "insertion_rate": a.insertion_rate, "arms": {}}
    for name in arms:
        s = {}
        for k in METRICS:
            v = [r.get(k, 0) or 0 for r in results[name]]
            s[k] = {"mean": round(st.mean(v), 4),
                    "sd": round(st.stdev(v), 4) if len(v) > 1 else 0.0}
        if name != "ORIGINAL":
            for k in METRICS:
                d = [(results[name][i].get(k, 0) or 0) - (results["ORIGINAL"][i].get(k, 0) or 0)
                     for i in range(a.reps)]
                md = st.mean(d)
                sd = st.stdev(d) if len(d) > 1 else 0.0
                se = sd / math.sqrt(len(d)) if sd else 0.0
                # 95% CI, t approx for n=10 -> 2.262 ; use 1.96 fallback for large n
                tcrit = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447,
                         8: 2.365, 9: 2.306, 10: 2.262, 11: 2.228, 12: 2.201,
                         15: 2.145, 20: 2.093, 30: 2.045}.get(len(d), 2.0)
                s[k]["paired_diff_vs_ORIGINAL"] = round(md, 4)
                s[k]["paired_ci95"] = [round(md - tcrit * se, 4), round(md + tcrit * se, 4)]
                s[k]["significant_at_95"] = bool(se > 0 and abs(md) > tcrit * se)
                base = st.mean([results["ORIGINAL"][i].get(k, 0) or 0 for i in range(a.reps)])
                s[k]["pct_change"] = round(100 * md / base, 3) if base else None
        s["per_rep"] = results[name]
        s["routing"] = routing[name]
        s["unroutable_total"] = sum(x["unroutable"] for x in routing[name])
        s["net"] = arms[name]
        s["additional"] = adds.get(name)
        summary["arms"][name] = s

    json.dump(summary, open(os.path.join(od, "behavioral.json"), "w"), indent=1)
    # console table
    print("\n| arm | completed | mean dur (s) | mean timeLoss (s) | mean routeLen (m) | teleports | unroutable |")
    print("|---|---|---|---|---|---|---|")
    for n in arms:
        s = summary["arms"][n]
        def c(k):
            x = s[k]
            t = f"{x['mean']:.1f}±{x['sd']:.1f}"
            if "paired_diff_vs_ORIGINAL" in x:
                pc = x["pct_change"]
                pcs = f"{pc:+.1f}%" if pc is not None else f"{x['paired_diff_vs_ORIGINAL']:+.2f}abs"
                t += f" ({pcs}{'*' if x['significant_at_95'] else ''})"
            return t
        print(f"| {n} | {c('completed')} | {c('mean_duration')} | {c('mean_timeloss')} "
              f"| {c('mean_routelen')} | {c('teleports')} | {s['unroutable_total']} |")
    print("* = paired 95% CI excludes 0")
    print("wrote", os.path.join(od, "behavioral.json"))


if __name__ == "__main__":
    main()
