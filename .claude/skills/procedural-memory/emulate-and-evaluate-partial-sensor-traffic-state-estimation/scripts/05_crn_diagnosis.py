#!/usr/bin/env python3
"""
05_crn_diagnosis.py

The CRN check in 04 FAILED for the real --device.fcd.probability arms: every
distinct probability value produced a DIFFERENT tripinfo, i.e. the probe
penetration setting perturbs the underlying traffic.  This script:

  (a) quantifies HOW BIG that perturbation is (per-vehicle duration differences
      vs. master, and aggregate mean-duration spread across arms),
  (b) tests whether --device.fcd.deterministic repairs CRN,
  (c) tests the alternative --device.fcd.explicit (named vehicle list), which
      should require no RNG draw at all,
  (d) hashes the teleport arms to confirm --time-to-teleport is inert here.

Conclusion drives the study design: if SUMO-side penetration breaks CRN, the
penetration sweep must instead be done by OFFLINE SUBSAMPLING of the 100% FCD.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SCEN = os.path.abspath(os.path.join(HERE, "..", "scenario"))
RUNS = os.path.abspath(os.path.join(HERE, "..", "..", "runs"))
RES = os.path.abspath(os.path.join(HERE, "..", "results"))
sys.path.insert(0, HERE)
from importlib import import_module
v4 = import_module("04_verify_crn_and_teleports") if False else None


def tripinfo_map(path):
    """id -> (depart, arrival, duration, routeLength, timeLoss)"""
    out = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            out[el.get("id")] = (float(el.get("depart")), float(el.get("arrival")),
                                 float(el.get("duration")), float(el.get("routeLength")),
                                 float(el.get("timeLoss")))
            el.clear()
    return out


def hsh(path):
    import hashlib
    h = hashlib.sha1()
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            h.update("|".join(f"{k}={el.get(k)}" for k in sorted(el.keys())).encode())
            el.clear()
    return h.hexdigest()


def run_variant(name, extra):
    outdir = os.path.join(RUNS, name)
    os.makedirs(outdir, exist_ok=True)
    cmd = ["sumo",
           "-n", os.path.join(SCEN, "arterial.net.xml"),
           "-r", os.path.join(SCEN, "demand.rou.xml"),
           "-a", os.path.join(SCEN, "tls.add.xml"),
           "--begin", "0", "--end", "5400", "--step-length", "1", "--seed", "42",
           "--time-to-teleport", "300",
           "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
           "--tripinfo-output.write-unfinished",
           "--no-step-log", "true", "--xml-validation", "never"] + extra
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(name, "FAILED\n", r.stderr[-2000:])
        return None
    return os.path.join(outdir, "tripinfo.xml")


def main():
    res = {}
    master = tripinfo_map(os.path.join(RUNS, "master", "tripinfo.xml"))
    base_h = hsh(os.path.join(RUNS, "master", "tripinfo.xml"))

    # -------- (a) magnitude of the CRN violation across real probability arms
    rows = []
    for arm in ["pilot"] + [f"p{p}_T1" for p in [0.5, 1, 2, 5, 10, 20, 50, 100]]:
        p = os.path.join(RUNS, arm, "tripinfo.xml")
        m = tripinfo_map(p)
        common = set(m) & set(master)
        diffs = [m[k][2] - master[k][2] for k in common]
        nz = [d for d in diffs if abs(d) > 1e-9]
        mean_arm = sum(m[k][2] for k in m) / len(m)
        mean_ref = sum(master[k][2] for k in master) / len(master)
        rows.append(dict(arm=arm, n=len(m), n_common=len(common),
                         n_vehicles_with_different_duration=len(nz),
                         frac_perturbed=len(nz) / len(common),
                         max_abs_duration_diff_s=max(abs(d) for d in diffs) if diffs else 0.0,
                         mean_duration_s=mean_arm,
                         mean_duration_diff_vs_master_s=mean_arm - mean_ref,
                         hash_matches_master=(hsh(p) == base_h)))
        print(f"{arm:10s} n={rows[-1]['n']} perturbed={rows[-1]['frac_perturbed']*100:5.1f}% "
              f"maxdiff={rows[-1]['max_abs_duration_diff_s']:7.1f}s "
              f"meandur={mean_arm:7.2f}s (delta {mean_arm-mean_ref:+.3f}s)")
    res["real_fcd_probability_arms"] = rows
    res["mean_duration_spread_s"] = max(r["mean_duration_s"] for r in rows) - \
                                    min(r["mean_duration_s"] for r in rows)

    # -------- (b) does --device.fcd.deterministic repair CRN?
    det = {}
    for pct in [0.5, 1, 2, 5, 10, 20, 50, 100]:
        p = run_variant(f"det_p{pct}", ["--device.fcd.probability", str(pct / 100.0),
                                        "--device.fcd.deterministic"])
        det[f"p{pct}"] = hsh(p)
    ndet = len(set(det.values()))
    res["deterministic_flag"] = dict(hashes=det, n_distinct=ndet,
                                     crn_preserved=(ndet == 1))
    print(f"\n--device.fcd.deterministic: {ndet} distinct tripinfo hashes across 8 "
          f"penetration levels -> CRN {'PRESERVED' if ndet==1 else 'STILL BROKEN'}")

    # -------- (c) --device.fcd.explicit (no RNG draw)
    ids = sorted(master.keys())
    exp = {}
    for k, frac in [("10pct", 10), ("50pct", 50)]:
        sel = ids[::(100 // frac)]
        lf = os.path.join(RUNS, f"explicit_{k}_ids.txt")
        open(lf, "w").write(",".join(sel))
        p = run_variant(f"explicit_{k}", ["--device.fcd.explicit", ",".join(sel[:4000])])
        exp[k] = hsh(p) if p else None
    res["explicit_flag"] = dict(hashes=exp, base=base_h,
                                crn_preserved=all(v == base_h or v is not None and
                                                  v == list(exp.values())[0] for v in exp.values()),
                                matches_no_device_run=(exp.get("10pct") ==
                                                       hsh(os.path.join(RUNS, "pilot", "tripinfo.xml"))))
    print("--device.fcd.explicit hashes:", {k: (v[:12] if v else None) for k, v in exp.items()},
          " pilot(no device):", hsh(os.path.join(RUNS, "pilot", "tripinfo.xml"))[:12])

    # -------- (d) teleport arms
    tt = {a: hsh(os.path.join(RUNS, a, "tripinfo.xml"))
          for a in ["ttt-1", "ttt120", "ttt300", "ttt600", "pilot"]}
    res["teleport_arm_hashes"] = tt
    print("\nteleport arms distinct hashes:", len(set(tt.values())), {k: v[:12] for k, v in tt.items()})

    json.dump(res, open(os.path.join(RES, "crn_diagnosis.json"), "w"), indent=1)
    print("wrote", os.path.join(RES, "crn_diagnosis.json"))


if __name__ == "__main__":
    main()
