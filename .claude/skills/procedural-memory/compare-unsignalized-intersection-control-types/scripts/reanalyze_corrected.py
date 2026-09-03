#!/usr/bin/env python3
"""
CORRECTED re-analysis of attempt-1's 32 raw runs (NO re-simulation).

Fixes the two defects the critic flagged in attempt-1:

  DEFECT A (SSM safety narrative): attempt-1 counted every SSM type=111
  ("collision") flag as a severe conflict. Independent parsing shows EVERY
  type=111 flag in EVERY run is degenerate (minTTC value = 0.00 or NA; PET
  value = 0.00, NA, or NEGATIVE) and is produced by left-turn movements sitting
  on the same collinear internal-lane crossing point. summary.xml reports
  collisions=0 for every run. So type=111 is a pure geometry artifact and is
  EXCLUDED from the safety comparison here. Genuine safety signal is taken from
  crossing-type encounters (SSM encounter types 10-17) that carry a finite TTC,
  classified by the actual movement pair (minor NS vs major EW crossing, or
  same-axis left-vs-through permissive-left).

  DEFECT B (incomplete metric): attempt-1 used incomplete = inserted - arrived,
  missing vehicles blocked from ever being inserted at jammed source edges.
  Corrected: incomplete_true = loaded - arrived, and never_inserted =
  loaded - inserted reported separately.

Reads attempt-1 raw run outputs unchanged; writes new deliverables into
attempt-2/outputs/analysis/.
"""
import csv, json, os
import xml.etree.ElementTree as ET
from collections import Counter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

A1 = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-29_09-44-55/attempts/attempt-1"
A2 = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-29_09-44-55/attempts/attempt-2"
RUNS = os.path.join(A1, "outputs", "runs")
ANA = os.path.join(A2, "outputs", "analysis")
os.makedirs(ANA, exist_ok=True)

MODES = ["A_right_before_left", "B_priority", "C_allway_stop", "D_traffic_light"]
MODE_LABEL = {
    "A_right_before_left": "right_before_left",
    "B_priority": "priority (TWSC, major=E-W)",
    "C_allway_stop": "allway_stop (AWSC)",
    "D_traffic_light": "traffic_light (signal)",
}
LEVELS = [300, 600, 900, 1200, 1500, 1800, 2100, 2400]
CROSS_TYPES = set(str(x) for x in range(10, 18))   # SSM crossing encounter types
SEVERE_TTC = 1.5   # s : threshold for a "genuine severe" crossing near-miss


def mv(vid):
    """f_N_s.12 -> ('N','s')  (origin, turn)"""
    _, o, t = vid.split(".")[0].split("_")
    return o, t


def axis(o):
    return "NS" if o in "NS" else "EW"


def is_leftleft_artifact(e, f):
    (eo, et), (fo, ft) = mv(e), mv(f)
    if et == "l" and ft == "l":
        if axis(eo) == axis(fo) == "NS" and eo != fo:
            return "NS-left"
        if axis(eo) == axis(fo) == "EW" and eo != fo:
            return "EW-left"
    return None


def crossing_category(e, f):
    (eo, et), (fo, ft) = mv(e), mv(f)
    if axis(eo) != axis(fo):
        return "minor_major"        # perpendicular NS x EW crossing (broadside risk)
    # same corridor
    if "l" in (et, ft) and "s" in (et, ft):
        return "same_axis_permissive_left"
    return "same_axis_other"


def parse_trip(path):
    root = ET.parse(path).getroot()
    waits, losses, durs, speeds = [], [], [], []
    arrived = 0
    for ti in root.findall("tripinfo"):
        arr = ti.get("arrival")
        if arr is not None and float(arr) >= 0:
            arrived += 1
        d = float(ti.get("duration")); rl = float(ti.get("routeLength"))
        waits.append(float(ti.get("waitingTime")))
        losses.append(float(ti.get("timeLoss")))
        durs.append(d)
        if d > 0:
            speeds.append(rl / d)
    mean = lambda a: round(sum(a) / len(a), 2) if a else None
    return {"n_tripinfo": len(durs), "arrived": arrived,
            "mean_wait_s": mean(waits), "mean_timeloss_s": mean(losses),
            "mean_speed_ms": mean(speeds)}


def parse_summary(path):
    root = ET.parse(path).getroot()
    teleports = loaded = inserted = 0
    for step in root.findall("step"):
        teleports = int(step.get("teleports", "0"))
        loaded = int(step.get("loaded", loaded))
        inserted = int(step.get("inserted", inserted))
    # collisions attribute (real SUMO collisions) - read last value
    collisions = 0
    for step in root.findall("step"):
        collisions = int(step.get("collisions", "0"))
    return {"teleports": teleports, "loaded": loaded, "inserted": inserted,
            "sumo_collisions": collisions}


