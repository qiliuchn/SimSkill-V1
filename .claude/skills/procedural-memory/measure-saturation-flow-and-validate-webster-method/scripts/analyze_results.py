#!/usr/bin/env python3
"""Builds every final table/CSV deliverable and runs the head-to-head against
tlsCycleAdaptation.py's own plans.

Writes into outputs/:
  table1_headway_vs_queue_position.csv   mean h_n by queue position, all vTypes
  table2_saturation_by_vtype.csv         measured s / l1 / l2 per vType + refs
  table3_webster_vs_sim_sweep.csv        per level & cycle: Webster d(C) vs sim
  table4_tool_comparison.csv             tlsCycleAdaptation vs measured-Webster
                                         vs brute-force optimum
  raw_e1_leave_times_base_g32.csv        every rear-bumper stop-line crossing of
                                         the base run, with cycle & queue index
                                         (this is what the critic re-derives from)
  tls_all_cycles.add.xml                 every tlLogic used in the sweep
"""
import os
import sys
import csv
import json
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WORK, OUT, NET, YELLOW, ALLRED, tls_xml, STEP_LENGTH, run_sumo
from webster import WebsterDesign
import measure_saturation as MS
import run_sweep as RS

TOOL_H = 2.0                     # tlsCycleAdaptation.py -H default (s)
TOOL_S = 3600.0 / TOOL_H         # 1800 veh/h/lane
TEXTBOOK_S = 1900.0              # classic HCM-ish assumption


def w(name):
    return os.path.join(OUT, name)


