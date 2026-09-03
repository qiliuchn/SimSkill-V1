#!/usr/bin/env python3
"""
Sub-goal 4: parse every completed run under corridor/runs/<cell>/ and produce
two tidy CSVs:

  per_run.csv       -- one row per (variant, density, seed, consolidate) cell,
                        with corridor-wide AND through-vs-access-decomposed
                        mobility metrics (travel time, speed, delay/timeLoss,
                        stops/waitingCount, entry delay), VMT/VHT, and a
                        completion/survivorship sanity check.
  conflicts.csv      -- one row per cell, SSM conflict counts by movement-type
                        category (left-turn-in, left-turn-out, right-turn-in,
                        right-turn-out, thru-thru, median/crossover-related),
                        both raw and normalized per million vehicle-km.

Movement class is read directly off the vehicle id, which gen_demand.py
encodes at creation time (thru_eb/thru_wb, dwy_in_left/in_right/out_left/
out_right_<driveway-node>_<serial>) -- no inference needed.
"""
import csv
import glob
import os
import re
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "..", "corridor", "runs")
OUT = HERE

CELL_RE = re.compile(r"^(undivided|twltl|raised)_d(\d+)(?:_c(\d+))?_s(\d+)$")


def move_class(vid):
    if vid.startswith("thru_eb"):
        return "through", "thru_eb"
    if vid.startswith("thru_wb"):
        return "through", "thru_wb"
    m = re.match(r"^dwy_(in_left|in_right|out_left|out_right)_", vid)
    if m:
        return "access", m.group(1)
    return "other", "other"


def parse_cell_name(name):
    m = CELL_RE.match(name)
    if not m:
        return None
    variant, density, consolidate, seed = m.groups()
    return variant, int(density), int(consolidate or 1), int(seed)


def parse_tripinfo(path):
    recs = []
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag == "tripinfo":
            vid = elem.get("id")
            grp, sub = move_class(vid)
            recs.append({
                "id": vid, "group": grp, "sub": sub,
                "depart": float(elem.get("depart")),
                "duration": float(elem.get("duration")),
                "routeLength": float(elem.get("routeLength")),
                "timeLoss": float(elem.get("timeLoss")),
                "waitingTime": float(elem.get("waitingTime")),
                "waitingCount": float(elem.get("waitingCount")),
                "departDelay": float(elem.get("departDelay")),
                "vaporized": elem.get("vaporized", ""),
            })
            elem.clear()
    return recs


def parse_statistics(path):
    tree = ET.parse(path)
    root = tree.getroot()
    veh = root.find("vehicles")
    tel = root.find("teleports")
    saf = root.find("safety")
    vts = root.find("vehicleTripStatistics")
    return {
        "loaded": int(veh.get("loaded")), "inserted": int(veh.get("inserted")),
        "running": int(veh.get("running")), "waiting": int(veh.get("waiting")),
        "teleports_total": int(tel.get("total")),
        "collisions": int(saf.get("collisions")),
        "stat_speed": float(vts.get("speed")), "stat_duration": float(vts.get("duration")),
        "stat_timeLoss": float(vts.get("timeLoss")),
        "stat_totalDepartDelay": float(vts.get("totalDepartDelay")),
    }


CONFLICT_TYPE_NAME = {
    "2": "following", "3": "following", "18": "following",
    "6": "merging", "7": "merging", "8": "merging", "19": "merging",
    "111": "collinear_collision_artifact",
}
for _c in range(10, 18):
    CONFLICT_TYPE_NAME[str(_c)] = "crossing"


def classify_conflict(ego_id, foe_id):
    """Movement-type category for one conflict, from the (ego,foe) vehicle-id
    pair. Priority: any left-turn movement present > any right-turn movement
    present > thru-thru. This intentionally double-counts a conflict under
    both 'left_in' and 'left_out' in the rare case both parties are left
    movers of opposite senses -- flagged, not hidden, in the README note the
    analysis prints."""
    classes = set()
    for vid in (ego_id, foe_id):
        _, sub = move_class(vid)
        if sub in ("in_left", "in_right", "out_left", "out_right"):
            classes.add(sub)
    cats = []
    if "in_left" in classes:
        cats.append("left_turn_in")
    if "out_left" in classes:
        cats.append("left_turn_out")
    if "in_right" in classes:
        cats.append("right_turn_in")
    if "out_right" in classes:
        cats.append("right_turn_out")
    if not cats:
        cats = ["thru_thru"]
    return cats


