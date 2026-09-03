#!/usr/bin/env python3
"""Run one SUMO scenario and sample per-edge Harmonoise noise every step via TraCI.

Decibels do NOT average arithmetically. To get a correct time-averaged dB(A)
(equivalent-continuous level, Leq) for an edge we:
  1. convert each per-step dB sample L to linear acoustic intensity  I = 10^(L/10)
  2. arithmetic-average the intensities over time
  3. convert back  Leq = 10*log10(mean(I))
We deliberately ALSO record the (wrong) arithmetic mean of the dB values so the
mis-statement from naive averaging can be quantified (task step 6c).

A meandata edgeData type="harmonoise" additional file is loaded in the same run so
SUMO's own internal energy-averaged 'noise' attribute can cross-check our TraCI value.
"""
import os, sys, argparse, math, csv

SUMO_HOME = os.environ["SUMO_HOME"]
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--route", required=True)
    ap.add_argument("--vtypes", required=True)
    ap.add_argument("--meandata-add", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--end", type=float, default=3600.0)
    ap.add_argument("--out-csv", required=True)
    args = ap.parse_args()

    sumo = os.path.join(SUMO_HOME, "bin", "sumo")
    traci.start([sumo, "-n", args.net, "-r", args.route,
                 "-a", args.vtypes + "," + args.meandata_add,
                 "--begin", "0", "--end", str(args.end),
                 "--step-length", "1", "--no-step-log", "true",
                 "--no-warnings", "true"])

    edges = [e for e in traci.edge.getIDList() if not e.startswith(":")]
    edges.sort()

    # per-edge accumulators
    sum_I_all = {e: 0.0 for e in edges}      # sum of intensity over ALL steps
    sum_I_act = {e: 0.0 for e in edges}      # sum of intensity over ACTIVE steps (noise>0)
    sum_dB_act = {e: 0.0 for e in edges}     # sum of dB over ACTIVE steps (for naive mean)
    n_act = {e: 0 for e in edges}
    max_dB = {e: 0.0 for e in edges}
    veh_steps = {e: 0 for e in edges}        # sum of veh count over steps -> mean occupancy
    n_steps = 0

    while traci.simulation.getTime() < args.end:
        traci.simulationStep()
        n_steps += 1
        for e in edges:
            L = traci.edge.getNoiseEmission(e)          # instantaneous edge noise, dB(A)
            I = 10.0 ** (L / 10.0)
            sum_I_all[e] += I
            if L > 0.0:
                sum_I_act[e] += I
                sum_dB_act[e] += L
                n_act[e] += 1
                if L > max_dB[e]:
                    max_dB[e] = L
            veh_steps[e] += traci.edge.getLastStepVehicleNumber(e)
    traci.close()

    rows = []
    for e in edges:
        leq_full = 10.0 * math.log10(sum_I_all[e] / n_steps) if sum_I_all[e] > 0 else 0.0
        if n_act[e] > 0:
            leq_active = 10.0 * math.log10(sum_I_act[e] / n_act[e])
            arith_active = sum_dB_act[e] / n_act[e]
        else:
            leq_active = arith_active = 0.0
        rows.append({
            "scenario": args.scenario,
            "edge": e,
            "leq_active_dBA": round(leq_active, 3),      # energy avg over occupied time (matches meandata)
            "leq_full_dBA": round(leq_full, 3),          # energy avg over whole hour (roadside Leq,1h)
            "arith_mean_active_dBA": round(arith_active, 3),  # WRONG naive dB mean, for 6c
            "energy_minus_arith_dB": round(leq_active - arith_active, 3),
            "max_dBA": round(max_dB[e], 3),
            "mean_veh_on_edge": round(veh_steps[e] / n_steps, 3),
            "active_steps": n_act[e],
            "total_steps": n_steps,
        })

    write_header = not os.path.exists(args.out_csv)
    with open(args.out_csv, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if write_header:
            w.writeheader()
        w.writerows(rows)
    print(f"[{args.scenario}] wrote {len(rows)} edge rows; steps={n_steps}")


if __name__ == "__main__":
    main()
