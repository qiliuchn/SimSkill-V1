#!/usr/bin/env python3
"""Goal 5: study-area error (GEH on link volumes, delay RMSE, VHT-proxy bias)
vs buffer distance, one curve per parent resolution per demand level, with
the replication noise floor drawn on it. Also emits the CSV backing the
figure and the buffer x parent x level table required by goal 3."""
import csv
import math
import os
import statistics
import sys

sys.path.append(os.path.dirname(__file__))
from common import WD, STUDY_EDGES, read_edgedata, geh, mean_ci95

SEEDS_CHILD = [42, 43, 44]
SEEDS_PARENT = [42, 43, 44, 45, 46]
LEVELS = ["low", "high"]
PARENTS = ["micro", "meso"]
BUFFERS = [0, 1, 2, 3]


def reference_volumes(level):
    """Mean study-edge volume across the 5-seed full micro reference."""
    out = {}
    for e in STUDY_EDGES:
        vals = []
        for s in SEEDS_PARENT:
            tag = "micro_%s_seed%d" % (level, s)
            ed = read_edgedata(os.path.join(WD, "micro", "full", "%s_edgedata.xml" % tag), {e})
            vals.append(ed.get(e, {}).get("entered", 0.0) or 0.0)
        out[e] = sum(vals) / len(vals)
    return out


def reference_delay(level):
    out = {}
    for e in STUDY_EDGES:
        vals = []
        for s in SEEDS_PARENT:
            tag = "micro_%s_seed%d" % (level, s)
            ed = read_edgedata(os.path.join(WD, "micro", "full", "%s_edgedata.xml" % tag), {e})
            d = ed.get(e, {})
            if d.get("left"):
                vals.append(d["timeLoss"] / d["left"])
        out[e] = sum(vals) / len(vals) if vals else 0.0
    return out


def reference_vht_proxy(level):
    """Sum of sampledSeconds/3600 over the study edges, mean across seeds --
    a network-size-independent VHT proxy comparable between full ref and any
    cut child (since it's restricted to the always-present study-edge set)."""
    vals = []
    for s in SEEDS_PARENT:
        tag = "micro_%s_seed%d" % (level, s)
        ed = read_edgedata(os.path.join(WD, "micro", "full", "%s_edgedata.xml" % tag), set(STUDY_EDGES))
        vals.append(sum((ed.get(e, {}).get("sampledSeconds") or 0.0) for e in STUDY_EDGES) / 3600.0)
    return sum(vals) / len(vals), vals


def child_volumes(buf, parent, level):
    out = {e: [] for e in STUDY_EDGES}
    for s in SEEDS_CHILD:
        name = "buf%d_%s_%s" % (buf, parent, level)
        tag = "%s_seed%d" % (name, s)
        ed = read_edgedata(os.path.join(WD, "cuts", name, "runs", "%s_edgedata.xml" % tag), set(STUDY_EDGES))
        for e in STUDY_EDGES:
            out[e].append(ed.get(e, {}).get("entered", 0.0) or 0.0)
    return {e: sum(v) / len(v) for e, v in out.items()}


def child_delay(buf, parent, level):
    out = {e: [] for e in STUDY_EDGES}
    for s in SEEDS_CHILD:
        name = "buf%d_%s_%s" % (buf, parent, level)
        tag = "%s_seed%d" % (name, s)
        ed = read_edgedata(os.path.join(WD, "cuts", name, "runs", "%s_edgedata.xml" % tag), set(STUDY_EDGES))
        for e in STUDY_EDGES:
            d = ed.get(e, {})
            if d.get("left"):
                out[e].append(d["timeLoss"] / d["left"])
    return {e: (sum(v) / len(v) if v else 0.0) for e, v in out.items()}


def child_vht_proxy(buf, parent, level):
    vals = []
    for s in SEEDS_CHILD:
        name = "buf%d_%s_%s" % (buf, parent, level)
        tag = "%s_seed%d" % (name, s)
        ed = read_edgedata(os.path.join(WD, "cuts", name, "runs", "%s_edgedata.xml" % tag), set(STUDY_EDGES))
        vals.append(sum((ed.get(e, {}).get("sampledSeconds") or 0.0) for e in STUDY_EDGES) / 3600.0)
    return sum(vals) / len(vals), vals


def noise_floor(level):
    """Parent-vs-parent GEH / VHT-proxy-bias floor (5 seeds vs their own mean)."""
    ref = reference_volumes(level)
    gehs = []
    for e in STUDY_EDGES:
        for s in SEEDS_PARENT:
            tag = "micro_%s_seed%d" % (level, s)
            ed = read_edgedata(os.path.join(WD, "micro", "full", "%s_edgedata.xml" % tag), {e})
            v = ed.get(e, {}).get("entered", 0.0) or 0.0
            gehs.append(geh(v, ref[e]))
    mean_geh = sum(gehs) / len(gehs)
    vhtp_mean, vhtp_vals = reference_vht_proxy(level)
    vht_bias = [100.0 * (v - vhtp_mean) / vhtp_mean for v in vhtp_vals]
    return mean_geh, statistics.pstdev(vht_bias)


def main():
    rows = []
    nf = {}
    for level in LEVELS:
        nf[level] = noise_floor(level)
        print("noise floor [%s]: mean GEH=%.3f | VHT-proxy-bias sd=%.2f%%" % (level, nf[level][0], nf[level][1]))

    for level in LEVELS:
        ref_vol = reference_volumes(level)
        ref_delay = reference_delay(level)
        ref_vht, _ = reference_vht_proxy(level)
        for parent in PARENTS:
            for buf in BUFFERS:
                cv = child_volumes(buf, parent, level)
                cd = child_delay(buf, parent, level)
                cvht, _ = child_vht_proxy(buf, parent, level)
                gehs = [geh(cv[e], ref_vol[e]) for e in STUDY_EDGES]
                mean_geh = sum(gehs) / len(gehs)
                delay_rmse = math.sqrt(sum((cd[e] - ref_delay[e]) ** 2 for e in STUDY_EDGES) / len(STUDY_EDGES))
                vht_bias_pct = 100.0 * (cvht - ref_vht) / ref_vht
                rows.append({
                    "level": level, "parent": parent, "buffer": buf,
                    "mean_geh": mean_geh, "max_geh": max(gehs),
                    "delay_rmse_s": delay_rmse, "vht_bias_pct": vht_bias_pct,
                    "noise_floor_geh": nf[level][0],
                })
                print("level=%-4s parent=%-5s buf=%d  mean_GEH=%.3f (floor %.3f)  delay_RMSE=%.2fs  VHT_proxy_bias=%+.2f%%"
                      % (level, parent, buf, mean_geh, nf[level][0], delay_rmse, vht_bias_pct))

    csv_path = os.path.join(WD, "analysis", "buffer_curve.csv")
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\nwrote", csv_path)
    return rows, nf


if __name__ == "__main__":
    main()
