#!/usr/bin/env python3
"""Multi-seed sensitivity study of cut-scenario configurations.

The cut scenario turned out to be metastable (a single seed can lock up), so
every configuration is evaluated over 3 seeds and reported as mean +/- sd.
A parent-vs-parent control (same demand, different sumo seed) gives the noise
floor: no cut can be more faithful than the simulator is to itself.

All comparisons are restricted to the CORE evaluation set: edges of the tight
study box whose whole geometry is >= INSET metres inside the box, so that the
metric is about the study area's interior, not the cut face.
"""
import argparse
import math
import os
import statistics
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

INSET = float(os.environ.get("CUT_INSET", "250"))
ZONE = os.environ.get("CUT_ZONE", "core")   # core | band
BOX = (1530.0, 1540.0, 2930.0, 2940.0)
HOURS = 3000.0 / 3600.0   # edgeData window 600..3600 s


def read(path):
    iv = ET.parse(path).getroot().find("interval")
    return {e.get("id"): e for e in iv.findall("edge")}


def f(e, k, d=0.0):
    v = e.get(k)
    return float(v) if v is not None else d


def geh(m, c):
    return 0.0 if m + c == 0 else math.sqrt(2.0 * (m - c) ** 2 / (m + c))


def metrics(parent, cut, eids):
    gehs, ape = [], []
    vp = vc = 0.0
    vktp = vktc = vhtp = vhtc = 0.0
    spn_p = spn_c = spd = ssc_tot = 0.0
    for eid in eids:
        p, c = parent[eid], cut[eid]
        pv = (f(p, "entered") + f(p, "departed")) / HOURS
        cv = (f(c, "entered") + f(c, "departed")) / HOURS
        vp += pv
        vc += cv
        ss_p, ss_c = f(p, "sampledSeconds"), f(c, "sampledSeconds")
        vktp += ss_p * f(p, "speed") / 1000.0
        vktc += ss_c * f(c, "speed") / 1000.0
        vhtp += ss_p / 3600.0
        vhtc += ss_c / 3600.0
        spn_p += f(p, "speed") * ss_p
        spn_c += f(c, "speed") * ss_c
        spd += ss_p
        ssc_tot += ss_c
        if pv < 1 and cv < 1:
            continue
        gehs.append(geh(cv, pv))
        if pv > 0:
            ape.append(abs(cv - pv) / pv)
    n = len(gehs)
    return {
        "n": n,
        "geh_mean": statistics.mean(gehs) if n else float("nan"),
        "geh_p95": sorted(gehs)[int(0.95 * (n - 1))] if n else float("nan"),
        "pct_geh_lt5": 100.0 * sum(1 for g in gehs if g < 5) / n if n else float("nan"),
        "mape": 100.0 * statistics.mean(ape) if ape else float("nan"),
        "vol_err_pct": 100.0 * (vc - vp) / vp if vp else float("nan"),
        "vkt_err_pct": 100.0 * (vktc - vktp) / vktp if vktp else float("nan"),
        "vht_err_pct": 100.0 * (vhtc - vhtp) / vhtp if vhtp else float("nan"),
        # occupancy-weighted mean speed on each side, then relative error
        "speed_err_pct": (100.0 * ((spn_c / ssc_tot) - (spn_p / spd))
                          / (spn_p / spd)) if spd and ssc_tot else float("nan"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent-net", required=True)
    ap.add_argument("--parent-dir", required=True)
    ap.add_argument("--cut-dir", required=True)
    ap.add_argument("--variants", required=True, help="comma separated")
    ap.add_argument("--seeds", default="42,1,2")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    net = sumolib.net.readNet(args.parent_net)
    x0, y0, x1, y1 = BOX
    ref = read(os.path.join(args.parent_dir, "parent_edgedata_steady.xml"))
    seeds = args.seeds.split(",")

    # CORE set: fully inset inside the tight study box AND present in every
    # variant's edgeData (i.e. survives even the tight cut)
    tight = read(os.path.join(args.cut_dir, "edgedata_tight.xml"))
    core = []
    for eid in tight:
        if eid not in ref:
            continue
        try:
            shp = net.getEdge(eid).getShape()
        except KeyError:
            continue
        inside = all(x0 + INSET <= x <= x1 - INSET and y0 + INSET <= y <= y1 - INSET
                     for x, y in shp)
        if (ZONE == "core") == bool(inside):
            core.append(eid)
    print("%s evaluation set: %d edges (inset %g m)" % (ZONE, len(core), INSET))

    rows = []

    # ---- noise floor: parent vs parent, different sumo seed ---------------
    ctrl = []
    for s in ("1", "2"):
        p2 = os.path.join(args.parent_dir, "parent_edgedata_steady_s%s.xml" % s)
        if os.path.exists(p2):
            ctrl.append(metrics(ref, read(p2), core))
    if ctrl:
        rows.append(("PARENT-vs-PARENT (noise floor)", ctrl))

    # ---- variants ---------------------------------------------------------
    for v in args.variants.split(","):
        ms = []
        for s in seeds:
            p = os.path.join(args.cut_dir, "edgedata_%s_s%s.xml" % (v, s))
            if not os.path.exists(p):
                p = os.path.join(args.cut_dir, "edgedata_%s.xml" % v)
            if os.path.exists(p):
                ms.append(metrics(ref, read(p), core))
        if ms:
            rows.append((v, ms))

    keys = ["geh_mean", "geh_p95", "pct_geh_lt5", "mape", "vol_err_pct",
            "vkt_err_pct", "vht_err_pct", "speed_err_pct"]
    hdr = ("| config | seeds | mean GEH | p95 GEH | %GEH<5 | MAPE% | "
           "vol err% | VKT err% | VHT err% | speed err% |")
    md = [hdr, "|" + "---|" * 10]
    for name, ms in rows:
        cells = []
        for k in keys:
            vals = [m[k] for m in ms]
            mu = statistics.mean(vals)
            sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
            cells.append("%.2f ±%.2f" % (mu, sd))
        md.append("| %s | %d | %s |" % (name, len(ms), " | ".join(cells)))
    txt = "\n".join(md)
    print(txt)
    with open(args.out, "w") as fh:
        fh.write("core evaluation set: %d edges (tight study box, inset %g m)\n\n"
                 % (len(core), INSET))
        fh.write(txt + "\n")
    print("\nwrote %s" % args.out)


if __name__ == "__main__":
    main()
