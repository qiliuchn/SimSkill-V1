#!/usr/bin/env python3
"""
H3, part 1: measure the ARTERIAL saturation-flow / PCE loss caused by heavy vehicles
directly, on a dedicated signalised-approach testbed built to match this study's
arterial cross-section (2 lanes, 50 km/h, the same Webster cycle length).

Method follows `measure-heavy-vehicle-passenger-car-equivalent`:
  * permanently oversaturated standing queue at a signalised stop line
  * ASYMPTOTIC discharge-headway estimator (the n-th and later queued vehicles),
    NOT the green-duration regression -- that skill records the regression being
    integer-quantisation-limited on a low-noise fleet
  * E_T backed out of the HCM heavy-vehicle adjustment factor
        f_HV = s_mix / s_car = 1 / (1 + P_HV * (E_T - 1))
  * the truck share is computed from the DISCHARGE data, never from the nominal
    demand-generation parameter.
"""
import os, sys, json, math, statistics as st
import xml.etree.ElementTree as ET
from common import *   # noqa

D = os.path.join(ROOT, "pce")
os.makedirs(D, exist_ok=True)
CYCLE_G, CYCLE_Y, CYCLE_AR, CYCLE_R = 37, 4, 2, 14      # matches the Webster plan
APPROACH_LEN = 600.0
WARM_CYCLES = 2
SEEDS_P = list(range(1, 9))
SHARES = [0.0, 0.05, 0.10, 0.20, 0.40]


def build():
    open(f"{D}/p.nod.xml", "w").write("""<nodes>
  <node id="A" x="0"   y="0" type="priority"/>
  <node id="B" x="600" y="0" type="traffic_light"/>
  <node id="C" x="1200" y="0" type="priority"/>
  <node id="S" x="600" y="-300" type="priority"/>
</nodes>""")
    open(f"{D}/p.edg.xml", "w").write(f"""<edges>
  <edge id="in"   from="A" to="B" numLanes="2" speed="{ART_SPEED:.3f}" priority="3"/>
  <edge id="out"  from="B" to="C" numLanes="2" speed="{ART_SPEED:.3f}" priority="3"/>
  <edge id="side" from="S" to="B" numLanes="1" speed="{LOC_SPEED:.3f}" priority="1"/>
</edges>""")
    r = sh(f'"{NETCONVERT}" -n {D}/p.nod.xml -e {D}/p.edg.xml -o {D}/p.net.xml '
           f'--no-turnarounds true --tls.default-type static --offset.disable-normalization true')
    assert r.returncode == 0, r.stderr
    # force the exact cycle we want on the through movement
    import sumolib
    net = sumolib.net.readNet(f"{D}/p.net.xml")
    tl = [t for t in net.getTrafficLights()][0]
    nlinks = max(c[2] for c in tl.getConnections()) + 1
    thru = sorted({c[2] for c in tl.getConnections()
                   if c[0].getEdge().getID() == "in" and c[1].getEdge().getID() == "out"})
    side = sorted({c[2] for c in tl.getConnections() if c[0].getEdge().getID() == "side"})

    def state(green, yellow=()):
        return "".join("G" if i in green else ("y" if i in yellow else "r") for i in range(nlinks))
    prog = (f'<additional>\n  <tlLogic id="{tl.getID()}" type="static" programID="1" offset="0">\n'
            f'    <phase duration="{CYCLE_G}" state="{state(thru)}"/>\n'
            f'    <phase duration="{CYCLE_Y}" state="{state((), thru)}"/>\n'
            f'    <phase duration="{CYCLE_AR}" state="{state(())}"/>\n'
            f'    <phase duration="{CYCLE_R}" state="{state(side)}"/>\n'
            f'    <phase duration="{CYCLE_Y}" state="{state((), side)}"/>\n'
            f'    <phase duration="{CYCLE_AR}" state="{state(())}"/>\n'
            f'  </tlLogic>\n'
            f'  <instantInductionLoop id="stopline_0" lane="out_0" pos="5" file="loop.xml"/>\n'
            f'  <instantInductionLoop id="stopline_1" lane="out_1" pos="5" file="loop.xml"/>\n'
            f'</additional>\n')
    open(f"{D}/p.add.xml", "w").write(prog)
    return tl.getID()


def routes(share, seed, end=1800):
    import random
    rng = random.Random(seed * 31 + int(share * 1000))
    out = ["<routes>", vtype_xml(),
           '  <route id="r" edges="in out"/>']
    t = 0.0
    k = 0
    while t < end:
        vt = "rigid" if rng.random() < share else "car"
        out.append('  <vehicle id="v%d" type="%s" route="r" depart="%.2f" departLane="free" departSpeed="max"/>'
                   % (k, vt, t))
        t += 0.6           # far above capacity -> permanent standing queue
        k += 1
    out.append("</routes>")
    f = f"{D}/p_{int(share*100)}_{seed}.rou.xml"
    open(f, "w").write("\n".join(out))
    return f