def parse_ssm(path):
    root = ET.parse(path).getroot()
    art = Counter()            # type-111 artifact flags by pair class
    art_nonzero_positive = 0   # sanity: any physically-meaningful 111 value?
    total_conf = 0
    crossing = 0
    severe = Counter()         # genuine severe crossing near-miss by category
    severe_total = 0
    finite_ttcs = []
    finite_pets = []
    for c in root.findall("conflict"):
        total_conf += 1
        ttc = c.find("minTTC"); pet = c.find("PET")
        tt = ttc.get("type") if ttc is not None else None
        pt = pet.get("type") if pet is not None else None
        e, f = c.get("ego"), c.get("foe")

        is111 = (tt == "111") or (pt == "111")
        if is111:
            cls = is_leftleft_artifact(e, f) or "other_leftturn"
            art[cls] += 1
            for el in (ttc, pet):
                if el is not None and el.get("type") == "111":
                    v = el.get("value")
                    try:
                        if v not in ("NA", None) and float(v) > 0.001:
                            art_nonzero_positive += 1
                    except ValueError:
                        pass
            continue   # 111 excluded from all genuine metrics

        # genuine (non-111) metrics.
        # "crossing_conflicts" is a broad descriptive tally (minTTC OR PET is a
        # crossing-type encounter). Severity, however, is keyed strictly off the
        # minTTC encounter type, because it is thresholded on the minTTC value.
        if (tt in CROSS_TYPES) or (pt in CROSS_TYPES):
            crossing += 1
        ttc_is_cross = tt in CROSS_TYPES
        if ttc is not None and tt not in (None, "NA", "111"):
            try:
                v = float(ttc.get("value"))
                if v > 0:
                    finite_ttcs.append(v)
                    if v < SEVERE_TTC and ttc_is_cross:
                        severe_total += 1
                        severe[crossing_category(e, f)] += 1
            except ValueError:
                pass
        if pet is not None and pt not in (None, "NA", "111"):
            try:
                v = float(pet.get("value"))
                if v >= 0:
                    finite_pets.append(v)
            except ValueError:
                pass
    return {
        "total_conflicts": total_conf,
        "artifact111_total": sum(art.values()),
        "artifact111_NSleft": art["NS-left"],
        "artifact111_EWleft": art["EW-left"],
        "artifact111_other_leftturn": art["other_leftturn"],
        "artifact111_nonzero_positive": art_nonzero_positive,
        "crossing_conflicts": crossing,
        "severe_nearmiss_total": severe_total,
        "severe_minor_major": severe["minor_major"],
        "severe_same_axis_permissive_left": severe["same_axis_permissive_left"],
        "severe_same_axis_other": severe["same_axis_other"],
        "worst_finite_TTC": round(min(finite_ttcs), 2) if finite_ttcs else None,
        "worst_finite_PET": round(min(finite_pets), 2) if finite_pets else None,
    }


