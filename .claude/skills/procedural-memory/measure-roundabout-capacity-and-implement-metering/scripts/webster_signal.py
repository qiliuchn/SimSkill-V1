"""
Signalized reference: MEASURE the saturation flow / startup lost time of this
network's own vehicles, then size the signal with Webster's equations from the
same movement volumes used for every roundabout variant.

Follows `measure-saturation-flow-and-validate-webster-method`:
  * oversaturated approach served from a permanently standing queue
  * --step-length 0.1 (a 1 s step cannot resolve a ~1.8 s saturation headway)
  * departSpeed="max" (departSpeed=0 silently caps insertion at ~1500 veh/h/lane)
  * rear-bumper (state="leave") crossing convention on an instantInductionLoop
  * windowed headway-vs-queue-position estimator as PRIMARY (the fleet here has
    sigma=0.5 > 0, so the green-duration regression would also be usable; the
    windowed estimator is reported with its window sensitivity)
  * a laneAreaDetector with endPos clipped to the lane's own length verifies the
    standing queue never ran out
"""
import argparse
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import write_flows, run_sumo, vtype_xml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(HERE, "networks")

# link indices in sig.net.xml, verified by reading the compiled net:
LINK = {"N": dict(r=0, s=1, l=2), "E": dict(r=3, s=4, l=5),
        "S": dict(r=6, s=7, l=8), "W": dict(r=9, s=10, l=11)}
NLINKS = 12


def state(green_links, yellow_links=()):
    st = ["r"] * NLINKS
    for i in green_links:
        st[i] = "G"
    for i in yellow_links:
        st[i] = "y"
    return "".join(st)


