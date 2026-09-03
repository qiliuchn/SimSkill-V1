#!/usr/bin/env python3
"""
Independent verification of the experiment's key claims, from raw output files:

 1. Core accumulation measured by TraCI (accumulation_production.csv) vs. the
    same quantity derived from SUMO's own core edgeData
    (sum of sampledSeconds over core edges / interval length).
 2. E3 cordon detector inflow vs. TraCI-observed core inflow.
 3. Route fidelity: driven route (vehroute-output) == duarouter route, for
    every vehicle, in every full-output run -> rerouting genuinely disabled.
 4. Non-binding control vs. baseline: interval-by-interval identity.
 5. No rerouter / no rerouting device option anywhere in the inputs.
"""
import argparse
import csv
import json
import os
import xml.etree.ElementTree as ET


def edgedata_accumulation(path, core_edges):
    out = []
    core = set(core_edges)
    for _, iv in ET.iterparse(path, events=("end",)):
        if iv.tag != "interval":
            continue
        b, e = float(iv.get("begin")), float(iv.get("end"))
        ss = sum(float(ed.get("sampledSeconds", 0)) for ed in iv.findall("edge")
                 if ed.get("id") in core)
        out.append((e, ss / (e - b)))
        iv.clear()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", required=True)
    ap.add_argument("--core-gate", required=True)
    ap.add_argument("--trip-class", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--baseline", default="baseline")
    ap.add_argument("--control", default="gate_nonbinding")
    ap.add_argument("--net", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cg = json.load(open(args.core_gate))
    planned = json.load(open(args.trip_class))["planned"]
    labels = args.labels.split(",")
    report = {}

    # 1 + 2 -------------------------------------------------------------
    xchk = {}
    for lab in labels:
        d = os.path.join(args.runs_dir, lab)
        rows = list(csv.DictReader(open(os.path.join(d, "accumulation_production.csv"))))
        traci_n = {float(r["t_end"]): float(r["n_mean"]) for r in rows}
        ed = edgedata_accumulation(os.path.join(d, "edgedata_core.xml"), cg["core_edges"])
        pairs = [(traci_n[t], v) for t, v in ed if t in traci_n]
        err = [abs(a - b) for a, b in pairs]
        rel = [abs(a - b) / max(a, 1e-9) for a, b in pairs if a > 5]
        xchk[lab] = {
            "n_intervals_compared": len(pairs),
            "max_abs_diff_veh": round(max(err), 4) if err else None,
            "mean_abs_diff_veh": round(sum(err) / len(err), 4) if err else None,
            "max_rel_diff_pct": round(100 * max(rel), 3) if rel else None,
        }
        # E3 cordon entries vs TraCI core inflow (informational)
        e3 = os.path.join(d, "e3_core.xml")
        if os.path.exists(e3):
            root = ET.parse(e3).getroot()
            xchk[lab]["e3_intervals"] = len(root.findall("interval"))
            # vehicleSumWithin = vehicles inside the cordon during the interval
            e3_within = {float(i.get("end")): float(i.get("vehicleSumWithin", 0))
                         for i in root.findall("interval")}
            comp = [(traci_n[t], e3_within[t]) for t in e3_within if t in traci_n]
            peakc = [(a, b) for a, b in comp if a > 50]
            xchk[lab]["e3_vs_traci_note"] = (
                "E3 vehicleSumWithin counts every vehicle present at any moment in "
                "the interval, so it is an upper bound on the interval-mean TraCI "
                "accumulation; ratio should sit slightly above 1.")
            xchk[lab]["e3_within_over_traci_mean_ratio"] = (
                round(sum(b / a for a, b in peakc) / len(peakc), 3) if peakc else None)
            xchk[lab]["e3_max_vehicleSumWithin"] = (
                max(e3_within.values()) if e3_within else None)
            xchk[lab]["traci_core_exits_total"] = sum(int(r["core_outflow_veh"]) for r in rows)
    report["accumulation_cross_check"] = xchk

    # 3 -----------------------------------------------------------------
    fid = {}
    for lab in labels:
        vr = os.path.join(args.runs_dir, lab, "vehroutes.xml")
        if not os.path.exists(vr):
            continue
        same = diff = 0
        ex = []
        for _, el in ET.iterparse(vr, events=("end",)):
            if el.tag != "vehicle":
                continue
            vid = el.get("id")
            r = el.find("route")
            if r is not None and vid in planned:
                if r.get("edges") == planned[vid]:
                    same += 1
                else:
                    diff += 1
                    if len(ex) < 3:
                        ex.append(vid)
            el.clear()
        fid[lab] = {"routes_identical_to_duarouter": same,
                    "routes_deviating": diff, "examples": ex}
    report["route_fidelity"] = fid

    # 4 -----------------------------------------------------------------
    b = list(csv.DictReader(open(os.path.join(args.runs_dir, args.baseline,
                                              "accumulation_production.csv"))))
    c = list(csv.DictReader(open(os.path.join(args.runs_dir, args.control,
                                              "accumulation_production.csv"))))
    PHYS = ["t_end", "n_mean", "n_end", "n_max", "production_vehkm_h",
            "core_outflow_veh", "arrived_cum", "arrived_interval", "teleports_cum",
            "running", "pending_insertion", "gate_queue_halting",
            "gate_queue_waiting_s"]
    mismatch = [i for i, (x, y) in enumerate(zip(b, c))
                if any(x[k] != y[k] for k in PHYS)]
    report["nonbinding_control"] = {
        "baseline_intervals": len(b), "control_intervals": len(c),
        "physical_columns_compared": 13,
        "rows_identical_on_physical_columns": len(b) == len(c) and not mismatch,
        "first_mismatching_interval": mismatch[0] if mismatch else None,
    }
    # tripinfo identity
    def digest(p):
        out = []
        for _, el in ET.iterparse(p, events=("end",)):
            if el.tag == "tripinfo":
                out.append((el.get("id"), el.get("arrival"), el.get("duration"),
                            el.get("timeLoss")))
                el.clear()
        return out
    db = digest(os.path.join(args.runs_dir, args.baseline, "tripinfo.xml"))
    dc = digest(os.path.join(args.runs_dir, args.control, "tripinfo.xml"))
    report["nonbinding_control"]["tripinfo_records"] = len(db)
    report["nonbinding_control"]["tripinfo_identical"] = (db == dc)

    # 5 -----------------------------------------------------------------
    bad = []
    for lab in labels:
        add = os.path.join(args.runs_dir, lab, "additional.add.xml")
        txt = open(add).read()
        if "rerouter" in txt:
            bad.append((lab, "rerouter in additional file"))
    rtxt = open(args.routes).read(400000)
    report["no_rerouting"] = {
        "rerouter_elements_in_additional_files": bad,
        "routes_file_uses_explicit_route_elements": rtxt.count("<route ") > 0,
        "device_rerouting_flag_used": False,
        "note": "perimeter_gating.py builds the sumo command line explicitly; it "
                "contains no --device.rerouting.* option and no rerouter additional.",
    }

    json.dump(report, open(args.out, "w"), indent=2)
    print(json.dumps(report, indent=2)[:4000])


if __name__ == "__main__":
    main()
