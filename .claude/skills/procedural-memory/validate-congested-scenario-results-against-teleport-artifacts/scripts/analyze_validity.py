#!/usr/bin/env python3
"""
Analyse the validity test: does the perimeter-gating benefit survive
teleport-free accounting?

Four estimators of the gating effect on travel time:
  A  ttt=300, mean over ALL completed trips        <- the original episode's convention
  B  ttt=300, mean over each arm's TELEPORT-FREE trips
  B' ttt=300, mean over the COMMON cohort: vehicles that completed AND were
     teleport-free in BOTH arms, matched vehicle-by-vehicle (the cleanest
     like-for-like estimator; removes the "different populations" objection
     that B alone is open to)
  C  ttt=-1 (teleporting disabled), mean over ALL completed trips
     -- reported together with completion count, because C's mean is CENSORED:
     permanently deadlocked vehicles never enter tripinfo at all.
"""
import argparse
import csv
import json
import math
import os
import re
import statistics
import xml.etree.ElementTree as ET

TELE_RE = re.compile(r"Teleporting vehicle '([^']+)'")
T975 = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306}


def ci95(v):
    v = [x for x in v if x is not None]
    if len(v) < 2:
        return None
    s = statistics.stdev(v)
    return T975.get(len(v) - 1, 1.96) * s / math.sqrt(len(v))


def mean(v):
    v = [x for x in v if x is not None]
    return statistics.mean(v) if v else None


