#!/usr/bin/env python3
"""
Surrogate-safety analysis of the SSM runs.

Discipline (from analyze-intersection-safety-with-ssm):
  * SUMO writes each encounter TWICE (once per ego) -- deduplicate by unordered
    vehicle pair + begin time, or every count is doubled.
  * classify by encounter TYPE code (2,3,18 rear-end; 6,7,8,19 merging;
    10-17 crossing; 111 "collision") AND by movement pair; check every type=111
    for the degenerate collinear-opposing-left artifact (TTC/PET NA or 0.00).
  * conflicts are LOCALISED (main junction vs crossover vs open link) from the
    reported conflict position, so "eliminated" can be told apart from "relocated".
  * counts are normalised per 1000 veh-km, because the alternatives deliberately
    generate MORE veh-km -- a raw count comparison would be biased.
"""
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from analyze import load_routes  # noqa: E402
from demand import movement_class  # noqa: E402

REAR = {2, 3, 18}
MERGE = {6, 7, 8, 19}
CROSS = set(range(10, 18))
COLL = {111}
NEAR = 55.0     # radius (m) used to attribute a conflict to a junction


def region(x, y, D):
    for name, cx in (("J", 0.0), ("XW", -D), ("XE", D)):
        if math.hypot(x - cx, y) <= NEAR:
            return name
    return "link"


def parse(rundir):
    meta = json.load(open(os.path.join(rundir, "meta.json")))
    D = float(meta["D"])
    routes = load_routes(meta["route_file"])
    vcls = {v: movement_class(o, d) for v, (o, d, e, u) in routes.items()}
    seen = set()
    rows = []
    for _, cf in ET.iterparse(os.path.join(rundir, "ssm.xml"), events=("end",)):
        if cf.tag != "conflict":
            continue
        e, f, b = cf.get("ego"), cf.get("foe"), cf.get("begin")
        k = (min(e, f), max(e, f), b)
        if k in seen:
            cf.clear()
            continue
        seen.add(k)
        rec = {"ego": e, "foe": f, "begin": float(b),
               "ego_class": vcls.get(e, "?"), "foe_class": vcls.get(f, "?")}
        for meas in ("minTTC", "maxDRAC", "PET"):
            el = cf.find(meas)
            if el is None:
                continue
            val, typ, pos = el.get("value"), el.get("type"), el.get("position")
            rec[meas] = None if val in (None, "NA") else float(val)
            if typ not in (None, "NA"):
                rec.setdefault("type", int(float(typ)))
            if pos not in (None, "NA") and "x" not in rec:
                x, y = [float(t) for t in pos.split(",")]
                rec["x"], rec["y"] = x, y
                rec["region"] = region(x, y, D)
        rec.setdefault("type", -1)
        rec.setdefault("region", "unknown")
        rows.append(rec)
        cf.clear()
    return meta, rows


def summarize(rundir):
    meta, rows = parse(rundir)
    tot_vmt = 0.0
    for _, t in ET.iterparse(os.path.join(rundir, "tripinfo.xml"), events=("end",)):
        if t.tag == "tripinfo":
            tot_vmt += float(t.get("routeLength"))
            t.clear()
    vmt_kkm = tot_vmt / 1e6      # thousands of veh-km

    def cat(ty):
        return ("rear" if ty in REAR else "merge" if ty in MERGE else
                "cross" if ty in CROSS else "collision_flag" if ty in COLL else "other")

    out = {"run": os.path.basename(rundir), "variant": meta["variant"],
           "D": meta["D"], "Q": meta["Q"], "m": meta["m"], "seed": meta["seed"],
           "veh_km": tot_vmt / 1000.0, "n_conflicts": len(rows)}
    byreg = defaultdict(int)
    bycat = defaultdict(int)
    bycatreg = defaultdict(int)
    severe_ttc = defaultdict(int)
    severe_pet = defaultdict(int)
    art111 = []
    for r in rows:
        c = cat(r["type"])
        byreg[r["region"]] += 1
        bycat[c] += 1
        bycatreg[f"{c}@{r['region']}"] += 1
        if r.get("minTTC") is not None and r["minTTC"] < 1.5:
            severe_ttc[r["region"]] += 1
        if r.get("PET") is not None and r["PET"] < 1.0:
            severe_pet[r["region"]] += 1
        if r["type"] in COLL:
            deg = (r.get("minTTC") in (None, 0.0)) and (r.get("PET") in (None, 0.0))
            art111.append({"pair": (r["ego_class"], r["foe_class"]), "region": r["region"],
                           "minTTC": r.get("minTTC"), "PET": r.get("PET"),
                           "degenerate": deg})
    out["by_region"] = dict(byreg)
    out["by_category"] = dict(bycat)
    out["by_category_region"] = dict(bycatreg)
    out["severe_TTC_lt_1.5"] = dict(severe_ttc)
    out["severe_PET_lt_1.0"] = dict(severe_pet)
    out["n_type111"] = len(art111)
    out["n_type111_degenerate"] = sum(1 for a in art111 if a["degenerate"])
    out["type111_examples"] = art111[:10]
    out["rate_per_1000vkm"] = {k: v / vmt_kkm / 1000.0 * 1000.0 if False else v / (tot_vmt / 1000.0) * 1000.0
                               for k, v in byreg.items()}
    out["total_rate_per_1000vkm"] = len(rows) / (tot_vmt / 1000.0) * 1000.0
    out["severe_TTC_rate_per_1000vkm"] = sum(severe_ttc.values()) / (tot_vmt / 1000.0) * 1000.0
    out["severe_PET_rate_per_1000vkm"] = sum(severe_pet.values()) / (tot_vmt / 1000.0) * 1000.0
    return out


def main(runroot):
    res = []
    for n in sorted(os.listdir(runroot)):
        d = os.path.join(runroot, n)
        if n.startswith("ssm_") and os.path.exists(os.path.join(d, "ssm.xml")):
            res.append(summarize(d))
    with open(os.path.join(ROOT, "results", "ssm_summary.json"), "w") as f:
        json.dump(res, f, indent=1)
    # aggregate per (cell, variant)
    agg = defaultdict(list)
    for r in res:
        agg[(r["D"], r["Q"], r["m"], r["variant"])].append(r)
    print(f"{'cell':22s} {'var':5s} {'vkm':>9s} {'confl':>7s} {'/1000vkm':>9s} "
          f"{'sevTTC/1k':>10s} {'sevPET/1k':>10s} {'@J':>7s} {'@Xover':>7s} {'@link':>7s} {'111deg':>7s}")
    for k in sorted(agg):
        rs = agg[k]
        n = len(rs)
        def mn(f):
            return sum(f(r) for r in rs) / n
        print(f"D{int(k[0])}_Q{int(k[1])}_m{int(k[2]*100)}     {k[3]:5s} "
              f"{mn(lambda r: r['veh_km']):9.0f} {mn(lambda r: r['n_conflicts']):7.0f} "
              f"{mn(lambda r: r['total_rate_per_1000vkm']):9.2f} "
              f"{mn(lambda r: r['severe_TTC_rate_per_1000vkm']):10.2f} "
              f"{mn(lambda r: r['severe_PET_rate_per_1000vkm']):10.2f} "
              f"{mn(lambda r: r['by_region'].get('J', 0)):7.0f} "
              f"{mn(lambda r: r['by_region'].get('XW', 0) + r['by_region'].get('XE', 0)):7.0f} "
              f"{mn(lambda r: r['by_region'].get('link', 0)):7.0f} "
              f"{mn(lambda r: r['n_type111_degenerate']):7.1f}")
    return res


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "runs"))
