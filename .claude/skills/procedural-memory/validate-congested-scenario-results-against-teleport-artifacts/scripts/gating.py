#!/usr/bin/env python3
"""
Perimeter-gating validity test.

Reuses the construction method of the `implement-mfd-based-perimeter-gating`
skill (core/gate derivation from the compiled network; ratio-form green-time
throttle applied only to into-core links; provably inert at r=1) but evaluates
the SAME controller under two teleport conventions:

    --time-to-teleport 300   (SUMO default; the convention the original
                              gating episode used)
    --time-to-teleport -1    (teleporting disabled)

and additionally reports the teleport-FREE subset of trips, to answer whether
the published gating benefit was partly SUMO rescuing its own baseline.

Controller:  g_gate(k) = clip(g0 - K*(n(k) - n_set), g_min, g0), applied as the
ratio r = g_gate/g0 uniformly to every phase in which any gate link is green.
Each throttled phase runs green for r*d_i, then the program's own yellow, then
red for the remainder -- the cycle length, phase order, and every non-gate
movement's colour are untouched.  At r=1 the emitted state string is identical
to the static program's, so a non-binding set-point is a real negative control.
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

SUMO_HOME = os.environ.get("SUMO_HOME") or \
    "/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo"
sys.path.append(os.path.join(SUMO_HOME, "tools"))
import traci  # noqa
import sumolib  # noqa


# ---------------------------------------------------------------- topology ---
def derive_core(netfile, k=4):
    root = ET.parse(netfile).getroot()
    js = {}
    for j in root.findall("junction"):
        if j.get("type") == "traffic_light":
            js[j.get("id")] = (float(j.get("x")), float(j.get("y")))
    xs = sorted(set(round(v[0], 2) for v in js.values()))
    ys = sorted(set(round(v[1], 2) for v in js.values()))

    def mid(a, k):
        s = (len(a) - k) // 2
        return set(a[s:s + k])
    mx, my = mid(xs, k), mid(ys, k)
    core = {j for j, (x, y) in js.items() if round(x, 2) in mx and round(y, 2) in my}

    edges = {}
    for e in root.findall("edge"):
        if e.get("function") == "internal":
            continue
        edges[e.get("id")] = (e.get("from"), e.get("to"))
    core_edges = [e for e, (f, t) in edges.items() if f in core and t in core]
    gate_edges = [e for e, (f, t) in edges.items() if t in core and f not in core]
    gate_juncs = sorted({edges[e][0] for e in gate_edges})
    gate_juncs = [j for j in gate_juncs if j in js]  # must be signalised
    programs = {}
    for tl in root.findall("tlLogic"):
        programs[tl.get("id")] = [(float(p.get("duration")), p.get("state"))
                                  for p in tl.findall("phase")]
    return sorted(core), sorted(core_edges), sorted(gate_edges), gate_juncs, programs


# ------------------------------------------------------------------- run -----
def run(netfile, roufile, ttt, seed, outdir, end, gating, n_set, K, gmin_ratio,
        ctrl_interval=60, k_core=4, label=""):
    os.makedirs(outdir, exist_ok=True)
    core, core_edges, gate_edges, gate_juncs, programs = derive_core(netfile, k_core)

    sumo = os.path.join(SUMO_HOME, "..", "..", "bin", "sumo")
    sumo = sumolib.checkBinary("sumo")
    cmd = [sumo, "-n", netfile, "-r", roufile,
           "--tripinfo-output", os.path.join(outdir, "tripinfo.xml"),
           "--summary-output", os.path.join(outdir, "summary.xml"),
           "--summary-output.period", "10",
           "--log", os.path.join(outdir, "sumo.log"),
           "--end", str(end), "--seed", str(seed),
           "--time-to-teleport", str(ttt),
           "--no-step-log", "true", "--xml-validation", "never",
           "--duration-log.statistics", "true"]
    traci.start(cmd, label=label or ("g%d" % os.getpid()))
    conn = traci.getConnection(label) if label else traci

    # gate-link index sets and per-phase membership
    gate_links = {}
    gate_phases = {}
    cyc = {}
    for tl in gate_juncs:
        links = conn.trafficlight.getControlledLinks(tl)
        idx = [i for i, lk in enumerate(links)
               if lk and lk[0][1].split("_")[0] in gate_edges]
        gate_links[tl] = idx
        ph = programs[tl]
        gate_phases[tl] = [i for i, (d, s) in enumerate(ph)
                           if any(s[j] in "Gg" for j in idx)]
        cyc[tl] = sum(d for d, s in ph)
    g0 = {tl: sum(programs[tl][i][0] for i in gate_phases[tl]) for tl in gate_juncs}
    # yellow duration = duration of the phase following a gate green phase
    yel = {}
    for tl in gate_juncs:
        ph = programs[tl]
        yel[tl] = ph[(gate_phases[tl][0] + 1) % len(ph)][0] if gate_phases[tl] else 3.0

    for e in core_edges:
        conn.edge.subscribe(e, [0x10, 0x11])  # last step veh number, mean speed

    r_cur = {tl: 1.0 for tl in gate_juncs}
    acc_buf = []
    mfd = []
    control_log = []
    inert_violations = 0

    t = 0.0
    step = 1.0
    while t < end:
        conn.simulationStep()
        t = conn.simulation.getTime()
        subs = conn.edge.getAllSubscriptionResults()
        n = sum(subs[e][0x10] for e in core_edges if e in subs)
        prod = sum(subs[e][0x10] * subs[e][0x11] for e in core_edges if e in subs)
        acc_buf.append((n, prod))

        if gating:
            for tl in gate_juncs:
                ph = programs[tl]
                ct = t % cyc[tl]
                acc = 0.0
                cur = 0
                for i, (d, s) in enumerate(ph):
                    if ct < acc + d:
                        cur, el = i, ct - acc
                        break
                    acc += d
                else:
                    cur, el = len(ph) - 1, 0.0
                state = list(ph[cur][1])
                if cur in gate_phases[tl] and r_cur[tl] < 1.0:
                    gtime = r_cur[tl] * ph[cur][0]
                    if el >= gtime:
                        c = "y" if el < gtime + yel[tl] else "r"
                        for j in gate_links[tl]:
                            if state[j] in "Gg":
                                state[j] = c
                conn.trafficlight.setRedYellowGreenState(tl, "".join(state))
                if r_cur[tl] >= 1.0 and "".join(state) != ph[cur][1]:
                    inert_violations += 1

        if gating and int(t) % ctrl_interval == 0 and acc_buf:
            nbar = sum(a for a, _ in acc_buf) / len(acc_buf)
            for tl in gate_juncs:
                g = g0[tl] - K * (nbar - n_set)
                g = max(gmin_ratio * g0[tl], min(g0[tl], g))
                r_cur[tl] = g / g0[tl]
            control_log.append((t, round(nbar, 1), round(r_cur[gate_juncs[0]], 3)))
        if int(t) % 60 == 0 and acc_buf:
            mfd.append((t, sum(a for a, _ in acc_buf) / len(acc_buf),
                        sum(p for _, p in acc_buf) / len(acc_buf)))
            acc_buf = []

    conn.close()
    meta = {"core_junctions": core, "n_core_edges": len(core_edges),
            "gate_edges": gate_edges, "gate_junctions": gate_juncs,
            "g0_example": g0[gate_juncs[0]], "cycle": cyc[gate_juncs[0]],
            "gate_phases_example": gate_phases[gate_juncs[0]],
            "gate_link_counts": {tl: len(v) for tl, v in gate_links.items()},
            "inert_violations": inert_violations,
            "gating": gating, "n_set": n_set, "K": K, "gmin_ratio": gmin_ratio}
    with open(os.path.join(outdir, "gating_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    with open(os.path.join(outdir, "mfd.csv"), "w") as fh:
        fh.write("t,accumulation,production_veh_m_s\n")
        for a in mfd:
            fh.write("%.0f,%.3f,%.3f\n" % a)
    with open(os.path.join(outdir, "control.csv"), "w") as fh:
        fh.write("t,n_bar,r\n")
        for a in control_log:
            fh.write("%.0f,%.1f,%.3f\n" % a)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--rou", required=True)
    ap.add_argument("--ttt", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--end", type=float, default=10800)
    ap.add_argument("--gating", type=int, default=0)
    ap.add_argument("--nset", type=float, default=200)
    ap.add_argument("--K", type=float, default=0.5)
    ap.add_argument("--gmin", type=float, default=0.25)
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    m = run(a.net, a.rou, a.ttt, a.seed, a.outdir, a.end, bool(a.gating),
            a.nset, a.K, a.gmin, label=a.label)
    print(json.dumps({k: m[k] for k in
                      ("gate_junctions", "n_core_edges", "g0_example", "cycle",
                       "gate_phases_example", "inert_violations")}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
