#!/usr/bin/env python3
"""
Build the signal plans for the driveway intersection from MEASURED saturation
flow and MEASURED net lost time (calibration/saturation_flow.json), using
Webster's method implemented explicitly:

    y_i   = q_i / (N_i * s_i)                critical flow ratio of phase i
    L     = SUM_i (Y_i + AR_i) + SUM_i l_net,i
    Y     = SUM_i y_i
    C_opt = (1.5 L + 5) / (1 - Y)
    g_eff,i  = (C - L) * y_i / Y
    g_disp,i = g_eff,i + l_net,i

Phasing (protected-only, 3 phases; link indices read off the compiled net):
    phi1  major protected LEFTS      links 6 (WBL), 13 (EBL)
    phi2  major THROUGH + RIGHT      links 3,4,5 (WB) and 10,11,12 (EB)
    phi3  minor street + DRIVEWAY    links 0,1,2 (DW) and 7,8,9 (MN)

Two plans per demand scenario:
    <scen>_fixed  static, timed for the PM peak DESIGN HOUR (17:00-18:00)
    <scen>_act    type="actuated", same phase skeleton, custom-placed E1
                  detection bound per lane via <param key="<laneID>" .../>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CAL, SCEN, write

SIG = os.path.join(SCEN, "signal")
os.makedirs(SIG, exist_ok=True)

NLINK = 14
PHASES = [
    ("phi1_major_left", [6, 13]),
    ("phi2_major_thru", [3, 4, 5, 10, 11, 12]),
    ("phi3_minor",      [0, 1, 2, 7, 8, 9]),
]
YELLOW, ALLRED = 3, 2
MIN_GREEN = 7
C_MIN, C_MAX = 40, 120
DESIGN_HOUR = 10          # 17:00-18:00

# custom actuated detector setback from the stop bar (m) and the lane it sits on
ACT_DETECTORS = {
    "maj_W_bay_0": 45.0, "maj_W_bay_1": 45.0, "maj_W_bay_2": 45.0,
    "maj_E_bay_0": 45.0, "maj_E_bay_1": 45.0, "maj_E_bay_2": 45.0,
    "drw_N_in_0": 20.0, "min_S_in_0": 20.0,
}
LANE_LEN = {"maj_W_bay_0": 100.0, "maj_W_bay_1": 100.0, "maj_W_bay_2": 100.0,
            "maj_E_bay_0": 100.0, "maj_E_bay_1": 100.0, "maj_E_bay_2": 100.0,
            "drw_N_in_0": 250.0, "min_S_in_0": 250.0}


def load_saturation(step="step_0.5"):
    j = json.load(open(os.path.join(CAL, "saturation_flow.json")))[step]
    return {k: {"s": v["regression"]["s_veh_per_h_per_lane"],
                "l_net": v["regression"]["l_net_s"],
                "r2": v["regression"]["r2"]} for k, v in j.items()}


def critical_ratios(mv, sat):
    """mv: movement -> veh/h for the design hour."""
    s_thru = sat["major_through"]["s"]
    s_left = sat["major_left_bay"]["s"]
    s_drw = sat["driveway"]["s"]
    s_min = sat["minor_street"]["s"]
    y1 = max(mv["EBL"], mv["WBL"]) / (1 * s_left)
    eb_tr = (mv["EBT"] + mv["EBR"]) / 2.0
    wb_tr = (mv["WBT"] + mv["WBR"]) / 2.0
    y2 = max(eb_tr, wb_tr) / s_thru
    y3 = max((mv["DWL"] + mv["DWR"]) / s_drw, (mv["SBL"] + mv["SBR"]) / s_min)
    l = [sat["major_left_bay"]["l_net"], sat["major_through"]["l_net"],
         sat["driveway"]["l_net"]]
    detail = {"y1_major_left": y1, "y2_major_through": y2, "y3_minor": y3,
              "critical_left_vph": max(mv["EBL"], mv["WBL"]),
              "critical_thru_vph_per_lane": max(eb_tr, wb_tr),
              "critical_minor_vph": max(mv["DWL"] + mv["DWR"], mv["SBL"] + mv["SBR"]),
              "s_left": s_left, "s_thru": s_thru,
              "s_minor": max(s_drw, s_min) if (mv["DWL"] + mv["DWR"]) >
              (mv["SBL"] + mv["SBR"]) else s_min}
    return [y1, y2, y3], l, detail


def webster(mv, sat):
    ys, lnet, detail = critical_ratios(mv, sat)
    Y = sum(ys)
    L = 3 * (YELLOW + ALLRED) + sum(lnet)
    if Y >= 1.0:
        C = C_MAX
        note = "Y>=1: Webster undefined, cycle clamped to C_MAX"
    else:
        C = (1.5 * L + 5) / (1 - Y)
        note = ""
    C_raw = C
    C = max(C_MIN, min(C_MAX, round(C)))
    g_eff = [(C - L) * y / Y for y in ys]
    g_disp = [max(MIN_GREEN, round(ge + ln)) for ge, ln in zip(g_eff, lnet)]
    # renormalise so the displayed greens + intergreens hit exactly C
    slack = C - (sum(g_disp) + 3 * (YELLOW + ALLRED))
    order = sorted(range(3), key=lambda i: -g_disp[i])
    i = 0
    while slack != 0:
        k = order[i % 3]
        if slack > 0:
            g_disp[k] += 1; slack -= 1
        elif g_disp[k] > MIN_GREEN:
            g_disp[k] -= 1; slack += 1
        else:
            i += 1
            if i > 30:
                break
            continue
        i += 1
    return {"y": ys, "Y": Y, "L_s": L, "l_net": lnet, "C_opt_raw_s": C_raw,
            "C_s": C, "g_eff_s": g_eff, "g_displayed_s": g_disp,
            "yellow_s": YELLOW, "allred_s": ALLRED, "note": note, "detail": detail}


def state(idx, ch):
    return "".join(ch if i in idx else "r" for i in range(NLINK))


def tls_block(prog_id, plan, actuated):
    x = [f'  <tlLogic id="C" type="{"actuated" if actuated else "static"}" '
         f'programID="{prog_id}" offset="0">']
    if actuated:
        x.append('    <param key="max-gap" value="3.0"/>')
        x.append('    <param key="passing-time" value="2.0"/>')
        x.append('    <param key="detector-gap" value="2.0"/>')
        for lane in ACT_DETECTORS:
            x.append(f'    <param key="{lane}" value="act_{lane}"/>')
    for (pname, idx), g in zip(PHASES, plan["g_displayed_s"]):
        if actuated:
            mn = max(5, int(round(0.45 * g)))
            mx = int(round(min(70, max(g * 1.8, g + 15))))
            x.append(f'    <phase duration="{g}" minDur="{mn}" maxDur="{mx}" '
                     f'state="{state(idx, "G")}" name="{pname}"/>')
        else:
            x.append(f'    <phase duration="{g}" state="{state(idx, "G")}" name="{pname}"/>')
        x.append(f'    <phase duration="{YELLOW}" state="{state(idx, "y")}"/>')
        x.append(f'    <phase duration="{ALLRED}" state="{"r" * NLINK}"/>')
    x.append("  </tlLogic>")
    return x


def act_detector_block(misplaced=False):
    """misplaced=True moves every actuated detector to 5 m from the START of its
    lane -- as far upstream as the lane allows.  Used only to VERIFY that the
    <param key="<laneID>" value="<detID>"/> binding genuinely took effect: an
    unrecognised param key is silently ignored by SUMO, so the absence of an
    error proves nothing (control-signals-with-actuated-tls)."""
    x = []
    for lane, back in ACT_DETECTORS.items():
        pos = 5.0 if misplaced else LANE_LEN[lane] - back
        x.append(f'  <inductionLoop id="act_{lane}" lane="{lane}" pos="{pos:.1f}" '
                 f'period="100000" file="act_det.xml"/>')
    return x


def write_plan(scen, plan, actuated, misplaced=False, suffix=""):
    prog = "tia"
    x = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>"]
    if actuated:
        x += act_detector_block(misplaced)
    x += tls_block(prog, plan, actuated)
    x += [f'  <WAUT id="w" refTime="0" startProg="{prog}"/>',
          '  <wautJunction wautID="w" junctionID="C" procedure="Immediate"/>',
          "</additional>"]
    name = f"{scen}_{'act' if actuated else 'fixed'}{suffix}.add.xml"
    p = os.path.join(SIG, name)
    write(p, "\n".join(x) + "\n")
    return p


def main():
    sat = load_saturation("step_0.1")   # finer resolution; actionStepLength is pinned
    sat_cross = load_saturation("step_0.5")
    man = json.load(open(os.path.join(SCEN, "demand", "demand_manifest.json")))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gen_demand as gd

    out = {"saturation_used": sat, "saturation_crosscheck_step_0.5": sat_cross, "design_hour": man["scenarios"]["build"]["hourly"][DESIGN_HOUR]["hour"],
           "plans": {}}
    print("Measured inputs (step_0.1 calibration):")
    for k, v in sat.items():
        print(f"   {k:15s} s={v['s']:7.1f} veh/h/ln  l_net={v['l_net']:+5.2f} s  R2={v['r2']:.4f}")
    for scen in ("nobuild", "build", "build_high"):
        mv_by_hour, _ = gd.hourly_movements(gd.SCENARIOS[scen])
        mv = mv_by_hour[DESIGN_HOUR]
        plan = webster(mv, sat)
        out["plans"][scen] = {"design_hour_movements": {k: round(v, 1) for k, v in mv.items()},
                              "webster": plan}
        write_plan(scen, plan, False)
        write_plan(scen, plan, True)
        write_plan(scen, plan, True, misplaced=True, suffix="_MISPLACED")  # binding check
        print(f"\n[signal] {scen}: Y={plan['Y']:.4f} L={plan['L_s']:.2f}s "
              f"C_opt={plan['C_opt_raw_s']:.1f}s -> C={plan['C_s']}s")
        for (pname, _), ge, gd_ in zip(PHASES, plan["g_eff_s"], plan["g_displayed_s"]):
            print(f"          {pname:16s} g_eff={ge:5.1f}s  g_displayed={gd_:3d}s")
        print(f"          y = {[round(v,4) for v in plan['y']]}")
    write(os.path.join(SIG, "signal_design.json"), json.dumps(out, indent=2))
    print("\n[signal] wrote", os.path.join(SIG, "signal_design.json"))


if __name__ == "__main__":
    main()
