#!/usr/bin/env python3
"""Copy the small, final deliverables into the episodic-memory outputs/ directory.
Bulk raw traces stay in the attempt working directory per project convention;
exactly ONE full raw output set is exported so the numbers can be re-derived."""
import os
import sys
import json
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scenario as S  # noqa: E402

ROOT = os.path.dirname(HERE)
OUTDIR = os.environ.get("OUTDIR", os.path.join(os.path.dirname(os.path.dirname(ROOT)), "outputs"))

RAW_CELL = os.path.join(ROOT, "runs", "homo__HUMAN", "s1")
RAW_CELL2 = os.path.join(ROOT, "runs", "sweep__CACC__p40", "s1")


def main():
    for d in ["net", "scripts", "raw_example__homo_HUMAN_seed1",
              "raw_example__sweep_CACC_p40_seed1"]:
        os.makedirs(os.path.join(OUTDIR, d), exist_ok=True)

    # --- network: plain XML sources + the compiled net ---
    for f in ["bneck.nod.xml", "bneck.edg.xml", "bneck.net.xml",
              "nodrop.edg.xml", "nodrop.net.xml"]:
        p = os.path.join(ROOT, "net", f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(OUTDIR, "net", f))

    # --- standalone vType definition file (the fleet under study) ---
    with open(os.path.join(OUTDIR, "net", "vtypes.add.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!-- Fleet definitions for the CAV-penetration bottleneck study.\n'
                '     Every vType shares length/minGap/accel/decel/emergencyDecel/\n'
                '     speedFactor/laneChangeModel.  ONLY carFollowModel, sigma and tau\n'
                '     differ, which is what makes HUMAN_FAST a valid mechanism control:\n'
                '       HUMAN_FAST = Krauss, sigma=0, tau=0.9  (same tau as ACC/CACC)\n'
                '       ACC        = ACC model, tau=0.9\n'
                '       CACC       = CACC model, tau=0.9  -->\n'
                '<additional>\n' + S.vtype_xml() + '\n</additional>\n')

    # --- scripts ---
    for f in ["scenario.py", "run_cell.py", "sweep.py", "analyze.py", "plots.py",
              "make_tables.py", "verify.py", "cacc_leader_probe.py", "audit_warnings.py",
              "package_outputs.py"]:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(OUTDIR, "scripts", f))

    # --- probe results ---
    p = os.path.join(ROOT, "probe", "probe_results.json")
    if os.path.exists(p):
        shutil.copy2(p, os.path.join(OUTDIR, "probe_results.json"))

    # --- one FULL raw output set per convention ---
    for src, dst in [(RAW_CELL, "raw_example__homo_HUMAN_seed1"),
                     (RAW_CELL2, "raw_example__sweep_CACC_p40_seed1")]:
        if not os.path.isdir(src):
            continue
        for f in sorted(os.listdir(src)):
            fp = os.path.join(src, f)
            if not os.path.isfile(fp):
                continue
            if f in ("routes.rou.xml", "fcd.xml.gz"):      # large, regenerable
                continue
            shutil.copy2(fp, os.path.join(OUTDIR, dst, f))

    # --- the per-run (not per-cell) index, so replication variance is auditable ---
    idx = os.path.join(ROOT, "runs_index.csv")
    if os.path.exists(idx):
        shutil.copy2(idx, os.path.join(OUTDIR, "runs_index.csv"))

    # --- per-seed discharge values behind every cell mean ---
    sys.path.insert(0, HERE)
    from analyze import load_all
    cells = load_all()
    import csv
    with open(os.path.join(OUTDIR, "per_seed_discharge.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cell", "seed", "discharge_veh_h", "pre_breakdown_peak",
                    "frac_time_queued", "mean_travel_time_s", "n_trips",
                    "bn_speed_while_queued", "warm_flag"])
        for c in sorted(cells):
            for sd, r in cells[c]:
                w.writerow([c, sd, round(r["discharge"], 1) if r["discharge"] == r["discharge"] else "",
                            round(r["pre_peak"], 1) if r["pre_peak"] == r["pre_peak"] else "",
                            round(r["frac_queued"], 3),
                            round(r["mean_duration"], 1), r["n_trips"],
                            round(r["bn_speed_queued"], 2) if r["bn_speed_queued"] == r["bn_speed_queued"] else "",
                            r["warm_flag"]])
    print("packaged deliverables into", OUTDIR)
    for f in sorted(os.listdir(OUTDIR)):
        print("   ", f)


if __name__ == "__main__":
    main()
