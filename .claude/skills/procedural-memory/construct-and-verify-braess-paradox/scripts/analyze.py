#!/usr/bin/env python3
"""
Analyse every duaIterate case: Wardrop dual check, route shares, equilibrium link costs,
network mean travel time, and the confound checks (teleports, vehicle loss, identical
demand/schedule across variants).

Adapted from the dual-cost Wardrop check in
.claude/skills/procedural-memory/compute-dynamic-user-equilibrium/scripts/analyze_due.py,
extended from 2 parallel routes to 3 (Braess has upper / lower / zig-zag) and augmented with
per-LINK (not per-edge) equilibrium travel times measured from vehroute exit-times.
"""
import argparse
import csv
import glob
import json
import os
import re
import xml.etree.ElementTree as ET

ROUTES = [("zigzag", "AB"), ("upper_SAT", "AT"), ("lower_SBT", "SB")]
# Braess link -> (predecessor edge in the route, last edge of the link)
LINKS = {"S->A": ("S_in", "SA_b"), "A->T": ("SA_b", "AT"), "S->B": ("S_in", "SB"),
         "B->T": (None, "BT_b"), "A->B": ("SA_b", "AB")}
LINK_PRED_ALT = {"B->T": ["SB", "AB"]}   # B->T can be entered from either SB or AB


def classify(edges):
    s = edges.split()
    for label, m in ROUTES:
        if m in s:
            return label
    return "other"


def parse_record(rec_dir):
    """Per-vehicle route label, in-network duration, departDelay, and per-link travel times."""
    veh = {}
    root = ET.parse(os.path.join(rec_dir, "vehroutes.xml")).getroot()
    for v in root.iter("vehicle"):
        r = v.find("route")
        if r is None:
            continue
        elist = r.get("edges").split()
        ex = [float(x) for x in r.get("exitTimes").split()]
        pos = {e: i for i, e in enumerate(elist)}
        links = {}
        for name, (pred, last) in LINKS.items():
            if last not in pos:
                continue
            preds = [pred] if pred else []
            preds += LINK_PRED_ALT.get(name, [])
            t0 = None
            for p in preds:
                if p in pos and pos[p] < pos[last]:
                    t0 = ex[pos[p]]
            if t0 is not None:
                links[name] = ex[pos[last]] - t0
        veh[v.get("id")] = {"route": classify(r.get("edges", "")), "links": links,
                            "depart_sched": float(v.get("depart"))}
    for t in ET.parse(os.path.join(rec_dir, "tripinfo.xml")).getroot().iter("tripinfo"):
        vid = t.get("id")
        if vid in veh:
            d = float(t.get("duration"))
            dd = float(t.get("departDelay", 0.0))
            veh[vid].update({"duration": d, "departDelay": dd, "total": d + dd,
                             "timeLoss": float(t.get("timeLoss", 0.0))})
    return {k: v for k, v in veh.items() if "duration" in v}


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def spread_pct(vals):
    """max-min spread as a percentage of the mean -- the Wardrop 'approximately equal' metric."""
    vals = [v for v in vals if v == v]
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return 100.0 * (max(vals) - min(vals)) / m if m else float("nan")


def teleport_and_loss(rec_dir):
    err = ""
    p = os.path.join(rec_dir, "sumo.stderr")
    if os.path.exists(p):
        err = open(p).read()
    tele = len(re.findall(r"teleporting", err, re.I))
    stats = {}
    sp = os.path.join(rec_dir, "stats.xml")
    if os.path.exists(sp):
        root = ET.parse(sp).getroot()
        v = root.find("vehicles")
        if v is not None:
            stats = {k: int(v.get(k, 0)) for k in ("loaded", "inserted", "running", "waiting")}
        te = root.find("teleports")
        if te is not None:
            stats["teleports_total"] = int(te.get("total", 0))
    return tele, stats


# link -> LPF key in lpf_fits.json, for the zero-flow fallback cost of an UNUSED link
LPF_KEY = {"S->A": "S->A (flow-dep)", "B->T": "B->T (flow-dep)",
           "A->T": "A->T (flow-indep, isolated)", "S->B": "S->B (flow-indep, isolated)",
           "A->B": None}
ROUTE_LINKS = {"upper_SAT": ["S->A", "A->T"], "lower_SBT": ["S->B", "B->T"],
               "zigzag": ["S->A", "A->B", "B->T"]}