def main():
    data = {}
    rows = []
    for mode in MODES:
        for L in LEVELS:
            rd = os.path.join(RUNS, f"{mode}__{L}")
            t = parse_trip(os.path.join(rd, "tripinfo.xml"))
            s = parse_summary(os.path.join(rd, "summary.xml"))
            ssm = parse_ssm(os.path.join(rd, "ssm.xml"))
            m = {**t, **s, **ssm}
            m["never_inserted"] = m["loaded"] - m["inserted"]
            m["incomplete_true"] = m["loaded"] - m["arrived"]       # CORRECTED
            m["incomplete_inserted_minus_arrived"] = m["inserted"] - m["arrived"]  # old defn, kept for transparency
            data[(mode, L)] = m
            rows.append({
                "mode": mode, "demand": L,
                "mean_wait_s": m["mean_wait_s"], "mean_timeloss_s": m["mean_timeloss_s"],
                "mean_speed_ms": m["mean_speed_ms"],
                "loaded": m["loaded"], "inserted": m["inserted"], "arrived": m["arrived"],
                "never_inserted": m["never_inserted"],
                "incomplete_true_loaded_minus_arrived": m["incomplete_true"],
                "incomplete_OLD_inserted_minus_arrived": m["incomplete_inserted_minus_arrived"],
                "teleports": m["teleports"], "sumo_collisions": m["sumo_collisions"],
                "total_conflicts": m["total_conflicts"],
                "crossing_conflicts": m["crossing_conflicts"],
                "artifact111_total_EXCLUDED": m["artifact111_total"],
                "artifact111_NSleft": m["artifact111_NSleft"],
                "artifact111_EWleft": m["artifact111_EWleft"],
                "artifact111_otherLeft": m["artifact111_other_leftturn"],
                "genuine_severe_nearmiss": m["severe_nearmiss_total"],
                "severe_minor_major_crossing": m["severe_minor_major"],
                "severe_permissive_left": m["severe_same_axis_permissive_left"],
                "severe_same_axis_other": m["severe_same_axis_other"],
                "worst_finite_TTC": m["worst_finite_TTC"],
                "worst_finite_PET": m["worst_finite_PET"],
            })

    with open(os.path.join(ANA, "comparison_corrected.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    with open(os.path.join(ANA, "metrics_corrected.json"), "w") as fh:
        json.dump({f"{k[0]}__{k[1]}": v for k, v in data.items()}, fh, indent=2)

    # sanity: no type-111 should ever carry a physically-meaningful positive value
    tot_art = sum(data[(m, L)]["artifact111_total"] for m in MODES for L in LEVELS)
    tot_pos = sum(data[(m, L)]["artifact111_nonzero_positive"] for m in MODES for L in LEVELS)
    tot_realcoll = sum(data[(m, L)]["sumo_collisions"] for m in MODES for L in LEVELS)
    print(f"ARTIFACT CHECK: {tot_art} type-111 flags total; "
          f"{tot_pos} carry a positive finite value; "
          f"real SUMO collisions across all 32 runs = {tot_realcoll}")

    # ---- incomplete / throughput correction table ----
    print("\nCORRECTED THROUGHPUT / FAILED-DEMAND (loaded/inserted/arrived):")
    print(f"{'mode':22s}{'dem':>5s}{'load':>6s}{'ins':>6s}{'arr':>6s}"
          f"{'nevIns':>7s}{'incTrue':>8s}{'incOLD':>7s}{'tele':>6s}")
    for mode in MODES:
        for L in LEVELS:
            m = data[(mode, L)]
            print(f"{mode:22s}{L:5d}{m['loaded']:6d}{m['inserted']:6d}{m['arrived']:6d}"
                  f"{m['never_inserted']:7d}{m['incomplete_true']:8d}"
                  f"{m['incomplete_inserted_minus_arrived']:7d}{m['teleports']:6d}")

    # ---- genuine safety table ----
    print("\nGENUINE SAFETY (type-111 artifacts EXCLUDED); severe = crossing near-miss TTC<1.5s:")
    print(f"{'mode':22s}{'dem':>5s}{'cross':>7s}{'sevTot':>7s}{'minMaj':>7s}"
          f"{'permL':>7s}{'saOth':>7s}{'wTTC':>7s}{'wPET':>7s}")
    for mode in MODES:
        for L in LEVELS:
            m = data[(mode, L)]
            print(f"{mode:22s}{L:5d}{m['crossing_conflicts']:7d}{m['severe_nearmiss_total']:7d}"
                  f"{m['severe_minor_major']:7d}{m['severe_same_axis_permissive_left']:7d}"
                  f"{m['severe_same_axis_other']:7d}"
                  f"{(m['worst_finite_TTC'] or -1):7.2f}{(m['worst_finite_PET'] or -1):7.2f}")

    # ---- plot: genuine minor-major crossing severe near-misses vs demand ----
    fig, ax = plt.subplots(figsize=(8, 5.5))
    colors = {"A_right_before_left": "#d62728", "B_priority": "#1f77b4",
              "C_allway_stop": "#2ca02c", "D_traffic_light": "#000000"}
    markers = {"A_right_before_left": "o", "B_priority": "s",
               "C_allway_stop": "^", "D_traffic_light": "D"}
    for mode in MODES:
        ys = [data[(mode, L)]["severe_minor_major"] for L in LEVELS]
        ax.plot(LEVELS, ys, marker=markers[mode], color=colors[mode],
                linewidth=2.2 if mode == "D_traffic_light" else 1.6,
                linestyle="-" if mode == "D_traffic_light" else "--",
                label=MODE_LABEL[mode])
    ax.set_xlabel("Total demand (veh/h)")
    ax.set_ylabel("Genuine severe minor-major crossing near-misses\n(perpendicular NS x EW, crossing TTC < 1.5 s)")
    ax.set_title("Genuine dangerous crossing near-misses vs demand by control mode\n(type-111 geometry artifacts excluded)")
    ax.set_xticks(LEVELS); ax.grid(True, alpha=0.3); ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(ANA, "genuine_minor_major_conflicts.png"), dpi=130)
    print(f"\nWrote comparison_corrected.csv, metrics_corrected.json, "
          f"genuine_minor_major_conflicts.png to {ANA}")


if __name__ == "__main__":
    main()
