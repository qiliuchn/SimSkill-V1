#!/usr/bin/env python3
"""Copy the representative networks / configs / raw run artifacts out of scratch
into outputs/, so every claim in FINDINGS.md can be re-verified from retained files.

Raw FCD is NOT retained (hundreds of GB across the sweeps); everything downstream
reads the per-run measure.json / result.json, psummary.xml, tripinfo.xml, accum.csv
and the sumo log, all of which ARE retained for the representative runs.
"""
import argparse
import os
import shutil

CORRIDOR_KEEP = ["corr.net.xml", "corr.nod.xml", "corr.edg.xml", "ped.rou.xml",
                 "measure.json", "psummary.xml", "accum.csv", "sumo.log", "tripinfo.xml"]
EGRESS_KEEP = ["egress.net.xml", "eg.nod.xml", "eg.edg.xml", "eg.rou.xml",
               "result.json", "losmap.csv", "traj.json", "accum.csv",
               "psummary.xml", "summary.xml", "sumo.log"]


def copy_run(src, dst, keep, max_log_mb=3):
    if not os.path.isdir(src):
        return False
    os.makedirs(dst, exist_ok=True)
    for f in keep:
        p = os.path.join(src, f)
        if not os.path.exists(p):
            continue
        if f == "sumo.log" and os.path.getsize(p) > max_log_mb * 1e6:
            # keep head+tail of an enormous warning log rather than dropping it
            with open(p, errors="ignore") as fh:
                lines = fh.readlines()
            with open(os.path.join(dst, f), "w") as o:
                o.writelines(lines[:2000])
                o.write("\n... [%d lines elided] ...\n\n" % max(0, len(lines) - 4000))
                o.writelines(lines[-2000:])
        else:
            shutil.copy2(p, os.path.join(dst, f))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    S, O = a.scratch, a.out
    n = 0
    picks = [
        # (experiment dir, run name, retained name, kind)
        ("h1_uniform", "h1u_r0.1_s1", "corridor_freeflow_r0.1", "c"),
        ("h1_uniform", "h1u_r3_s1", "corridor_capacity_r3.0", "c"),
        ("h1_uniform", "h1u_r6_s1", "corridor_oversaturated_r6.0", "c"),
        ("h1_gated", "h1g_w0.32_s1", "corridor_gated_jam_wg0.32", "c"),
        ("h1_gated", "h1g_w1.6_s1", "corridor_gated_wg1.6", "c"),
        ("h2_default", "h2_default_w1.92_s1", "corridor_width1.92_3stripes", "c"),
        ("h2_default", "h2_default_w2.4_s1", "corridor_width2.40_3stripes", "c"),
        ("h2_default", "h2_default_w2.56_s1", "corridor_width2.56_4stripes", "c"),
        ("h2_sw080", "h2_sw080_w2.4_s1", "corridor_width2.40_stripe0.80", "c"),
        ("h3_counterflow", "h3_f1_s1", "corridor_counterflow_100_0", "c"),
        ("h3_counterflow", "h3_f0.5_s1", "corridor_counterflow_50_50", "c"),
        ("h3_reserve", "h3r_f0.5_ro0.34_s1", "corridor_counterflow_50_50_reserve0.34", "c"),
        ("h4_jamtime", "h4_r6_jt300_s1", "corridor_jamtime_default300_r6", "c"),
        ("h4_jamtime", "h4_r6_jt-1_s1", "corridor_jamtime_disabled_r6", "c"),
        ("app_grid", "app_w2_g20_s1", "egress_w2.0_green20", "e"),
        ("app_grid", "app_w6_g20_s1", "egress_w6.0_green20", "e"),
        ("app_grid", "app_w2_g40_s1", "egress_w2.0_green40", "e"),
        ("app_grid", "app_w6_g40_s1", "egress_w6.0_green40", "e"),
        ("app_grid", "app_w3_g20_s1", "egress_reference_w3.0_green20", "e"),
        ("veh_baseline", "vb_g20_s1", "egress_vehicle_baseline_green20", "e"),
        ("h5_striping_vs_noninteracting", "h5_nonInteracting_w2_g20_s1",
         "egress_nonInteracting_w2.0_green20", "e"),
        ("h5_reduced", "h5r_jupedsim_s1", "egress_jupedsim_reduced", "e"),
        ("h5_reduced", "h5r_striping_s1", "egress_striping_reduced", "e"),
        ("h5_reduced", "h5r_nonInteracting_s1", "egress_nonInteracting_reduced", "e"),
    ]
    for exp, run, name, kind in picks:
        src = os.path.join(S, exp, run)
        dst = os.path.join(O, "runs", name)
        keep = CORRIDOR_KEEP if kind == "c" else EGRESS_KEEP
        if copy_run(src, dst, keep):
            n += 1
            print("kept", name)
        else:
            print("MISSING", src)
    # networks on their own, for quick inspection
    os.makedirs(os.path.join(O, "net"), exist_ok=True)
    for run, out in [("runs/corridor_capacity_r3.0/corr.net.xml", "corridor_w2.24.net.xml"),
                     ("runs/corridor_gated_jam_wg0.32/corr.net.xml", "corridor_gated_wg0.32.net.xml"),
                     ("runs/egress_reference_w3.0_green20/egress.net.xml", "egress_w3.0.net.xml"),
                     ("runs/egress_w6.0_green40/egress.net.xml", "egress_w6.0_green40.net.xml")]:
        p = os.path.join(O, run)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(O, "net", out))
    print("retained %d runs" % n)


if __name__ == "__main__":
    main()