def run_cell(share, seed, end=1800):
    rf = routes(share, seed, end)
    tag = f"{int(share*100)}_{seed}"
    r = sh([SUMO, "-n", f"{D}/p.net.xml", "-r", rf, "-a", f"{D}/p.add.xml",
            "-e", str(end + 200), "--no-step-log", "true", "--seed", str(seed),
            "--time-to-teleport", "-1", "--max-depart-delay", "-1",
            "--tripinfo-output", f"{D}/ti_{tag}.xml"], cwd=D)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-1500:])
    os.rename(f"{D}/loop.xml", f"{D}/loop_{tag}.xml")
    return f"{D}/loop_{tag}.xml"


def analyse_loop(loopf, cycle):
    """Asymptotic saturation headway: per lane, per cycle, take the headways of the
    5th and later discharging vehicles."""
    veh = []
    for e in ET.parse(loopf).getroot():
        # instantInductionLoop emits one <instantOut> per event; keep "enter" events
        if e.get("state") not in (None, "enter"):
            continue
        veh.append((e.get("id"), float(e.get("time")), e.get("vehID", ""), e.get("type", "")))
    per_lane = {}
    for lid, t, _, vt in veh:
        per_lane.setdefault(lid, []).append((t, vt))
    hs, trucks, total = [], 0, 0
    for lid, arr in per_lane.items():
        arr.sort()
        cyc = {}
        for t, vt in arr:
            cyc.setdefault(int(t // cycle), []).append((t, vt))
        for c, lst in sorted(cyc.items()):
            if c < WARM_CYCLES:
                continue
            lst.sort()
            for i in range(1, len(lst)):
                if i >= 4:                       # 5th and later vehicle in the queue
                    h = lst[i][0] - lst[i - 1][0]
                    if h > 8.0:                  # cross-cycle gap, not a saturation headway
                        continue
                    hs.append(h)
                    total += 1
                    if lst[i][1] and lst[i][1] != "car":
                        trucks += 1
    return hs, (trucks / total if total else 0.0), total


def main():
    tlid = build()
    cycle = CYCLE_G + CYCLE_Y + CYCLE_AR + CYCLE_R + CYCLE_Y + CYCLE_AR
    print("testbed cycle = %d s, arterial green = %d s (g/C=%.3f)"
          % (cycle, CYCLE_G, CYCLE_G / cycle))
    res = {}
    for share in SHARES:
        cells = []
        for s in SEEDS_P:
            lf = run_cell(share, s)
            hs, realized, n = analyse_loop(lf, cycle)
            # capacity is governed by the MEAN discharge headway, not the median:
            # at a low truck share the median is essentially blind to the rare truck.
            h = st.mean(hs)
            cells.append(dict(seed=s, headway=h, sat_flow=3600.0 / h,
                              realized_share=realized, n_headways=n))
        res[share] = cells
        hh = [c["headway"] for c in cells]
        print("  nominal truck share %4.0f%% -> realized %.3f  headway %.3f s "
              "(sat flow %.0f veh/h/lane)"
              % (share * 100, st.mean([c["realized_share"] for c in cells]),
                 st.mean(hh), 3600.0 / st.mean(hh)))
    # ---- E_T -------------------------------------------------------------
    base = st.mean([c["sat_flow"] for c in res[0.0]])
    table = []
    for share in SHARES[1:]:
        cells = res[share]
        P = st.mean([c["realized_share"] for c in cells])
        smix = st.mean([c["sat_flow"] for c in cells])
        fhv = smix / base
        ET_ = 1 + (1.0 / fhv - 1.0) / P if P > 0 else float("nan")
        # per-seed CI (CRN: seed-paired)
        per = []
        for c, c0 in zip(cells, res[0.0]):
            f = c["sat_flow"] / c0["sat_flow"]
            p = c["realized_share"]
            per.append(1 + (1.0 / f - 1.0) / p if p > 0 else float("nan"))
        per = [x for x in per if x == x]
        lo, hi = ci95(per)
        table.append(dict(nominal_share=share, realized_share=P, sat_flow=smix,
                          sat_flow_base=base, f_HV=fhv, E_T=ET_,
                          E_T_seedmean=st.mean(per), E_T_ci=(lo, hi)))
        print("  P_HV=%.3f  s_mix=%.0f  f_HV=%.4f  E_T=%.3f  [seed-paired 95%% CI %.3f, %.3f]"
              % (P, smix, fhv, ET_, lo, hi))
    json.dump(dict(cells={str(k): v for k, v in res.items()}, table=table,
                   cycle=cycle, green=CYCLE_G, base_sat_flow=base),
              open(os.path.join(TAB, "pce_results.json"), "w"), indent=1)


def ci95(xs):
    if len(xs) < 2:
        return (float("nan"), float("nan"))
    m = st.mean(xs); sd = st.stdev(xs); n = len(xs)
    t = 2.365 if n == 8 else 2.0
    return (m - t * sd / math.sqrt(n), m + t * sd / math.sqrt(n))


if __name__ == "__main__":
    main()