def route_costs(row, lpf):
    """Cost of EVERY route (used or not) from measured link travel times, falling back to the
    fitted free-flow value t0 for a link that carried no vehicles in this equilibrium.
    This is what lets Wardrop's SECOND condition be checked: an unused route must not be
    cheaper than the used ones."""
    lt, imputed = {}, set()
    for lk in LINKS:
        v = row.get(f"link_{lk}_s")
        if v not in ("", None) and row.get(f"link_{lk}_veh", 0) > 0:
            lt[lk] = float(v)
        else:
            key = LPF_KEY.get(lk)
            if key and lpf and key in lpf:
                lt[lk] = lpf[key]["queueing"]["t0_s"]
                imputed.add(lk)
            elif lk == "A->B":
                lt[lk] = 23.6      # measured free-flow cross-link cost
                imputed.add(lk)
    out = {}
    for r, links in ROUTE_LINKS.items():
        if all(l in lt for l in links):
            out[r] = round(sum(lt[l] for l in links), 2)
    return out, imputed


def analyse_case(case_dir, threshold_pct):
    name = os.path.basename(case_dir)
    model, variant, demand = name.split("_")[0], name.split("_")[1], int(name.split("_")[2])
    rec = os.path.join(case_dir, "record")
    veh = parse_record(rec)
    conv = json.load(open(os.path.join(case_dir, "convergence.json")))
    n = len(veh)
    labels = [l for l, _ in ROUTES]
    used = [l for l in labels if sum(1 for v in veh.values() if v["route"] == l) / n >= 0.01]
    tele, stats = teleport_and_loss(rec)

    row = {"model": model, "variant": variant, "demand_vph": demand,
           "n_vehicles": n, "dua_iterations": len(conv["trace"]),
           "final_route_change_pct": conv["trace"][-1]["route_change_pct"],
           "mean_duration_s": round(mean(v["duration"] for v in veh.values()), 2),
           "mean_total_s": round(mean(v["total"] for v in veh.values()), 2),
           "mean_departDelay_s": round(mean(v["departDelay"] for v in veh.values()), 2),
           "mean_timeLoss_s": round(mean(v["timeLoss"] for v in veh.values()), 2),
           "teleports": stats.get("teleports_total", tele),
           "loaded": stats.get("loaded"), "inserted": stats.get("inserted"),
           "still_running_at_end": stats.get("running")}
    for l in labels:
        sub = [v for v in veh.values() if v["route"] == l]
        row[f"share_{l}"] = round(100.0 * len(sub) / n, 2)
        row[f"dur_{l}"] = round(mean(v["duration"] for v in sub), 2) if sub else ""
        row[f"tot_{l}"] = round(mean(v["total"] for v in sub), 2) if sub else ""
        row[f"dd_{l}"] = round(mean(v["departDelay"] for v in sub), 2) if sub else ""
    row["routes_used"] = "|".join(used)
    row["wardrop_innetwork_spread_pct"] = round(
        spread_pct([mean(v["duration"] for v in veh.values() if v["route"] == l) for l in used]), 2)
    row["wardrop_total_spread_pct"] = round(
        spread_pct([mean(v["total"] for v in veh.values() if v["route"] == l) for l in used]), 2)
    row["wardrop_innetwork_ok"] = row["wardrop_innetwork_spread_pct"] < threshold_pct
    row["wardrop_total_ok"] = row["wardrop_total_spread_pct"] < threshold_pct
    for lk in LINKS:
        vals = [v["links"][lk] for v in veh.values() if lk in v["links"]]
        row[f"link_{lk}_s"] = round(mean(vals), 2) if vals else ""
        row[f"link_{lk}_veh"] = len(vals)
    return row, veh, conv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--due-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--threshold-pct", type=float, default=5.0)
    ap.add_argument("--lpf-json", help="lpf_fits.json, for the zero-flow cost of unused links")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    lpf = json.load(open(a.lpf_json)) if a.lpf_json and os.path.exists(a.lpf_json) else None
    rows, sched = [], {}
    for case in sorted(glob.glob(os.path.join(a.due_dir, "*_*_*"))):
        if not os.path.exists(os.path.join(case, "convergence.json")):
            continue
        row, veh, conv = analyse_case(case, a.threshold_pct)
        # Wardrop condition 2: no UNUSED route may be cheaper than the used ones
        rc, imputed = route_costs(row, lpf)
        for r, c in rc.items():
            row[f"routecost_{r}_s"] = c
        row["routecost_imputed_links"] = "|".join(sorted(imputed))
        used_r = [r for r in ROUTE_LINKS if row.get(f"share_{r}", 0) >= 1.0 and r in rc]
        unused_r = [r for r in ROUTE_LINKS if row.get(f"share_{r}", 0) < 1.0 and r in rc]
        if used_r:
            maxused = max(rc[r] for r in used_r)
            row["wardrop_unused_not_cheaper"] = all(rc[r] >= maxused - 1e-6 for r in unused_r)
            row["cheapest_unused_minus_dearest_used_s"] = round(
                min((rc[r] for r in unused_r), default=float("nan")) - maxused, 2) if unused_r else ""
        rows.append(row)
        sched[os.path.basename(case)] = sorted((k, v["depart_sched"]) for k, v in veh.items())
        with open(os.path.join(a.out_dir, f"convergence_{os.path.basename(case)}.csv"), "w",
                  newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(conv["trace"][0].keys()))
            w.writeheader()
            w.writerows(conv["trace"])

    rows.sort(key=lambda r: (r["model"], r["demand_vph"], r["variant"]))
    with open(os.path.join(a.out_dir, "cases.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # ---- paradox table: LINK vs NOLINK per demand level (Gawron)
    by = {(r["model"], r["variant"], r["demand_vph"]): r for r in rows}
    demands = sorted({r["demand_vph"] for r in rows if r["model"] == "gawron"})
    ptab = []
    for d in demands:
        nl, lk = by.get(("gawron", "nolink", d)), by.get(("gawron", "link", d))
        if not nl or not lk:
            continue
        e = {"demand_vph": d,
             "nolink_mean_duration_s": nl["mean_duration_s"], "link_mean_duration_s": lk["mean_duration_s"],
             "delta_duration_pct": round(100 * (lk["mean_duration_s"] - nl["mean_duration_s"]) / nl["mean_duration_s"], 2),
             "nolink_mean_total_s": nl["mean_total_s"], "link_mean_total_s": lk["mean_total_s"],
             "delta_total_pct": round(100 * (lk["mean_total_s"] - nl["mean_total_s"]) / nl["mean_total_s"], 2),
             "link_share_zigzag_pct": lk["share_zigzag"],
             "link_share_upper_pct": lk["share_upper_SAT"], "link_share_lower_pct": lk["share_lower_SBT"],
             "nolink_share_upper_pct": nl["share_upper_SAT"], "nolink_share_lower_pct": nl["share_lower_SBT"],
             "paradox": "YES" if lk["mean_duration_s"] > nl["mean_duration_s"] else "no"}
        ptab.append(e)
    with open(os.path.join(a.out_dir, "paradox_table.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ptab[0].keys()))
        w.writeheader()
        w.writerows(ptab)

    # ---- threshold (linear interpolation of the sign change in delta_duration_pct)
    thr = None
    for i in range(1, len(ptab)):
        a0, b0 = ptab[i - 1]["delta_duration_pct"], ptab[i]["delta_duration_pct"]
        if a0 <= 0 < b0:
            d0, d1 = ptab[i - 1]["demand_vph"], ptab[i]["demand_vph"]
            thr = round(d0 + (d1 - d0) * (0 - a0) / (b0 - a0), 0)
            break
    worst = max(ptab, key=lambda e: e["delta_duration_pct"])

    # ---- confound: identical demand + departure schedule between variants?
    sched_ok = {}
    for d in demands:
        k1, k2 = f"gawron_nolink_{d}", f"gawron_link_{d}"
        if k1 in sched and k2 in sched:
            sched_ok[d] = (sched[k1] == sched[k2])

    summary = {"paradox_threshold_vph": thr,
               "max_degradation_pct": worst["delta_duration_pct"],
               "max_degradation_at_vph": worst["demand_vph"],
               "identical_departure_schedule_across_variants": sched_ok,
               "total_teleports_all_cases": sum(r["teleports"] or 0 for r in rows),
               "cases_with_vehicle_loss": [f'{r["model"]}_{r["variant"]}_{r["demand_vph"]}'
                                           for r in rows
                                           if r["loaded"] != r["inserted"] or r["still_running_at_end"]]}
    json.dump(summary, open(os.path.join(a.out_dir, "summary.json"), "w"), indent=2)
    print(json.dumps(summary, indent=2))
    print("\n demand | NOLINK dur | LINK dur | delta% | zigzag% | Wardrop(in/tot) spread%")
    for e in ptab:
        lk = by[("gawron", "link", e["demand_vph"])]
        print(f" {e['demand_vph']:6d} | {e['nolink_mean_duration_s']:10.1f} | {e['link_mean_duration_s']:8.1f} | "
              f"{e['delta_duration_pct']:+6.1f} | {e['link_share_zigzag_pct']:7.1f} | "
              f"{lk['wardrop_innetwork_spread_pct']:5.2f} / {lk['wardrop_total_spread_pct']:5.2f}")
    print("\nwrote", a.out_dir)


if __name__ == "__main__":
    main()