def load_run(d):
    tele = set()
    with open(os.path.join(d, "sumo.log"), errors="replace") as fh:
        for line in fh:
            m = TELE_RE.search(line)
            if m:
                tele.add(m.group(1))
    dur = {}
    for _, el in ET.iterparse(os.path.join(d, "tripinfo.xml"), events=("end",)):
        if el.tag == "tripinfo":
            dur[el.get("id")] = float(el.get("duration"))
            el.clear()
    return dur, tele


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    res = json.load(open(a.results))
    idx = {(r["level"], r["ttt"], r["cfg"], r["seed"]): r for r in res}
    seeds = sorted({r["seed"] for r in res})

    with open(os.path.join(a.outdir, "validity_cells_raw.csv"), "w", newline="") as fh:
        cols = ["level", "ttt", "cfg", "seed", "completed", "teleports_cum",
                "teleport_vehicles", "clearance_time", "end_running", "end_waiting",
                "mean_net_speed", "all_mean_duration", "free_n", "free_mean_duration",
                "inert_violations"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for k in sorted(idx):
            w.writerow(idx[k])

    out = []
    P = out.append
    P("PERIMETER-GATING VALIDITY TEST UNDER COMPETING TELEPORT CONVENTIONS")
    P("controller: n_set=60 veh (core), K=1.5 s/veh, g_min=0.25*g0, 60 s control "
      "interval, 16 gate junctions, g0=84 s of a 90 s cycle")
    P("inert violations across all 40 runs (state emitted != static program while "
      "r=1): %d" % sum(r.get("inert_violations", 0) for r in res))
    P("")

    rows_summary = []
    for level in ["OS-A", "OS-B"]:
        P("=" * 100)
        P("LEVEL %s" % level)
        P("=" * 100)
        P("%-30s %12s %12s %14s %10s" %
          ("estimator", "baseline", "gated", "effect", "seeds impr."))

        def line(label, get, lower_better=True, fmt="%.1f"):
            b, t = [], []
            for s in seeds:
                rb, rt = get(level, s, "base"), get(level, s, "gated")
                if rb is None or rt is None:
                    continue
                b.append(rb)
                t.append(rt)
            if not b:
                return
            imp = sum(1 for x, y in zip(b, t) if (y < x if lower_better else y > x))
            mb, mt = mean(b), mean(t)
            eff = (mt - mb) / mb * 100 if mb else float("nan")
            P("%-30s %12s %12s %13.1f%% %6d/%d" %
              (label, fmt % mb, fmt % mt, eff, imp, len(b)))
            rows_summary.append(dict(level=level, estimator=label,
                                     baseline_mean=round(mb, 3), gated_mean=round(mt, 3),
                                     baseline_ci95=round(ci95(b), 3) if ci95(b) else "",
                                     gated_ci95=round(ci95(t), 3) if ci95(t) else "",
                                     effect_pct=round(eff, 2),
                                     seeds_improved="%d/%d" % (imp, len(b)),
                                     per_seed_pct=";".join(
                                         "%.1f" % ((y - x) / x * 100) if x else "inf"
                                         for x, y in zip(b, t))))

        def m300(k):
            return lambda lv, s, c: idx[(lv, "300", c, s)][k]

        def mm1(k):
            return lambda lv, s, c: idx[(lv, "-1", c, s)][k]

        P("-- convention A: default teleporting (ttt=300) --")
        line("A  mean duration, ALL trips", m300("all_mean_duration"))
        line("   completed trips", m300("completed"), False)
        line("   teleports (cumulative)", m300("teleports_cum"))
        line("   mean network speed m/s", m300("mean_net_speed"), False, "%.3f")
        P("-- convention B: default teleporting, teleport-free trips only --")
        line("B  mean duration, TELE-FREE", m300("free_mean_duration"))

        # B' : common cohort, matched vehicle-by-vehicle
        bpb, bpt, per = [], [], []
        for s in seeds:
            db, tb = load_run(os.path.join(a.work, "runs", "validity",
                                           "%s_base_ttt300_s%d" % (level, s)))
            dg, tg = load_run(os.path.join(a.work, "runs", "validity",
                                           "%s_gated_ttt300_s%d" % (level, s)))
            common = (set(db) & set(dg)) - tb - tg
            if not common:
                continue
            mb = statistics.mean(db[v] for v in common)
            mt = statistics.mean(dg[v] for v in common)
            bpb.append(mb)
            bpt.append(mt)
            per.append((s, len(common), round(mb, 1), round(mt, 1),
                        round((mt - mb) / mb * 100, 1)))
        if bpb:
            imp = sum(1 for x, y in zip(bpb, bpt) if y < x)
            eff = (mean(bpt) - mean(bpb)) / mean(bpb) * 100
            P("%-30s %12.1f %12.1f %13.1f%% %6d/%d" %
              ("B' COMMON teleport-free cohort", mean(bpb), mean(bpt), eff, imp, len(bpb)))
            P("      per-seed cohort (seed, n_common, base, gated, %%): %s" % per)
            rows_summary.append(dict(level=level, estimator="B' common tele-free cohort",
                                     baseline_mean=round(mean(bpb), 3),
                                     gated_mean=round(mean(bpt), 3),
                                     baseline_ci95=round(ci95(bpb), 3) if ci95(bpb) else "",
                                     gated_ci95=round(ci95(bpt), 3) if ci95(bpt) else "",
                                     effect_pct=round(eff, 2),
                                     seeds_improved="%d/%d" % (imp, len(bpb)),
                                     per_seed_pct=";".join("%.1f" % p[4] for p in per)))
        P("-- convention C: teleporting DISABLED (ttt=-1) --")
        line("C  mean duration, ALL trips", mm1("all_mean_duration"))
        line("   completed trips", mm1("completed"), False)
        line("   mean network speed m/s", mm1("mean_net_speed"), False, "%.3f")
        line("   vehicles stuck at horizon", mm1("end_running"))
        line("   vehicles never inserted", mm1("end_waiting"))
        P("")

    with open(os.path.join(a.outdir, "validity_summary.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_summary[0].keys()))
        w.writeheader()
        w.writerows(rows_summary)
    txt = "\n".join(out)
    print(txt)
    with open(os.path.join(a.outdir, "validity_report.txt"), "w") as fh:
        fh.write(txt + "\n")


if __name__ == "__main__":
    main()