# --------------------------------------------------------------- table 1 ---
def table1(sat):
    vts = list(sat)
    maxn = max(max(int(k) for k in sat[v]["headway"]["mean_headway_by_n"]) for v in vts)
    with open(w("table1_headway_vs_queue_position.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["queue_position_n"] + ["h_n_%s" % v for v in vts]
                    + ["n_cycles_%s" % v for v in vts])
        for n in range(1, maxn + 1):
            row = [n]
            for v in vts:
                row.append(sat[v]["headway"]["mean_headway_by_n"].get(str(n), ""))
            for v in vts:
                row.append(sat[v]["headway"]["n_obs_by_n"].get(str(n), ""))
            wr.writerow(row)


# --------------------------------------------------------------- table 2 ---
def table2(sat):
    with open(w("table2_saturation_by_vtype.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["vType", "tau_s", "accel_mps2", "minGap_m", "length_m",
                     "h_s_regression_s", "s_regression_vphpl",
                     "l1_regression_s", "l2_regression_s", "L_per_phase_s", "R2",
                     "h_s_headway_s", "s_headway_vphpl", "l1_headway_s",
                     "h_s_sd_s", "n_headway_obs", "n_cycles",
                     "ratio_s_over_1900", "ratio_s_over_tool1800",
                     "implied_discharge_speed_mps"])
        for v, r in sat.items():
            p = r["params"]
            rg = r["regression"]
            hw = r["headway"]
            # h_s = tau + (length+minGap)/v_d  ->  v_d = (length+minGap)/(h_s - tau)
            vd = (p["length"] + p["minGap"]) / (rg["h_s"] - p["tau"])
            wr.writerow([v, p["tau"], p["accel"], p["minGap"], p["length"],
                         round(rg["h_s"], 4), round(rg["s"], 1),
                         round(rg["l1"], 3), round(rg["l2"], 3),
                         round(rg["L_per_phase"], 3), round(rg["r2"], 6),
                         round(hw["h_s"], 4), round(hw["s"], 1), round(hw["l1"], 3),
                         round(hw["h_s_sd"], 4), hw["h_s_nobs"], hw["cycles_used"],
                         round(rg["s"] / TEXTBOOK_S, 4),
                         round(rg["s"] / TOOL_S, 4), round(vd, 2)])


# --------------------------------------------------------------- table 3 ---
def flatness(cs, vals, frac):
    best = min(vals)
    ok = [c for c, v in zip(cs, vals) if v <= (1 + frac) * best]
    return min(ok), max(ok), len(ok)


def table3(sw):
    rows = []
    summary = {}
    with open(w("table3_webster_vs_sim_sweep.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["level", "Y", "cycle_s", "g_disp_NS_s", "g_disp_EW_s",
                     "g_eff_NS_s", "g_eff_EW_s", "x_NS", "x_EW",
                     "webster_delay_s", "sim_mean_timeLoss_s",
                     "sim_mean_waitingTime_s", "sim_mean_duration_s",
                     "arrived", "loaded", "not_inserted", "still_running",
                     "teleports"])
        for lvl in ("under", "critical", "over"):
            L = sw["levels"][lvl]
            cs = sorted(int(c) for c in L["sim"])
            sim = [L["sim"][str(c)]["mean_timeLoss"] for c in cs]
            for c in cs:
                web = L["webster"][str(c)]
                s = L["sim"][str(c)]
                wr.writerow([lvl, round(L["Y"], 4), c,
                             s["g_disp"][0], s["g_disp"][1],
                             web["g_eff"][0], web["g_eff"][1],
                             web["x"][0], web["x"][1],
                             "" if web["delay"] is None else round(web["delay"], 3),
                             round(s["mean_timeLoss"], 3),
                             round(s["mean_waitingTime"], 3),
                             round(s["mean_duration"], 3),
                             s["arrived"], s["loaded"], s["not_inserted"],
                             s["running"], s["teleports"]])
            bi = min(range(len(cs)), key=lambda i: sim[i])
            b5 = flatness(cs, sim, 0.05)
            b10 = flatness(cs, sim, 0.10)
            wcs = [c for c in cs if L["webster"][str(c)]["delay"] is not None]
            wv = [L["webster"][str(c)]["delay"] for c in wcs]
            wopt = wcs[min(range(len(wv)), key=lambda i: wv[i])] if wv else None
            summary[lvl] = dict(Y=L["Y"], C_opt_webster=L["C_opt"],
                                C_argmin_webster_curve=wopt,
                                C_opt_sim=cs[bi], min_sim_delay=sim[bi],
                                band5=b5, band10=b10,
                                sim_delay_at_webster_Copt=None)
            if L["C_opt"]:
                near = min(cs, key=lambda c: abs(c - L["C_opt"]))
                summary[lvl]["nearest_grid_C_to_Copt"] = near
                summary[lvl]["sim_delay_at_webster_Copt"] = L["sim"][str(near)]["mean_timeLoss"]
    return summary


# --------------------------------------------------------------- table 4 ---
TOOL_PLANS = {}      # filled by run_tool_plans


def run_tool_plans(sw):
    """Run tlsCycleAdaptation.py's own output plans under identical demand."""
    tooldir = os.path.join(WORK, "tool")
    res = {}
    for lvl in ("under", "critical", "over"):
        add = os.path.join(tooldir, "tls_%s.add.xml" % lvl)
        durs = [float(p.get("duration")) for p in
                ET.parse(add).getroot().iter("phase")]
        C = sum(durs)
        od = os.path.join(WORK, "sweep", "toolplan_%s" % lvl)
        os.makedirs(od, exist_ok=True)
        tls = os.path.join(od, "tls.add.xml")
        with open(tls, "w") as f:
            f.write(tls_xml(durs[0], durs[2], program="tool"))
        run_sumo(["-n", NET, "-r", sw["levels"][lvl]["demand_file"], "-a", tls,
                  "--begin", "0", "--end", str(RS.SIM_END),
                  "--step-length", str(STEP_LENGTH), "--seed", str(RS.SEED),
                  "--time-to-teleport", "600", "--no-step-log", "true",
                  "--xml-validation", "never",
                  "--tripinfo-output", os.path.join(od, "tripinfo.xml"),
                  "--summary-output", os.path.join(od, "summary.xml")], "tool-" + lvl)
        r = RS.parse_run(od, [durs[0], durs[2]])
        r["cycle"] = C
        res[lvl] = r
    return res


def table4(sw, summ, tool):
    exact = json.load(open(os.path.join(WORK, "exact_copt_runs.json")))
    # tool's own Y, read from its verbose log
    tool_Y = {}
    for lvl in ("under", "critical", "over"):
        for line in open(os.path.join(WORK, "tool", "log_%s.txt" % lvl)):
            if "critical flow" in line:
                tool_Y[lvl] = float(line.strip().split(":")[-1])
    with open(w("table4_tool_comparison.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["level", "Y_measured_s2191", "Y_tlsCycleAdaptation_s1800",
                     "C_opt_measured_webster_s", "C_opt_tlsCycleAdaptation_s",
                     "C_opt_bruteforce_sim_s",
                     "sim_delay_at_exact_measured_Copt_s", "sim_delay_tool_plan_s",
                     "sim_delay_at_bruteforce_opt_s",
                     "tool_penalty_vs_bruteforce_pct",
                     "measuredWebster_penalty_vs_bruteforce_pct",
                     "band_within5pct_s", "band_within10pct_s"])
        for lvl in ("under", "critical", "over"):
            S = summ[lvl]
            best = S["min_sim_delay"]
            td = tool[lvl]["mean_timeLoss"]
            md = exact[lvl]["mean_timeLoss"] if lvl in exact else None
            wr.writerow([lvl, round(S["Y"], 4), round(tool_Y.get(lvl, float("nan")), 4),
                         "" if S["C_opt_webster"] is None else round(S["C_opt_webster"], 1),
                         tool[lvl]["cycle"], S["C_opt_sim"],
                         "" if md is None else round(md, 2), round(td, 2),
                         round(best, 2),
                         round(100 * (td - best) / best, 1),
                         "" if md is None else round(100 * (md - best) / best, 1),
                         "%d-%d" % (S["band5"][0], S["band5"][1]),
                         "%d-%d" % (S["band10"][0], S["band10"][1])])
    return tool_Y


# ------------------------------------------------------- raw E1 extract ----
def raw_e1(sat):
    """The exact per-vehicle stop-line crossings the base h_s/l1 came from."""
    od = os.path.join(WORK, "measure", "base_g%g" % MS.G_HEADWAY)
    times = MS.parse_leave_times(os.path.join(od, "instant_N.xml"))
    cyc, C = MS.per_cycle(times, MS.G_HEADWAY)
    with open(w("raw_e1_leave_times_base_g32.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["green_onset_s", "queue_position_n", "t_leave_s",
                     "headway_s", "cycle_length_s", "green_s"])
        for t0, win in cyc:
            prev = t0
            for n, t in enumerate(win, 1):
                wr.writerow([round(t0, 2), n, round(t, 2), round(t - prev, 3),
                             C, MS.G_HEADWAY])
                prev = t
    return len(cyc), C


# ------------------------------------------------------- tlLogic bundle ----
def tls_bundle(sw):
    with open(w("tls_all_cycles.add.xml"), "w") as f:
        f.write("<!-- every fixed-time plan used in the cycle-length sweep.\n"
                "     programID = <level>_C<cycle>.  Phase order:\n"
                "     NS-through green, NS yellow, EW-through green, EW yellow. -->\n")
        f.write("<additional>\n")
        from common import S_NS_G, S_NS_Y, S_EW_G, S_EW_Y
        for lvl in ("under", "critical", "over"):
            for c in sorted(int(x) for x in sw["levels"][lvl]["sim"]):
                g = sw["levels"][lvl]["sim"][str(c)]["g_disp"]
                g0 = round(g[0], 1)
                g1 = round(c - 2 * (YELLOW + ALLRED) - g0, 1)
                f.write('  <tlLogic id="center" type="static" programID="%s_C%03d" '
                        'offset="0">\n' % (lvl, c))
                for d, st in ((g0, S_NS_G), (YELLOW, S_NS_Y),
                              (g1, S_EW_G), (YELLOW, S_EW_Y)):
                    f.write('    <phase duration="%g" state="%s"/>\n' % (d, st))
                f.write('  </tlLogic>\n')
        f.write("</additional>\n")


def main():
    sat = json.load(open(os.path.join(WORK, "saturation_results.json")))
    sw = json.load(open(os.path.join(WORK, "sweep_results.json")))
    table1(sat)
    table2(sat)
    summ = table3(sw)
    ncyc, C = raw_e1(sat)
    tls_bundle(sw)
    print("raw E1 extract: %d cycles, cycle length %g s" % (ncyc, C))
    tool = run_tool_plans(sw)
    tool_Y = table4(sw, summ, tool)
    out = dict(summary=summ, tool_runs=tool, tool_Y=tool_Y)
    with open(os.path.join(WORK, "analysis_summary.json"), "w") as f:
        json.dump(out, f, indent=2)
    for lvl, S in summ.items():
        print("%-9s Y=%.3f  C_opt(Webster)=%s  C_opt(sim)=%d  best=%.2f s  "
              "5%%band=%d-%d  10%%band=%d-%d"
              % (lvl, S["Y"],
                 ("%.1f" % S["C_opt_webster"]) if S["C_opt_webster"] else "undef",
                 S["C_opt_sim"], S["min_sim_delay"],
                 S["band5"][0], S["band5"][1], S["band10"][0], S["band10"][1]))
    for lvl, t in tool.items():
        print("  tool plan %-9s C=%g  greens=%s  simTL=%.2f"
              % (lvl, t["cycle"], t["g_disp"], t["mean_timeLoss"]))


if __name__ == "__main__":
    main()