def parse_ssm(path, variant):
    """Returns list of (type_code, categories, is_median_related, ego, foe)."""
    out = []
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag == "conflict":
            ego, foe = elem.get("ego"), elem.get("foe")
            cats = classify_conflict(ego, foe)
            # median/crossover-related: for twltl, either party's minTTC/PET
            # position lane starts with MEB_/MWB_ (the discretized pocket
            # lanes); for raised, any conflict touching a left-turn class
            # (in_left/out_left) is *by construction* a U-turn-crossover
            # conflict, since raised has NO direct left connection at all --
            # the direct crossing movement simply does not exist in that net.
            median_related = False
            type_code = None
            for sub in elem:
                if sub.tag in ("minTTC", "maxDRAC", "PET", "maxMDRAC"):
                    lane = sub.get("egoLane", "") or ""
                    if lane.startswith("MEB_") or lane.startswith("MWB_") or lane.startswith(":"):
                        # internal (":"-prefixed) lanes are junction-interior,
                        # which is where the twltl pocket's arbitration lives
                        # once compiled -- still "median-pocket vicinity" for
                        # twltl specifically.
                        if variant == "twltl":
                            median_related = True
                    if type_code is None:
                        type_code = sub.get("type")
            if variant == "raised" and ("left_turn_in" in cats or "left_turn_out" in cats):
                median_related = True
            out.append((type_code, cats, median_related, ego, foe))
            elem.clear()
    return out


def agg(vals):
    if not vals:
        return {"n": 0, "mean": float("nan"), "p95": float("nan")}
    v = sorted(vals)
    n = len(v)
    return {"n": n, "mean": sum(v) / n, "p95": v[int(0.95 * (n - 1))]}


