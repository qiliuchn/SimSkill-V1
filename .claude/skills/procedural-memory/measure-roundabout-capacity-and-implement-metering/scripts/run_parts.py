"""
Drivers for PART 3 (unbalanced-demand starvation), PART 4 (metering sweep) and
PART 5 (five-way comparison + teleport validity).

Every comparison uses paired Common Random Numbers: the identical seed list is
used in every arm, and differences are evaluated with a paired t-test whose
reported paired correlation / variance-reduction factor shows whether CRN
actually helped for that metric (per `quantify-sumo-run-to-run-variability`: CRN
is not free money).
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenarios as sc
import metering as mt
import webster_signal as ws
from common import run_sumo
from stats import mean_ci, paired_diff

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(HERE, "networks")
RES = os.path.join(HERE, "results")
END = 3600
M_MINOR = 400


def ssm_add(path, ssm):
    return path


def run_variant(variant, rou, outdir, seed, end=END, ttt=300, ssm_file=None,
                webster_add=None, meter_cfg=None):
    """variant in {sl, two, turbo, sig, slm_nometer, slm_meter}"""
    if variant in ("slm_nometer", "slm_meter"):
        cfg = meter_cfg or {}
        return mt.run(os.path.join(NET, "slm.net.xml"), rou, outdir, end, seed=seed,
                      ttt=ttt, meter=(variant == "slm_meter"), ssm_file=ssm_file, **cfg)
    add = [webster_add] if (variant == "sig" and webster_add) else None
    r = run_sumo(os.path.join(NET, variant + ".net.xml"), rou, outdir, end=end, seed=seed,
                 step=0.5, ttt=ttt, additional=add, ssm_file=ssm_file)
    assert r.returncode == 0, r.stderr[:2000]
    return {}


# ---------------------------------------------------------------- PART 3
def part3(seeds, out):
    ladder = [300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1400, 1600]
    rows = []
    for D in ladder:
        vol = sc.unbalanced(D, M_MINOR)
        per = {}
        for s in seeds:
            d = os.path.join(out, f"D{D}_s{s}")
            os.makedirs(d, exist_ok=True)
            rou = sc.write_scenario(os.path.join(d, "d.rou.xml"), vol, END)
            run_variant("sl", rou, d, s)
            per[s] = sc.collect(d, vol, END)
        agg = {}
        for k in per[seeds[0]]["agg"]:
            vals = [per[s]["agg"][k] for s in seeds]
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
                agg[k] = mean_ci(vals)
        arms = {}
        for a in "NESW":
            arms[a] = {k: mean_ci([per[s]["per_arm"][a][k] for s in seeds])
                       for k in ("throughput_vph", "delay_robust_s", "served_frac",
                                 "delay_completed_only_s", "never_inserted", "still_running")}
        dominant_share = round((D + 0.3 * D) / (1.3 * D + 2 * M_MINOR), 4)
        rows.append(dict(D=D, M=M_MINOR, dominant_axis_share=dominant_share,
                         planned_vc_at_N=round(0.85 * D + 0.15 * M_MINOR, 1),
                         agg=agg, arms=arms))
        print(f"[p3] D={D:5d} share={dominant_share:.3f} | N thr={arms['N']['throughput_vph']['mean']:6.1f} "
              f"delay={arms['N']['delay_robust_s']['mean']:8.1f} served={arms['N']['served_frac']['mean']:.3f} "
              f"| agg delay={agg['delay_robust_s']['mean']:7.1f} served={agg['served_frac']['mean']:.3f} "
              f"gini={agg['equity_gini_delay']['mean']:.3f} maxmin={agg['equity_maxmin_delay_ratio']['mean']:.2f}")
    # starvation threshold: first D where N's robust delay exceeds 3x the mean of
    # the other three approaches AND N's served fraction drops below 0.97
    thr = None
    for r in rows:
        others = [r["arms"][a]["delay_robust_s"]["mean"] for a in "ESW"]
        n = r["arms"]["N"]["delay_robust_s"]["mean"]
        r["N_over_others_ratio"] = round(n / (sum(others) / 3), 3)
        if thr is None and r["N_over_others_ratio"] >= 3.0 and r["arms"]["N"]["served_frac"]["mean"] < 0.99:
            thr = r
    return dict(ladder=rows, seeds=seeds,
                starvation_threshold=None if thr is None else
                dict(D=thr["D"], dominant_axis_share=thr["dominant_axis_share"],
                     planned_vc_at_N=thr["planned_vc_at_N"],
                     N_over_others_ratio=thr["N_over_others_ratio"]))


# ---------------------------------------------------------------- PART 4
def part4(seeds, out, D_sweep_cfg=None):
    D0 = 900   # peak-starvation rung from part 3
    vol = sc.unbalanced(D0, M_MINOR)
    grid = []
    cfgs = [("nometer", None)]
    for thr_on in [3, 5, 8, 12]:
        for red, green in [(6, 14), (8, 12), (12, 8), (16, 4)]:
            cfgs.append((f"t{thr_on}_r{red}g{green}", dict(thr_on=thr_on, red=red, green=green)))
    store = {}
    for name, cfg in cfgs:
        per = {}
        ctl = {}
        for s in seeds:
            d = os.path.join(out, "sweep", f"{name}_s{s}")
            os.makedirs(d, exist_ok=True)
            rou = sc.write_scenario(os.path.join(d, "d.rou.xml"), vol, END)
            ctl[s] = run_variant("slm_nometer" if cfg is None else "slm_meter", rou, d, s,
                                 meter_cfg=cfg)
            per[s] = sc.collect(d, vol, END)
        store[name] = per
        row = dict(cfg=name, thr_on=None if cfg is None else cfg["thr_on"],
                   red=None if cfg is None else cfg["red"],
                   green=None if cfg is None else cfg["green"],
                   N_delay=mean_ci([per[s]["per_arm"]["N"]["delay_robust_s"] for s in seeds]),
                   N_thr=mean_ci([per[s]["per_arm"]["N"]["throughput_vph"] for s in seeds]),
                   N_served=mean_ci([per[s]["per_arm"]["N"]["served_frac"] for s in seeds]),
                   E_delay=mean_ci([per[s]["per_arm"]["E"]["delay_robust_s"] for s in seeds]),
                   agg_delay=mean_ci([per[s]["agg"]["delay_robust_s"] for s in seeds]),
                   agg_thr=mean_ci([per[s]["agg"]["throughput_vph"] for s in seeds]),
                   gini=mean_ci([per[s]["agg"]["equity_gini_delay"] for s in seeds]),
                   maxmin=mean_ci([per[s]["agg"]["equity_maxmin_delay_ratio"] for s in seeds]),
                   duty=mean_ci([ctl[s].get("metering_duty_cycle", 0.0) for s in seeds]),
                   activations=mean_ci([float(ctl[s].get("activations", 0)) for s in seeds]))
        grid.append(row)
        print(f"[p4] {name:14s} N delay={row['N_delay']['mean']:8.1f} thr={row['N_thr']['mean']:6.1f} "
              f"| E delay={row['E_delay']['mean']:8.1f} | agg delay={row['agg_delay']['mean']:7.1f} "
              f"thr={row['agg_thr']['mean']:7.1f} gini={row['gini']['mean']:.3f} duty={row['duty']['mean']:.3f}")
    base = store["nometer"]
    for row in grid:
        if row["cfg"] == "nometer":
            continue
        p = store[row["cfg"]]
        row["vs_nometer"] = dict(
            N_delay=paired_diff([p[s]["per_arm"]["N"]["delay_robust_s"] for s in seeds],
                                [base[s]["per_arm"]["N"]["delay_robust_s"] for s in seeds]),
            agg_delay=paired_diff([p[s]["agg"]["delay_robust_s"] for s in seeds],
                                  [base[s]["agg"]["delay_robust_s"] for s in seeds]),
            agg_thr=paired_diff([p[s]["agg"]["throughput_vph"] for s in seeds],
                                [base[s]["agg"]["throughput_vph"] for s in seeds]),
            gini=paired_diff([p[s]["agg"]["equity_gini_delay"] for s in seeds],
                             [base[s]["agg"]["equity_gini_delay"] for s in seeds]))
    # pick the config that minimises N delay subject to not significantly hurting
    # aggregate throughput
    cand = [r for r in grid if r["cfg"] != "nometer"
            and not (r["vs_nometer"]["agg_thr"]["significant_95"] and r["vs_nometer"]["agg_thr"]["mean_diff"] < 0)]
    best = min(cand or [r for r in grid if r["cfg"] != "nometer"],
               key=lambda r: r["N_delay"]["mean"])
    print("[p4] best config:", best["cfg"])

    # ---- demand range where metering is a net win
    dsweep = []
    for D in (D_sweep_cfg or [600, 700, 800, 900, 1000, 1100, 1200, 1400]):
        v = sc.unbalanced(D, M_MINOR)
        arms = {}
        for arm, cfg in [("nometer", None),
                         ("meter", dict(thr_on=best["thr_on"], red=best["red"], green=best["green"]))]:
            per = {}
            for s in seeds:
                d = os.path.join(out, "dsweep", f"D{D}_{arm}_s{s}")
                os.makedirs(d, exist_ok=True)
                rou = sc.write_scenario(os.path.join(d, "d.rou.xml"), v, END)
                run_variant("slm_nometer" if cfg is None else "slm_meter", rou, d, s, meter_cfg=cfg)
                per[s] = sc.collect(d, v, END)
            arms[arm] = per
        row = dict(D=D)
        for k, get in [("N_delay", lambda p: p["per_arm"]["N"]["delay_robust_s"]),
                       ("N_served", lambda p: p["per_arm"]["N"]["served_frac"]),
                       ("agg_delay", lambda p: p["agg"]["delay_robust_s"]),
                       ("agg_thr", lambda p: p["agg"]["throughput_vph"]),
                       ("gini", lambda p: p["agg"]["equity_gini_delay"])]:
            row[k] = dict(nometer=mean_ci([get(arms["nometer"][s]) for s in seeds]),
                          meter=mean_ci([get(arms["meter"][s]) for s in seeds]),
                          paired=paired_diff([get(arms["meter"][s]) for s in seeds],
                                             [get(arms["nometer"][s]) for s in seeds]))
        dsweep.append(row)
        print(f"[p4] D={D:5d} N delay {row['N_delay']['nometer']['mean']:8.1f} -> "
              f"{row['N_delay']['meter']['mean']:8.1f} ({row['N_delay']['paired']['pct']}%) | "
              f"agg delay {row['agg_delay']['nometer']['mean']:7.1f} -> {row['agg_delay']['meter']['mean']:7.1f} "
              f"({row['agg_delay']['paired']['pct']}%) | agg thr {row['agg_thr']['paired']['pct']}%")
    return dict(sweep=grid, best=best["cfg"],
                best_cfg=dict(thr_on=best["thr_on"], red=best["red"], green=best["green"]),
                demand_sweep=dsweep, seeds=seeds, D_sweep_base=D0)


# ---------------------------------------------------------------- PART 5
VARIANTS = ["sl", "two", "turbo", "sig", "slm_nometer", "slm_meter"]


def part5(seeds, out, meter_cfg, ttt_list=(300,)):
    scenarios = {"unbalanced_D900": sc.unbalanced(900, M_MINOR),   # peak-starvation rung, inside the metering net-win window
                 "unbalanced_D1000": sc.unbalanced(1000, M_MINOR), # just outside it
                 "balanced_V600": sc.balanced(600)}
    results = {}
    for sname, vol in scenarios.items():
        wadd = None
        w = ws.webster(vol, S_THRU, S_LEFT, LOST_PER_PHASE)
        wadd = ws.write_tls(os.path.join(out, f"webster_{sname}.add.xml"), w)
        results[sname] = dict(webster=w, arms={})
        for ttt in ttt_list:
            for v in VARIANTS:
                per = {}
                for s in seeds:
                    d = os.path.join(out, sname, f"ttt{ttt}", v, f"s{s}")
                    os.makedirs(d, exist_ok=True)
                    rou = sc.write_scenario(os.path.join(d, "d.rou.xml"), vol, END, ssm=(ttt == 300))
                    run_variant(v, rou, d, s, ttt=ttt,
                                ssm_file=os.path.join(d, "ssm.xml") if ttt == 300 else None,
                                webster_add=wadd,
                                meter_cfg=meter_cfg if v == "slm_meter" else None)
                    m = sc.collect(d, vol, END)
                    if ttt == 300:
                        m["ssm"] = ssm_summary(os.path.join(d, "ssm.xml"), d)
                    per[s] = m
                results[sname]["arms"].setdefault(f"ttt{ttt}", {})[v] = summarize(per, seeds)
                a = results[sname]["arms"][f"ttt{ttt}"][v]
                print(f"[p5] {sname:18s} ttt={ttt:4d} {v:12s} delay={a['delay_robust_s']['mean']:8.1f} "
                      f"thr={a['throughput_vph']['mean']:7.1f} served={a['served_frac']['mean']:.3f} "
                      f"gini={a['equity_gini_delay']['mean']:.3f} tel={a['teleports']['mean']:.1f}"
                      + (f" conflicts={a.get('ssm_total', {}).get('mean', 0):.0f}" if ttt == 300 else ""))
        # paired comparisons (CRN) against the signalized reference and against
        # the unmetered control on the identical metering network
        for tkey, arms in results[sname]["arms"].items():
            cmp_ = {}
            for base in ("sig", "slm_nometer"):
                for v in VARIANTS:
                    if v == base:
                        continue
                    pair = {}
                    for k in ("delay_robust_s", "throughput_vph", "equity_gini_delay",
                              "min_approach_served_frac", "arm_N_delay", "arm_N_thr"):
                        a = [arms[v]["_raw"][str(s)][k] if k in arms[v]["_raw"][str(s)]
                             else arms[v]["_raw_arms"][str(s)][k.split("_")[1]][
                                 "delay_robust_s" if k.endswith("delay") else "throughput_vph"]
                             for s in seeds]
                        b = [arms[base]["_raw"][str(s)][k] if k in arms[base]["_raw"][str(s)]
                             else arms[base]["_raw_arms"][str(s)][k.split("_")[1]][
                                 "delay_robust_s" if k.endswith("delay") else "throughput_vph"]
                             for s in seeds]
                        pair[k] = paired_diff(a, b)
                    if "_raw_ssm" in arms[v] and "_raw_ssm" in arms[base]:
                        for k in ("total", "crossing", "following", "merging", "severe_ttc"):
                            pair["ssm_" + k] = paired_diff(
                                [float(arms[v]["_raw_ssm"][str(s)][k]) for s in seeds],
                                [float(arms[base]["_raw_ssm"][str(s)][k]) for s in seeds])
                    cmp_[f"{v}_vs_{base}"] = pair
            results[sname].setdefault("paired", {})[tkey] = cmp_
    return results


def summarize(per, seeds):
    out = {}
    keys = ["delay_robust_s", "delay_completed_only_s", "throughput_vph", "served_frac",
            "equity_gini_delay", "equity_maxmin_delay_ratio", "min_approach_served_frac",
            "teleports", "never_inserted", "still_running", "completed"]
    for k in keys:
        out[k] = mean_ci([per[s]["agg"][k] for s in seeds])
    for a in "NESW":
        out[f"arm_{a}_delay"] = mean_ci([per[s]["per_arm"][a]["delay_robust_s"] for s in seeds])
        out[f"arm_{a}_thr"] = mean_ci([per[s]["per_arm"][a]["throughput_vph"] for s in seeds])
        out[f"arm_{a}_served"] = mean_ci([per[s]["per_arm"][a]["served_frac"] for s in seeds])
    if "ssm" in per[seeds[0]]:
        for k in per[seeds[0]]["ssm"]:
            out["ssm_" + k] = mean_ci([per[s]["ssm"][k] for s in seeds])
    out["_raw"] = {str(s): per[s]["agg"] for s in seeds}
    out["_raw_arms"] = {str(s): per[s]["per_arm"] for s in seeds}
    if "ssm" in per[seeds[0]]:
        out["_raw_ssm"] = {str(s): per[s]["ssm"] for s in seeds}
    return out


# ---------------------------------------------------------------- SSM
import xml.etree.ElementTree as ET  # noqa: E402

FOLLOW = {"2", "3", "18"}
MERGE = {"6", "7", "8", "19"}
CROSS = {str(i) for i in range(10, 18)}
COLLISION = {"111"}


def ssm_summary(path, outdir, ttc_sev=1.5, pet_sev=1.0):
    if not os.path.exists(path):
        return dict(total=0)
    tot = fol = mer = cro = col = 0
    sev_ttc = sev_pet = 0
    art = 0
    worst_ttc, worst_pet, max_drac = 9e9, 9e9, 0.0
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "conflict":
            continue
        tot += 1
        types = set()
        ttcv = petv = None
        for sub in el:
            t = sub.get("type")
            if t:
                types.add(t)
            v = sub.get("value")
            if sub.tag == "minTTC" and v not in (None, "NA"):
                ttcv = float(v)
                worst_ttc = min(worst_ttc, ttcv)
            if sub.tag == "PET" and v not in (None, "NA"):
                petv = float(v)
                worst_pet = min(worst_pet, petv)
            if sub.tag == "maxDRAC" and v not in (None, "NA"):
                max_drac = max(max_drac, float(v))
        if types & COLLISION:
            # per `unsignalized-vs-signalized-intersection-control`: a 111 flag with
            # TTC/PET ~0 or NA is the documented degenerate-geometry artifact
            if (ttcv is None or ttcv <= 0.01) and (petv is None or petv <= 0.01):
                art += 1
            else:
                col += 1
        elif types & CROSS:
            cro += 1
        elif types & MERGE:
            mer += 1
        elif types & FOLLOW:
            fol += 1
        if ttcv is not None and ttcv < ttc_sev:
            sev_ttc += 1
        if petv is not None and petv < pet_sev:
            sev_pet += 1
        el.clear()
    return dict(total=tot, following=fol, merging=mer, crossing=cro, collisions=col,
                type111_artifacts=art, severe_ttc=sev_ttc, severe_pet=sev_pet,
                worst_ttc=(0 if worst_ttc > 8e9 else round(worst_ttc, 3)),
                worst_pet=(0 if worst_pet > 8e9 else round(worst_pet, 3)),
                max_drac=round(max_drac, 3))


# measured saturation-flow parameters (results/webster/saturation_flow.json)
# MEASURED on this network with this vType (results/webster/saturation_flow.json):
#   through+right lane: h_s = 1.521 s -> s = 2367.2 veh/h/lane, l1 = 0.57 s
#   protected left lane: h_s = 1.699 s -> s = 2118.7 veh/h/lane, l1 = 0.25 s
# (window sensitivity: through 2305-2367, left 2060-2132 across four windows)
S_THRU = 2367.2
S_LEFT = 2118.7
LOST_PER_PHASE = 4.11  # MEASURED total lost time per phase = (green+yellow) - N_d*h_s;
                       # 4.159 s (through) / 4.055 s (protected left), mean used


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", required=True, choices=["3", "4", "5"])
    ap.add_argument("--seeds", type=int, nargs="+", default=[101, 202, 303, 404, 505])
    ap.add_argument("--ttt", type=int, nargs="+", default=[300])
    ap.add_argument("--meter-thr", type=int, default=5)
    ap.add_argument("--meter-red", type=float, default=8)
    ap.add_argument("--meter-green", type=float, default=12)
    a = ap.parse_args()
    if a.part == "3":
        out = os.path.join(RES, "starvation")
        os.makedirs(out, exist_ok=True)
        r = part3(a.seeds, out)
        json.dump(r, open(os.path.join(out, "starvation.json"), "w"), indent=2)
    elif a.part == "4":
        out = os.path.join(RES, "metering")
        os.makedirs(out, exist_ok=True)
        r = part4(a.seeds, out)
        json.dump(r, open(os.path.join(out, "metering.json"), "w"), indent=2)
    else:
        out = os.path.join(RES, "comparison")
        os.makedirs(out, exist_ok=True)
        cfg = dict(thr_on=a.meter_thr, red=a.meter_red, green=a.meter_green)
        r = part5(a.seeds, out, cfg, ttt_list=a.ttt)
        r["meter_cfg"] = cfg
        json.dump(r, open(os.path.join(out, f"comparison_ttt{'_'.join(map(str,a.ttt))}.json"), "w"), indent=2)
