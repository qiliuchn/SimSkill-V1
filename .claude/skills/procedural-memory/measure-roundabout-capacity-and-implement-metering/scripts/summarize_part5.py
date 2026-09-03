"""Condense the part-5 comparison JSON into the tables used in FINDINGS.md S5,
including the teleport-treatment sensitivity and the running-count-freeze check."""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(HERE, "results", "comparison")
V = ["sl", "two", "turbo", "sig", "slm_nometer", "slm_meter"]
LBL = {"sl": "single-lane RAB", "two": "conventional 2-lane RAB", "turbo": "turbo RAB",
       "sig": "signalized (Webster)", "slm_nometer": "single-lane RAB + meter bed, NO metering",
       "slm_meter": "single-lane RAB, METERED"}


def main():
    fs = sorted(glob.glob(os.path.join(RES, "comparison_ttt*.json")))
    if not fs:
        sys.exit("no comparison json")
    d = json.load(open(fs[-1]))
    out = []
    for sname in [k for k in d if k != "meter_cfg"]:
        sd = d[sname]
        w = sd["webster"]
        out.append(f"\n### Scenario `{sname}`\n")
        out.append(f"Webster sizing of the signalized reference: flow ratios "
                   f"{ {k: round(v,4) for k,v in w['flow_ratios'].items()} }, Y = {w['Y']}, "
                   f"L = {w['L']} s, {w['note']}, greens = {w['greens']} s, yellow = {w['yellow']} s.\n")
        for tkey in sorted(sd["arms"], key=lambda x: (x != "ttt300", x)):
            arms = sd["arms"][tkey]
            ttt = tkey[3:]
            out.append(f"\n**`--time-to-teleport {ttt}`** (6 CRN seeds, mean +/- 95% CI)\n")
            out.append("| variant | junction delay (s, censoring-robust) | delay, completed only (s) | throughput (veh/h) | served | worst approach served | Gini(delay) | max/min delay | teleports | never inserted | still running | running-count freeze |")
            out.append("|:--|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--|")
            for v in V:
                a = arms[v]
                frz = any(a["_raw"][s].get("running_frozen_tail") for s in a["_raw"])
                out.append(f"| {LBL[v]} | {a['delay_robust_s']['mean']:.1f} +/- {a['delay_robust_s']['ci95']:.1f} | "
                           f"{a['delay_completed_only_s']['mean']:.1f} | "
                           f"{a['throughput_vph']['mean']:.0f} +/- {a['throughput_vph']['ci95']:.0f} | "
                           f"{a['served_frac']['mean']:.3f} | {a['min_approach_served_frac']['mean']:.3f} | "
                           f"{a['equity_gini_delay']['mean']:.3f} | {a['equity_maxmin_delay_ratio']['mean']:.1f} | "
                           f"{a['teleports']['mean']:.1f} | {a['never_inserted']['mean']:.0f} | "
                           f"{a['still_running']['mean']:.0f} | {'YES' if frz else 'no'} |")
            out.append("")
            out.append("| variant | N delay | E delay | S delay | W delay | N thr | E thr | S thr | W thr |")
            out.append("|:--|---:|---:|---:|---:|---:|---:|---:|---:|")
            for v in V:
                a = arms[v]
                out.append(f"| {LBL[v]} | " + " | ".join(f"{a[f'arm_{x}_delay']['mean']:.1f}" for x in "NESW")
                           + " | " + " | ".join(f"{a[f'arm_{x}_thr']['mean']:.0f}" for x in "NESW") + " |")
            out.append("")
            if "ssm_total" in arms["sl"]:
                out.append("| variant | SSM conflicts | following | merging | crossing | genuine collisions | type-111 artifacts | TTC<1.5 s | PET<1.0 s | worst TTC (s) | max DRAC |")
                out.append("|:--|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
                for v in V:
                    a = arms[v]
                    g = lambda k: a["ssm_" + k]["mean"]
                    out.append(f"| {LBL[v]} | {g('total'):.0f} | {g('following'):.0f} | {g('merging'):.0f} | "
                               f"{g('crossing'):.0f} | {g('collisions'):.1f} | {g('type111_artifacts'):.1f} | "
                               f"{g('severe_ttc'):.0f} | {g('severe_pet'):.0f} | {g('worst_ttc'):.2f} | {g('max_drac'):.2f} |")
                out.append("")
            pr = sd.get("paired", {}).get(tkey, {})
            if pr:
                out.append("Paired (CRN) differences vs the **signalized** reference "
                           "(`*` = significant at 95%; `rho` = paired correlation, `VRF` = CRN variance-reduction factor):\n")
                out.append("| variant | d junction delay (s) | d throughput (veh/h) | d Gini | d worst-approach served | rho (delay) | VRF (delay) |")
                out.append("|:--|:--|:--|:--|:--|---:|---:|")
                for v in V:
                    k = f"{v}_vs_sig"
                    if k not in pr:
                        continue
                    p = pr[k]
                    f = lambda kk: (f"{p[kk]['mean_diff']:+.2f} ({p[kk]['pct']:+.1f}%)"
                                    + ("*" if p[kk]["significant_95"] else ""))
                    out.append(f"| {LBL[v]} | {f('delay_robust_s')} | {f('throughput_vph')} | "
                               f"{f('equity_gini_delay')} | {f('min_approach_served_frac')} | "
                               f"{p['delay_robust_s']['paired_corr']} | {p['delay_robust_s']['crn_vrf']} |")
                out.append("")
                k = "slm_meter_vs_slm_nometer"
                if k in pr:
                    p = pr[k]
                    f = lambda kk: (f"{p[kk]['mean_diff']:+.2f} ({p[kk]['pct']:+.1f}%)"
                                    + ("*" if p[kk]["significant_95"] else ""))
                    out.append("Metered vs unmetered on the identical network: "
                               f"junction delay {f('delay_robust_s')}, throughput {f('throughput_vph')}, "
                               f"Gini {f('equity_gini_delay')}, N-approach delay {f('arm_N_delay')}, "
                               f"N-approach throughput {f('arm_N_thr')}.\n")
    txt = "\n".join(out)
    open(os.path.join(HERE, "results", "part5_tables.md"), "w").write(txt)
    print(txt)


if __name__ == "__main__":
    main()