def measure_saturation(outdir, green=30.0, red=30.0, cycles=30, movement="through"):
    """movement="through": N/S through+right green, demand N->S and S->N on lane 0.
       movement="left":    N/S PROTECTED left green,  demand N->E and S->W on lane 1.
    The left-turn saturation flow is MEASURED, not assumed at some fraction of the
    through value."""
    os.makedirs(outdir, exist_ok=True)
    if movement == "through":
        g_links = [LINK["N"]["s"], LINK["N"]["r"], LINK["S"]["s"], LINK["S"]["r"]]
        vol = {("N", "S"): 3600, ("S", "N"): 3600}
        lane = "in_N_0"
    else:
        g_links = [LINK["N"]["l"], LINK["S"]["l"]]
        vol = {("N", "E"): 3600, ("S", "W"): 3600}
        lane = "in_N_1"
    phases = [(green, state(g_links)), (3.0, state([], g_links)), (red, state([]))]
    tl = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>",
          '    <tlLogic id="C" type="static" programID="sat" offset="0">']
    for d, s in phases:
        tl.append(f'        <phase duration="{d}" state="{s}"/>')
    tl += ["    </tlLogic>",
           f'    <instantInductionLoop id="stop_N" lane="{lane}" pos="-1" friendlyPos="true" file="instant.xml"/>',
           f'    <laneAreaDetector id="q_N" lane="{lane}" pos="0" endPos="-1" friendlyPos="true" period="10" file="q.xml"/>',
           "</additional>"]
    addp = os.path.join(outdir, "sat.add.xml")
    open(addp, "w").write("\n".join(tl) + "\n")

    cyc = green + 3.0 + red
    end = cyc * cycles
    rou = write_flows(os.path.join(outdir, "d.rou.xml"), vol, 0, end, headway="uniform")
    r = run_sumo(os.path.join(NET, "sig.net.xml"), rou, outdir, end=end, seed=7, step=0.1,
                 ttt=-1, additional=[addp], tripinfo=False, summary=True)
    assert r.returncode == 0, r.stderr[:2000]

    # rear-bumper crossings at the stop line
    leaves = []
    for _, el in ET.iterparse(os.path.join(outdir, "instant.xml"), events=("end",)):
        if el.tag == "instantOut" and el.get("state") == "leave" and el.get("id") == "stop_N":
            leaves.append(float(el.get("time")))
            el.clear()
    leaves.sort()

    # group by green window, skipping the first 2 cycles as warm-up
    per_pos = {}
    used_cycles = 0
    per_green = []
    last_gap = []
    for c in range(2, cycles):
        t0 = c * cyc
        t1 = t0 + green + 3.0
        win = [t for t in leaves if t0 <= t < t1]
        if len(win) < 6:
            continue
        used_cycles += 1
        per_green.append(len(win))
        last_gap.append(t1 - win[-1])
        for n in range(1, len(win)):
            per_pos.setdefault(n + 1, []).append(win[n] - win[n - 1])
    h = {n: sum(v) / len(v) for n, v in sorted(per_pos.items()) if len(v) >= 5}

    # queue never emptied?
    jam = []
    for _, el in ET.iterparse(os.path.join(outdir, "q.xml"), events=("end",)):
        if el.tag == "interval" and float(el.get("begin")) > 2 * cyc:
            jam.append(float(el.get("maxJamLengthInVehicles", 0)))
            el.clear()

    def estimate(win_lo, win_hi):
        sel = [h[n] for n in h if win_lo <= n <= win_hi]
        if not sel:
            return None
        hs = sum(sel) / len(sel)
        s = 3600.0 / hs
        l1 = sum(h[n] - hs for n in h if n < win_lo)
        return dict(window=[win_lo, win_hi], h_s=round(hs, 4), s=round(s, 1), l1=round(l1, 3))

    est = [e for e in (estimate(4, 10), estimate(5, 12), estimate(3, 9), estimate(6, 14)) if e]
    # Saturation evidence: if the standing queue never ran out during green, the
    # LAST discharge of each green must be within ~one saturation headway of the
    # end of green (no idle tail), and vehicles-per-green must be ~ green/h_s.
    hs = est[0]["h_s"]
    return dict(headway_by_position={str(k): round(v, 4) for k, v in h.items()},
                cycles_used=used_cycles,
                veh_per_green_min=min(per_green), veh_per_green_mean=round(sum(per_green) / len(per_green), 2),
                expected_veh_per_green=round((green + 3.0) / hs, 2),
                idle_tail_s_max=round(max(last_gap), 3),
                saturated_throughout=bool(max(last_gap) < 2.0 * hs),
                lost_per_phase_s=round((green + 3.0) - (sum(per_green) / len(per_green)) * hs, 3),
                e2_min_jam_veh=(min(jam) if jam else -1),
                e2_mean_jam_veh=round(sum(jam) / len(jam), 2) if jam else -1,
                estimators=est, primary=est[0])


