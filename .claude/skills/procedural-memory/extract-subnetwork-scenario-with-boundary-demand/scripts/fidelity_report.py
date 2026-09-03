#!/usr/bin/env python3
"""Fidelity of a cut SUMO sub-scenario against its parent, on shared edges.

Compares per-edge volume (GEH / R^2 / MAPE), mean speed, edge travel time and
aggregate VKT/VHT between the parent run and each cut variant, restricted to
edges that exist in both.  The evaluation set is split into

  core  -- edges whose whole geometry lies >= --inset m inside the study box
  band  -- the remaining kept edges (the boundary ring where cut artifacts live)

so that boundary artifacts can be separated from genuine interior fidelity.

Usage:
  python3 fidelity_report.py --parent-net P.net.xml \
      --parent-edgedata P_steady.xml --box xmin,ymin,xmax,ymax --inset 250 \
      --variant tight=cut/edgedata_tight.xml ... --out-dir report/
"""
import argparse
import math
import os
import sys
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ.get("SUMO_HOME")
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import sumolib  # noqa: E402


def read_edgedata(path):
    """edge id -> dict of measures, for the FIRST interval in the file."""
    root = ET.parse(path).getroot()
    iv = root.find("interval")
    out = {}
    begin, end = float(iv.get("begin")), float(iv.get("end"))
    for e in iv.findall("edge"):
        g = lambda k, d=0.0: float(e.get(k, d))  # noqa: E731
        out[e.get("id")] = {
            "sampledSeconds": g("sampledSeconds"),
            "departed": g("departed"), "arrived": g("arrived"),
            "entered": g("entered"), "left": g("left"),
            "speed": float(e.get("speed")) if e.get("speed") else None,
            "traveltime": float(e.get("traveltime")) if e.get("traveltime") else None,
            "timeLoss": g("timeLoss"),
            "waitingTime": g("waitingTime"),
        }
    return out, begin, end


def volume(d):
    """Vehicles that occupied the edge in the interval = inflow + insertions."""
    return d["entered"] + d["departed"]


def geh(m, c):
    if m + c == 0:
        return 0.0
    return math.sqrt(2.0 * (m - c) ** 2 / (m + c))


def r2(xs, ys):
    """Coefficient of determination of y vs x about the 1:1 line (y = x)."""
    if not xs:
        return float("nan")
    ybar = sum(ys) / len(ys)
    sstot = sum((y - ybar) ** 2 for y in ys)
    ssres = sum((y - x) ** 2 for x, y in zip(xs, ys))
    return 1 - ssres / sstot if sstot > 0 else float("nan")