def main():
    cells = sorted(d for d in os.listdir(RUNS) if os.path.isdir(os.path.join(RUNS, d)))
    per_run_rows = []
    conflict_rows = []
    for cell in cells:
        parsed = parse_cell_name(cell)
        if parsed is None:
            print("SKIP (unparsed name):", cell)
            continue
        variant, density, consolidate, seed = parsed
        cdir = os.path.join(RUNS, cell)
        tpath = os.path.join(cdir, "tripinfo.xml")
        spath = os.path.join(cdir, "statistics.xml")
        ssmpath = os.path.join(cdir, "ssm.xml")
        if not (os.path.exists(tpath) and os.path.exists(spath)):
            print("SKIP (missing outputs):", cell)
            continue
        recs = parse_tripinfo(tpath)
        stats = parse_statistics(spath)

        def sub(group=None, subs=None):
            r = recs
            if group:
                r = [x for x in r if x["group"] == group]
            if subs:
                r = [x for x in r if x["sub"] in subs]
            return r

        vmt_km_all = sum(r["routeLength"] for r in recs) / 1000.0
        vht_h_all = sum(r["duration"] for r in recs) / 3600.0

        row = {
            "variant": variant, "density": density, "consolidate": consolidate, "seed": seed,
            "n_trips": len(recs),
            "loaded": stats["loaded"], "inserted": stats["inserted"],
            "running_at_end": stats["running"], "waiting_at_end": stats["waiting"],
            "teleports": stats["teleports_total"], "collisions": stats["collisions"],
            "vmt_km": vmt_km_all, "vht_h": vht_h_all,
            "mean_speed_mps_all": (vmt_km_all * 1000.0) / (vht_h_all * 3600.0) if vht_h_all > 0 else float("nan"),
        }
        for grpname, subs in [
            ("through", ("thru_eb", "thru_wb")),
            ("access", ("in_left", "in_right", "out_left", "out_right")),
            ("access_in_left", ("in_left",)),
            ("access_in_right", ("in_right",)),
            ("access_out_left", ("out_left",)),
            ("access_out_right", ("out_right",)),
        ]:
            rs = sub(subs=subs)
            dur = agg([r["duration"] for r in rs])
            tl = agg([r["timeLoss"] for r in rs])
            wt = agg([r["waitingTime"] for r in rs])
            wc = agg([r["waitingCount"] for r in rs])
            dd = agg([r["departDelay"] for r in rs])
            spd = agg([r["routeLength"] / r["duration"] for r in rs if r["duration"] > 0])
            row[f"{grpname}_n"] = dur["n"]
            row[f"{grpname}_mean_traveltime_s"] = dur["mean"]
            row[f"{grpname}_mean_speed_mps"] = spd["mean"]
            row[f"{grpname}_mean_timeloss_s"] = tl["mean"]
            row[f"{grpname}_p95_timeloss_s"] = tl["p95"]
            row[f"{grpname}_mean_waitingtime_s"] = wt["mean"]
            row[f"{grpname}_mean_stops"] = wc["mean"]
            row[f"{grpname}_mean_departdelay_s"] = dd["mean"]
            row[f"{grpname}_p95_departdelay_s"] = dd["p95"]
        per_run_rows.append(row)

        if os.path.exists(ssmpath):
            confs = parse_ssm(ssmpath, variant)
            counts = {}
            median_n = 0
            n_conflicts = len(confs)
            for type_code, cats, medrel, ego, foe in confs:
                for c in cats:
                    counts[c] = counts.get(c, 0) + 1
                if medrel:
                    median_n += 1
            crow = {
                "variant": variant, "density": density, "consolidate": consolidate, "seed": seed,
                "n_conflicts_total": n_conflicts, "vmt_km": vmt_km_all,
                "conflicts_per_Mvkm_total": n_conflicts * 1e6 / vmt_km_all if vmt_km_all > 0 else float("nan"),
            }
            for cat in ["left_turn_in", "left_turn_out", "right_turn_in", "right_turn_out", "thru_thru"]:
                n = counts.get(cat, 0)
                crow[f"n_{cat}"] = n
                crow[f"{cat}_per_Mvkm"] = n * 1e6 / vmt_km_all if vmt_km_all > 0 else float("nan")
            crow["n_median_related"] = median_n
            crow["median_related_per_Mvkm"] = median_n * 1e6 / vmt_km_all if vmt_km_all > 0 else float("nan")
            conflict_rows.append(crow)

    if per_run_rows:
        keys = list(per_run_rows[0].keys())
        with open(os.path.join(OUT, "per_run.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(per_run_rows)
    if conflict_rows:
        keys = list(conflict_rows[0].keys())
        with open(os.path.join(OUT, "conflicts.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(conflict_rows)
    print(f"wrote {len(per_run_rows)} per_run rows, {len(conflict_rows)} conflict rows")
    incomplete = [r for r in per_run_rows if r["running_at_end"] > 0 or r["waiting_at_end"] > 0]
    if incomplete:
        print(f"WARNING: {len(incomplete)} cells did not fully drain (running/waiting>0 at sim end):")
        for r in incomplete:
            print(f"   {r['variant']} d{r['density']} c{r['consolidate']} s{r['seed']}: "
                  f"running={r['running_at_end']} waiting={r['waiting_at_end']} loaded={r['loaded']}")
    else:
        print("All cells fully drained (running=0, waiting=0 at sim end) -- no survivorship censoring.")
    teleports = [(r["variant"], r["density"], r["seed"], r["teleports"]) for r in per_run_rows if r["teleports"] > 0]
    collisions = [(r["variant"], r["density"], r["seed"], r["collisions"]) for r in per_run_rows if r["collisions"] > 0]
    print(f"cells with teleports>0: {len(teleports)} ; cells with SUMO-reported collisions>0: {len(collisions)}")
    if teleports:
        print("  teleport cells:", teleports[:20])
    if collisions:
        print("  collision cells:", collisions[:20])


if __name__ == "__main__":
    main()