def webster(volumes, s_thru, s_left, lost_per_phase, yellow=3.0, cmin=40.0, cmax=140.0,
            min_green=5.0):
    """Webster's method on the 4 critical phase groups of the protected/permissive
    plan: NS through+right, NS protected left, EW through+right, EW protected left.

    `lost_per_phase` is the MEASURED total lost time per phase, obtained from the
    same saturation-flow rig as
        L_phase = (displayed green + yellow) - N_discharged * h_s
    i.e. it captures startup lost time AND the unused part of the yellow in one
    number, instead of the common shortcut of counting yellow as fully usable
    green (which here collapsed C_opt to ~18 s and produced a signal that served
    only 78% of demand -- a badly unfair reference).

    Permissive-left capacity during the through phase is deliberately IGNORED, so
    the sizing is conservative.
    """
    q = {}
    for a in ["N", "E", "S", "W"]:
        rt = {"N": "W", "W": "S", "S": "E", "E": "N"}[a]
        th = {"N": "S", "S": "N", "E": "W", "W": "E"}[a]
        lf = {"N": "E", "E": "S", "S": "W", "W": "N"}[a]
        q[a] = dict(right=volumes.get((a, rt), 0), through=volumes.get((a, th), 0),
                    left=volumes.get((a, lf), 0))
    groups = {
        "NS_thru": max((q["N"]["right"] + q["N"]["through"]) / s_thru,
                       (q["S"]["right"] + q["S"]["through"]) / s_thru),
        "NS_left": max(q["N"]["left"] / s_left, q["S"]["left"] / s_left),
        "EW_thru": max((q["E"]["right"] + q["E"]["through"]) / s_thru,
                       (q["W"]["right"] + q["W"]["through"]) / s_thru),
        "EW_left": max(q["E"]["left"] / s_left, q["W"]["left"] / s_left),
    }
    Y = sum(groups.values())
    L = 4.0 * lost_per_phase
    if Y >= 1.0:
        C = cmax
        note = f"Y={Y:.4f} >= 1 -> Webster C_opt undefined; using C=cmax={cmax}"
    else:
        Copt = (1.5 * L + 5.0) / (1.0 - Y)
        note = f"C_opt = (1.5*{L:.2f}+5)/(1-{Y:.4f}) = {Copt:.2f} s"
        C = max(cmin, min(cmax, Copt))
        if abs(C - Copt) > 1e-6:
            note += f" (clamped to [{cmin},{cmax}] -> {C:.2f})"
    geff = {k: (C - L) * v / Y for k, v in groups.items()} if Y > 0 else {k: (C - L) / 4 for k in groups}
    g = {k: max(min_green, v - yellow + lost_per_phase) for k, v in geff.items()}
    # renormalise so sum(G_i + yellow) == C exactly
    tot = sum(g.values()) + 4 * yellow
    if tot != C:
        sc_ = (C - 4 * yellow) / sum(g.values())
        g = {k: round(v * sc_, 1) for k, v in g.items()}
    return dict(flow_ratios={k: round(v, 5) for k, v in groups.items()}, Y=round(Y, 4),
                lost_per_phase=lost_per_phase, L=round(L, 3), C=round(C, 1),
                effective_greens={k: round(v, 2) for k, v in geff.items()},
                greens=g, yellow=yellow, note=note)


def write_tls(path, w):
    g = w["greens"]
    y = w["yellow"]
    ns_t = [LINK["N"]["r"], LINK["N"]["s"], LINK["S"]["r"], LINK["S"]["s"]]
    ns_l = [LINK["N"]["l"], LINK["S"]["l"]]
    ew_t = [LINK["E"]["r"], LINK["E"]["s"], LINK["W"]["r"], LINK["W"]["s"]]
    ew_l = [LINK["E"]["l"], LINK["W"]["l"]]
    seq = [(g["NS_thru"], ns_t), (y, ns_t, True), (g["NS_left"], ns_l), (y, ns_l, True),
           (g["EW_thru"], ew_t), (y, ew_t, True), (g["EW_left"], ew_l), (y, ew_l, True)]
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>",
         '    <tlLogic id="C" type="static" programID="webster" offset="0">']
    for item in seq:
        d, links = item[0], item[1]
        isy = len(item) > 2
        L.append(f'        <phase duration="{d}" state="{state([] if isy else links, links if isy else [])}"/>')
    L += ["    </tlLogic>", "</additional>"]
    open(path, "w").write("\n".join(L) + "\n")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=os.path.join(HERE, "results", "webster"))
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    out = {}
    for mv in ("through", "left"):
        sat = measure_saturation(os.path.join(args.outdir, "satflow_" + mv), movement=mv)
        out[mv] = sat
        print(f"--- {mv} ---")
        print({k: v for k, v in sat.items() if k not in ("headway_by_position", "estimators")})
        print("  estimators:", sat["estimators"])
        print("  headway by queue position:", sat["headway_by_position"])
    with open(os.path.join(args.outdir, "saturation_flow.json"), "w") as f:
        json.dump(out, f, indent=2)
