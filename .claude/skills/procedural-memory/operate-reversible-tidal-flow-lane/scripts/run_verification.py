#!/usr/bin/env python3
"""CHANGEOVER SAFETY VERIFICATION (part 2).

Three arms, identical network / demand / seed, differing ONLY in the changeover
procedure applied at t=1200 s when the corridor goes 3+3 -> 4+2 (physical lane
L4 taken from the westbound direction):

  swept        full procedure: stop admitting, cascade sweep, grant only when
               the whole lane is verifiably empty; nominal dead time 60 s
  swept_dt0    identical, but nominal dead time 0 s -- shows the safety comes
               from the SWEEP, not from an arbitrary dead-time constant
  broken       DELIBERATELY BROKEN positive control: instantaneous permission
               flip, no sweep at all

Each arm is checked three independent ways:
  1  live TraCI occupancy scan at the instant permissions flip
  2  offline geometric scan of SUMO's own fcd-output (shares no code with 1)
  3  SUMO's SSM device -- included to test whether the standard safety
     instrument can see this hazard at all

Writes outputs/analysis/changeover_verification.json
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import NETDIR, DEMDIR, RUNDIR, ANADIR, SCRIPTS, ensure_dirs

END = 2400.0
FLIP_T = 1200.0
FCD_BEGIN = 1150.0


def make_demand():
    rou = os.path.join(DEMDIR, "verif.rou.xml")
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "gen_demand.py"),
                    "--out", rou, "--seed", "99",
                    "--period", f"0,{int(END)},5000,0.48",
                    "--cross", "400", "--cross-end", str(int(END))],
                   check=True, capture_output=True)
    return rou


def edge_filter_file():
    p = os.path.join(RUNDIR, "fcd_edges.txt")
    with open(p, "w") as f:
        for e in ("apW_in", "COR_EB", "apE_out", "apE_in", "COR_WB", "apW_out"):
            f.write(f"edge:{e}\n")
    return p


def run_arm(name, policy, dead_time, rou, filt):
    outdir = os.path.join(RUNDIR, "verif_" + name)
    os.makedirs(outdir, exist_ok=True)
    fcd = os.path.join(outdir, "fcd.xml")
    ssm = os.path.join(outdir, "ssm.xml")
    cmd = [sys.executable, os.path.join(SCRIPTS, "reversible_controller.py"),
           "--net", os.path.join(NETDIR, "encB_open.net.xml"),
           "--routes", rou, "--outdir", outdir, "--policy", policy,
           "--start-config", "3+3", "--schedule", f"{int(FLIP_T)}:4+2",
           "--dead-time", str(dead_time), "--seed", "99", "--end", str(END),
           "--fcd", fcd, "--fcd-begin", str(FCD_BEGIN),
           "--fcd-filter", filt, "--ssm", ssm]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("controller failed: " + name)
    print(r.stdout.strip().splitlines()[-1])
    return outdir, fcd, ssm


def ssm_summary(path):
    """Does SUMO's own SSM device see the head-on hazard at all?

    Decisive test: count <conflict> records whose ego and foe travel in
    OPPOSITE directions (vehicle ids are prefixed EB./WB. by gen_demand.py).
    """
    if not os.path.exists(path):
        return dict(exists=False)
    root = ET.parse(path).getroot()
    confl = root.findall("conflict")
    types = {}
    worst_ttc = None
    opposing = 0
    collisions = 0
    for c in confl:
        ego, foe = c.get("ego", ""), c.get("foe", "")
        de = ego.split(".")[0]
        df = foe.split(".")[0]
        if {de, df} == {"EB", "WB"}:
            opposing += 1
        for meas in c:
            ty = meas.get("type")
            if ty:
                types[ty] = types.get(ty, 0) + 1
                if ty == "111":
                    collisions += 1
            if meas.tag == "minTTC" and meas.get("value") not in (None, "NA"):
                v = float(meas.get("value"))
                worst_ttc = v if worst_ttc is None else min(worst_ttc, v)
    return dict(exists=True, n_conflicts=len(confl),
                n_conflicts_between_opposing_direction_vehicles=opposing,
                n_simulated_collisions_type111=collisions,
                encounter_type_codes=dict(sorted(types.items(),
                                                 key=lambda kv: -kv[1])[:10]),
                min_TTC=worst_ttc,
                note="SSM encounter-type codes: 2/3/18 following, 6/7/8/19 "
                     "merging, 10-17 crossing, 111 collision.  There is no "
                     "head-on code because SUMO never relates two coincident "
                     "opposing edges.")


def main():
    ensure_dirs()
    rou = make_demand()
    filt = edge_filter_file()
    arms = [("swept", "B", 60.0), ("swept_dt0", "B", 0.0), ("broken", "broken", 0.0)]
    res = {}
    for name, policy, dt in arms:
        outdir, fcd, ssm = run_arm(name, policy, dt, rou, filt)
        # 2: independent offline FCD scan
        fcd_json = os.path.join(outdir, "headon_fcd.json")
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "verify_headon_fcd.py"),
                        "--fcd", fcd, "--out", fcd_json, "--label", name],
                       check=True, capture_output=True)
        live = json.load(open(os.path.join(outdir, "headon_scan.json")))
        offl = json.load(open(fcd_json))
        cho = json.load(open(os.path.join(outdir, "changeover_log.json")))
        res[name] = dict(
            outdir=outdir,
            changeovers=cho["changeovers"],
            check1_live_traci_scan={k: v for k, v in live.items() if k != "events"},
            check1_first_events=live["events"][:12],
            check2_offline_fcd_scan={k: v for k, v in offl.items() if k != "events"},
            check2_first_events=offl["events"][:12],
            check3_ssm_device=ssm_summary(os.path.join(outdir, "ssm.xml")),
        )
        # keep the artifacts small: fcd files are large, drop after scanning
        sz = os.path.getsize(fcd) / 1e6
        res[name]["fcd_file_mb"] = round(sz, 1)
        os.remove(fcd)

    out = os.path.join(ANADIR, "changeover_verification.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=2)
    for k, v in res.items():
        c = v["changeovers"][0] if v["changeovers"] else {}
        print(f"\n=== {k}")
        print("  clearance_s          :", c.get("clearance_s"))
        print("  occupancy at grant   :", c.get("occupancy_at_grant_total"))
        print("  residual at flip     :", c.get("residual_at_instant_flip"))
        print("  live scan  steps/ovl :",
              v["check1_live_traci_scan"]["steps_with_opposing_cooccupancy"], "/",
              v["check1_live_traci_scan"]["total_overlapping_pair_samples"])
        print("  fcd  scan  steps/ovl :",
              v["check2_offline_fcd_scan"]["steps_with_opposing_cooccupancy"], "/",
              v["check2_offline_fcd_scan"]["overlapping_pair_samples"])
        print("  ssm conflicts        :", v["check3_ssm_device"].get("n_conflicts"))
    print("\nwrote", out)


if __name__ == "__main__":
    main()