def pearson_r2(xs, ys):
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return float("nan")
    return (sxy ** 2) / (sxx * syy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent-net", required=True)
    ap.add_argument("--parent-edgedata", required=True)
    ap.add_argument("--box", required=True)
    ap.add_argument("--inset", type=float, default=250.0)
    ap.add_argument("--variant", action="append", required=True,
                    help="name=edgedata.xml (repeatable)")
    ap.add_argument("--variant-net", action="append", default=[],
                    help="name=net.xml (repeatable)")
    ap.add_argument("--min-volume", type=float, default=1.0,
                    help="ignore edges whose parent hourly volume is below this")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    x0, y0, x1, y1 = [float(v) for v in args.box.split(",")]
    net = sumolib.net.readNet(args.parent_net)

    def zone(edge):
        """'core' if the whole edge shape is >= inset inside the box,
        'band' if it touches the box at all, else None."""
        shp = edge.getShape()
        ins = all(x0 + args.inset <= x <= x1 - args.inset and
                  y0 + args.inset <= y <= y1 - args.inset for x, y in shp)
        if ins:
            return "core"
        return "band"

    parent, pb, pe = read_edgedata(args.parent_edgedata)
    hours = (pe - pb) / 3600.0

    variants = {}
    for v in args.variant:
        name, path = v.split("=", 1)
        variants[name] = read_edgedata(path)[0]
    vnets = {}
    for v in args.variant_net:
        name, path = v.split("=", 1)
        vnets[name] = path

    rows = []
    percsv = open(os.path.join(args.out_dir, "per_edge.csv"), "w")
    percsv.write("variant,zone,edge,parent_vph,cut_vph,geh,"
                 "parent_speed,cut_speed,parent_tt,cut_tt\n")

    for name, cut in variants.items():
        # shared edges only
        shared = [eid for eid in cut if eid in parent]
        buckets = {"core": [], "band": []}
        for eid in shared:
            try:
                e = net.getEdge(eid)
            except KeyError:
                continue
            buckets[zone(e)].append(eid)

        for zname in ("core", "band", "all"):
            eids = (buckets["core"] + buckets["band"]) if zname == "all" \
                else buckets[zname]
            xs, ys = [], []
            gehs = []
            sp_p, sp_c, tt_p, tt_c, w = [], [], [], [], []
            vkt_p = vkt_c = vht_p = vht_c = 0.0
            for eid in eids:
                p, c = parent[eid], cut[eid]
                L = net.getEdge(eid).getLength()
                vkt_p += p["sampledSeconds"] * (p["speed"] or 0) / 1000.0
                vkt_c += c["sampledSeconds"] * (c["speed"] or 0) / 1000.0
                vht_p += p["sampledSeconds"] / 3600.0
                vht_c += c["sampledSeconds"] / 3600.0
                pv, cv = volume(p) / hours, volume(c) / hours
                if pv < args.min_volume and cv < args.min_volume:
                    continue
                xs.append(pv)
                ys.append(cv)
                g = geh(cv, pv)
                gehs.append(g)
                if p["speed"] and c["speed"] and p["sampledSeconds"] > 0 \
                        and c["sampledSeconds"] > 0:
                    sp_p.append(p["speed"] * p["sampledSeconds"])
                    sp_c.append(c["speed"] * c["sampledSeconds"])
                    tt_p.append(p["traveltime"] or L / (p["speed"] or 1))
                    tt_c.append(c["traveltime"] or L / (c["speed"] or 1))
                    w.append(p["sampledSeconds"])
                if zname == "all":
                    percsv.write("%s,%s,%s,%.2f,%.2f,%.3f,%.3f,%.3f,%.2f,%.2f\n"
                                 % (name, zone(net.getEdge(eid)), eid, pv, cv, g,
                                    p["speed"] or -1, c["speed"] or -1,
                                    p["traveltime"] or -1, c["traveltime"] or -1))
            n = len(gehs)
            rows.append({
                "variant": name, "zone": zname, "n_edges": n,
                "geh_mean": sum(gehs) / n if n else float("nan"),
                "geh_median": sorted(gehs)[n // 2] if n else float("nan"),
                "pct_geh_lt5": 100.0 * sum(1 for g in gehs if g < 5) / n if n else float("nan"),
                "pct_geh_lt10": 100.0 * sum(1 for g in gehs if g < 10) / n if n else float("nan"),
                "r2_identity": r2(xs, ys),
                "r2_pearson": pearson_r2(xs, ys),
                "mape": 100.0 * sum(abs(y - x) / x for x, y in zip(xs, ys) if x > 0)
                        / max(1, sum(1 for x in xs if x > 0)),
                "vol_parent": sum(xs), "vol_cut": sum(ys),
                "speed_parent": sum(sp_p) / sum(w) if w else float("nan"),
                "speed_cut": sum(sp_c) / sum(w) if w else float("nan"),
                "tt_parent": sum(t * ww for t, ww in zip(tt_p, w)) / sum(w) if w else float("nan"),
                "tt_cut": sum(t * ww for t, ww in zip(tt_c, w)) / sum(w) if w else float("nan"),
                "vkt_parent": vkt_p, "vkt_cut": vkt_c,
                "vht_parent": vht_p, "vht_cut": vht_c,
            })
    percsv.close()

    cols = ["variant", "zone", "n_edges", "geh_mean", "geh_median",
            "pct_geh_lt5", "pct_geh_lt10", "r2_identity", "r2_pearson", "mape",
            "vol_parent", "vol_cut", "speed_parent", "speed_cut",
            "tt_parent", "tt_cut", "vkt_parent", "vkt_cut",
            "vht_parent", "vht_cut"]
    out = os.path.join(args.out_dir, "fidelity_table.csv")
    with open(out, "w") as fh:
        fh.write(",".join(cols) + "\n")
        for r in rows:
            fh.write(",".join(("%s" % r[c]) if isinstance(r[c], str)
                              else "%.4f" % r[c] for c in cols) + "\n")

    # markdown, core + all only
    md = ["| variant | zone | edges | mean GEH | %GEH<5 | R2(1:1) | MAPE% | "
          "vol par/cut (vph) | speed par/cut | VKT par/cut | VHT par/cut |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append("| %s | %s | %d | %.2f | %.1f | %.3f | %.1f | %.0f / %.0f | "
                  "%.2f / %.2f | %.1f / %.1f | %.2f / %.2f |"
                  % (r["variant"], r["zone"], r["n_edges"], r["geh_mean"],
                     r["pct_geh_lt5"], r["r2_identity"], r["mape"],
                     r["vol_parent"], r["vol_cut"], r["speed_parent"],
                     r["speed_cut"], r["vkt_parent"], r["vkt_cut"],
                     r["vht_parent"], r["vht_cut"]))
    mdtxt = "\n".join(md)
    with open(os.path.join(args.out_dir, "fidelity_table.md"), "w") as fh:
        fh.write(mdtxt + "\n")
    print(mdtxt)
    print("\nwrote %s" % out)


if __name__ == "__main__":
    main()
