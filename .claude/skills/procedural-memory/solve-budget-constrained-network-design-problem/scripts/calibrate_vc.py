#!/usr/bin/env python3
"""
Calibrate the EFFECTIVE saturation flow of a signalised grid approach directly
from the demand-sweep edgeData, instead of assuming the textbook 1900 veh/h/ln.

For every grid edge in every sweep level we compute
    s_hat = peak_30min_flow_scaled_to_veh_h / (numLanes * greenRatio)
and take a high quantile of s_hat over edges that are actually saturated
(v/c_1900 > 0.5) at the highest demand levels.  v/c is then recomputed with the
calibrated value and the loading level whose mean v/c on the 12 most-loaded
grid edges lands in 0.85-1.05 is selected.
"""
import os, sys, json, glob, csv
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from demand_sweep import edge_green_ratios, edge_lanes, peak_flows, WORK, OUT

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def main():
    levels = sorted(int(d[1:]) for d in os.listdir(WORK) if d.startswith("n"))
    per_level = {}
    shat_all = []
    for n in levels:
        d = os.path.join(WORK, "n%d" % n)
        netf = os.path.join(d, "net.net.xml")
        edf = os.path.join(d, "rec", "edgedata.xml")
        if not (os.path.exists(netf) and os.path.exists(edf)):
            continue
        gr = edge_green_ratios(netf); ln = edge_lanes(netf); fl = peak_flows(edf)
        rows = []
        for e, f in fl.items():
            if e.split("_")[0][0] in "WESN" or e.split("_")[1][0] in "WESN":
                continue                      # access/gate edges are uncontrolled
            g = gr.get(e, 1.0); L = ln.get(e, 1)
            if g >= 0.999:
                continue                      # not signal controlled
            rows.append((e, f, L, g, f / (L * 1900.0 * g), f / (L * g)))
        per_level[n] = rows
        if n >= 4000:
            shat_all += [r[5] for r in rows if r[4] > 0.5]
    shat_all.sort()
    q = lambda p: shat_all[min(len(shat_all) - 1, int(p * len(shat_all)))]
    s_eff = q(0.95)
    print("empirical saturation-flow estimates s_hat = flow/(lanes*g/C), "
          "saturated edges (vc_1900>0.5) at demand>=4000:")
    print("  n=%d  median=%.0f  p75=%.0f  p90=%.0f  p95=%.0f  max=%.0f veh/h/lane"
          % (len(shat_all), st.median(shat_all), q(.75), q(.90), q(.95), shat_all[-1]))
    print("  -> adopted effective saturation flow s_eff = %.0f veh/h/lane" % s_eff)

    out = []
    for n in sorted(per_level):
        rows = per_level[n]
        vc = sorted(((e, f / (L * s_eff * g)) for e, f, L, g, _, _ in rows),
                    key=lambda kv: -kv[1])
        top = vc[:12]
        out.append(dict(nveh=n,
                        mean_vc_top12=round(sum(v for _, v in top) / len(top), 4),
                        max_vc=round(vc[0][1], 4),
                        mean_vc_all_grid=round(sum(v for _, v in vc) / len(vc), 4),
                        n_edges_vc_ge_085=sum(1 for _, v in vc if v >= 0.85),
                        top12=[[e, round(v, 3)] for e, v in top]))
    print("\n%6s %12s %8s %10s %8s" % ("nveh", "meanvc_top12", "max_vc", "meanvc_all", "n>=0.85"))
    for r in out:
        print("%6d %12.3f %8.3f %10.3f %8d"
              % (r["nveh"], r["mean_vc_top12"], r["max_vc"],
                 r["mean_vc_all_grid"], r["n_edges_vc_ge_085"]))
    with open(os.path.join(OUT, "vc_calibration.json"), "w") as f:
        json.dump(dict(s_eff_veh_h_lane=round(s_eff, 1),
                       n_samples=len(shat_all),
                       median=round(st.median(shat_all), 1),
                       p90=round(q(.90), 1), levels=out), f, indent=2)


if __name__ == "__main__":
    main()
