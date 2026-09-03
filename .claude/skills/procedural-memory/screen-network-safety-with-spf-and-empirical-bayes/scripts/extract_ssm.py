"""
Parse every replication's SSM / tripinfo / summary / collision output into one
tidy per-run CSV.

Key conventions, inherited from `analyze-intersection-safety-with-ssm` and
`compare-left-turn-signal-treatments`:

  * SSM encounter-type codes:  2,3,18 -> rear-end/following; 6,7,8,19 -> merging/
    lane-change; 10..17 -> crossing/angle; 111 -> nominal "collision" (which is
    NOT a real simulated collision -- cross-checked here against summary.xml's
    cumulative `collisions` field and --collision-output, per the correction
    recorded in [[surrogate-safety-measures]]).
  * Every vehicle carries its own SSM device, so ONE physical near-miss is logged
    twice (once from each participant).  We de-duplicate on the unordered
    {ego,foe} pair with overlapping [begin,end] windows and report both the raw
    and de-duplicated counts.
  * summary.xml's `teleports` is CUMULATIVE -- take the last step's value, never
    a sum (the bug documented in `analyze-simulation-outputs`).

An analysis window [WARMUP, END) is applied so the loading transient is excluded
from both the conflict counts and the entering-vehicle denominator.
"""
import argparse
import csv
import json
import os
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed

REAR = {2, 3, 18}
MERGE = {6, 7, 8, 19}
CROSS = set(range(10, 18))
COLL = {111}

TTC_SEVERE = 1.5
PET_SEVERE = 1.0
DRAC_SEVERE = 3.5


def cat(code):
    if code in REAR:
        return "rear_end"
    if code in MERGE:
        return "merge_lanechange"
    if code in CROSS:
        return "crossing"
    if code in COLL:
        return "type111"
    return "other"


def fval(el, attr="value"):
    if el is None:
        return None
    v = el.get(attr)
    if v is None or v == "NA":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_ssm(path, t0, t1):
    """Return de-duplicated conflict records inside [t0, t1)."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return [], 0
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return [], 0

    raw = []
    for c in root.findall("conflict"):
        try:
            b = float(c.get("begin"))
            e = float(c.get("end"))
        except (TypeError, ValueError):
            continue
        if not (t0 <= b < t1):
            continue
        ttc_el, drac_el, pet_el = c.find("minTTC"), c.find("maxDRAC"), c.find("PET")
        codes = []
        for el in (ttc_el, drac_el, pet_el):
            if el is not None and el.get("type") not in (None, "NA"):
                try:
                    codes.append(int(el.get("type")))
                except ValueError:
                    pass
        code = codes[0] if codes else -1
        raw.append(dict(begin=b, end=e, ego=c.get("ego"), foe=c.get("foe"),
                        ttc=fval(ttc_el), drac=fval(drac_el), pet=fval(pet_el),
                        code=code, cat=cat(code)))

    # de-duplicate the mirrored (ego,foe)/(foe,ego) logging of one physical event
    raw.sort(key=lambda r: r["begin"])
    kept, seen = [], {}
    for r in raw:
        key = frozenset((r["ego"], r["foe"]))
        prev = seen.get(key)
        if prev is not None and r["begin"] <= prev["end"] + 1.0:
            # same physical encounter seen from the other participant: keep the
            # worse (smaller TTC / smaller PET / larger DRAC) reading
            for k, better in (("ttc", min), ("pet", min), ("drac", max)):
                a, b = prev[k], r[k]
                prev[k] = a if b is None else (b if a is None else better(a, b))
            prev["end"] = max(prev["end"], r["end"])
            continue
        seen[key] = r
        kept.append(r)
    return kept, len(raw)


def parse_tripinfo(path, t0, t1):
    if not os.path.exists(path):
        return dict(entering=0, arrived=0, mean_duration=None, mean_timeloss=None,
                    mean_waiting=None)
    n_dep = n_arr = 0
    dur = tl = wt = 0.0
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "tripinfo":
            continue
        try:
            d = float(el.get("depart"))
        except (TypeError, ValueError):
            el.clear(); continue
        if t0 <= d < t1:
            n_dep += 1
            n_arr += 1
            dur += float(el.get("duration"))
            tl += float(el.get("timeLoss"))
            wt += float(el.get("waitingTime"))
        el.clear()
    if n_dep == 0:
        return dict(entering=0, arrived=0, mean_duration=None, mean_timeloss=None, mean_waiting=None)
    return dict(entering=n_dep, arrived=n_arr, mean_duration=dur / n_dep,
                mean_timeloss=tl / n_dep, mean_waiting=wt / n_dep)


def parse_summary(path):
    """teleports/collisions are CUMULATIVE -> take the LAST step, never a sum."""
    last = None
    inserted = loaded = None
    if not os.path.exists(path):
        return dict(teleports=None, collisions=None, inserted=None, loaded=None)
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            last = (el.get("teleports"), el.get("collisions"),
                    el.get("inserted"), el.get("loaded"))
        el.clear()
    if last is None:
        return dict(teleports=None, collisions=None, inserted=None, loaded=None)
    t, c, ins, ld = last
    return dict(teleports=int(t) if t else 0, collisions=int(c) if c else 0,
                inserted=int(ins) if ins else 0, loaded=int(ld) if ld else 0)


def count_collision_output(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return 0
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return 0
    return len(root.findall(".//collision"))


def one(job):
    site, seed, variant, d, t0, t1 = job
    conf, n_raw = parse_ssm(os.path.join(d, "ssm.xml"), t0, t1)
    trip = parse_tripinfo(os.path.join(d, "tripinfo.xml"), t0, t1)
    summ = parse_summary(os.path.join(d, "summary.xml"))
    ncoll = count_collision_output(os.path.join(d, "collisions.xml"))

    ttcs = [c["ttc"] for c in conf if c["ttc"] is not None]
    pets = [c["pet"] for c in conf if c["pet"] is not None]
    dracs = [c["drac"] for c in conf if c["drac"] is not None]

    row = dict(site=site, seed=seed, variant=variant,
               conflicts_raw=n_raw, conflicts=len(conf),
               conf_rear_end=sum(1 for c in conf if c["cat"] == "rear_end"),
               conf_merge=sum(1 for c in conf if c["cat"] == "merge_lanechange"),
               conf_crossing=sum(1 for c in conf if c["cat"] == "crossing"),
               conf_type111=sum(1 for c in conf if c["cat"] == "type111"),
               conf_other=sum(1 for c in conf if c["cat"] == "other"),
               n_ttc=len(ttcs), n_pet=len(pets), n_drac=len(dracs),
               severe_ttc=sum(1 for v in ttcs if v < TTC_SEVERE),
               severe_pet=sum(1 for v in pets if v < PET_SEVERE),
               severe_drac=sum(1 for v in dracs if v > DRAC_SEVERE),
               severe_ttc_crossing=sum(1 for c in conf
                                       if c["cat"] == "crossing" and c["ttc"] is not None
                                       and c["ttc"] < TTC_SEVERE),
               min_ttc=min(ttcs) if ttcs else None,
               min_pet=min(pets) if pets else None,
               max_drac=max(dracs) if dracs else None,
               entering=trip["entering"],
               mean_duration=trip["mean_duration"], mean_timeloss=trip["mean_timeloss"],
               mean_waiting=trip["mean_waiting"],
               teleports=summ["teleports"], sumo_collisions=summ["collisions"],
               collision_output_n=ncoll,
               inserted=summ["inserted"], loaded=summ["loaded"])
    ent = row["entering"] or 0
    mev = ent / 1e6
    for src, dst in (("conflicts", "conf_rate_mev"), ("severe_ttc", "severe_ttc_rate_mev"),
                     ("conf_crossing", "crossing_rate_mev"), ("conf_rear_end", "rear_end_rate_mev"),
                     ("severe_ttc_crossing", "severe_crossing_rate_mev")):
        row[dst] = (row[src] / mev) if mev > 0 else None
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", required=True)
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--variant", default="base")
    ap.add_argument("--warmup", type=float, default=600.0)
    ap.add_argument("--end", type=float, default=4200.0)
    ap.add_argument("--workers", type=int, default=9)
    a = ap.parse_args()

    jobs = []
    for site in sorted(os.listdir(a.runs_root)):
        sd = os.path.join(a.runs_root, site)
        if not os.path.isdir(sd):
            continue
        for sub in sorted(os.listdir(sd)):
            if not sub.startswith("seed"):
                continue
            jobs.append((site, int(sub[4:]), a.variant, os.path.join(sd, sub),
                         a.warmup, a.end))

    rows = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for f in as_completed([ex.submit(one, j) for j in jobs]):
            rows.append(f.result())
    rows.sort(key=lambda r: (r["site"], r["seed"]))

    os.makedirs(os.path.dirname(os.path.abspath(a.out_csv)), exist_ok=True)
    with open(a.out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote %d rows -> %s" % (len(rows), a.out_csv))
    tot_t111 = sum(r["conf_type111"] for r in rows)
    tot_coll = sum(r["sumo_collisions"] or 0 for r in rows)
    tot_co = sum(r["collision_output_n"] for r in rows)
    tot_tp = sum(r["teleports"] or 0 for r in rows)
    print("cross-check: SSM type-111 encounters=%d | summary collisions=%d | "
          "--collision-output records=%d | teleports=%d"
          % (tot_t111, tot_coll, tot_co, tot_tp))


if __name__ == "__main__":
    main()
