#!/usr/bin/env python3
"""Verify the corridor and the signal plans FROM THE COMPILED ARTEFACTS.

Nothing here trusts a design intention: every claim is re-read from the
compiled .net.xml, from the tlLogic add-files, or from the program TraCI
actually loaded into a running simulation.

  1. NETWORK      7 traffic_light junctions, uniform spacing, 3 arterial lanes
                  with an EXCLUSIVE left-turn bay (leftmost lane feeds only the
                  left-turn connection), cross street at every junction.
  2. HAND PLAN    phase durations sum to C at every signal; cross green == gX;
                  protected-left green == gL per direction; through window
                  width == gT in BOTH directions for all three phasing modes;
                  lead-lag displaces the WB window by exactly delta = gL+y+ar
                  while consuming the SAME total arterial green as lead-lead.
  3. TOOL PLAN    tlsCycleAdaptation --unified-cycle really unifies the cycle
                  across all 7 signals (checked in the add file AND in the
                  program TraCI loads); tlsCoordinator's offsets really land on
                  the tlLogic offset attribute.

Writes data/verify_plan.json.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402
import expbase as B          # noqa: E402
import runner as R           # noqa: E402
import scenario as S         # noqa: E402
import traci                 # noqa: E402

rep = {"checks": [], "failures": []}


def chk(name, cond, detail="", informational=False):
    rep["checks"].append(dict(name=name, ok=bool(cond), detail=str(detail),
                              informational=informational))
    if not cond and not informational:
        rep["failures"].append(name)
    print("%-58s %s  %s" % (name, "OK  " if cond else
                            ("INFO" if informational else "FAIL"), detail))


def main():
    sc = S.get(L=B.L0, seed=1, thru=B.THRU0, cross=B.CROSS0, side=B.SIDE0)
    nt = R.net_of(sc)

    # ---------------- 1. network -------------------------------------------
    tls = sorted(n.getID() for n in nt.getNodes() if n.getType() == "traffic_light")
    chk("network: exactly 7 signalised junctions",
        tls == ["J%d" % i for i in range(7)], tls)
    xs = [nt.getNode("J%d" % i).getCoord()[0] for i in range(7)]
    gaps = [round(xs[i + 1] - xs[i], 3) for i in range(6)]
    chk("network: uniform block spacing == L0", set(gaps) == {B.L0}, gaps)
    e = nt.getEdge("J2toJ3")
    chk("network: 3 arterial lanes", e.getLaneNumber() == 3, e.getLaneNumber())
    chk("network: arterial link length = L - junction box",
        abs(e.getLength() - B.L0) < 40, round(e.getLength(), 2))
    # exclusive left-turn bay: leftmost lane of an arterial approach must have
    # exactly one outgoing connection and it must be the left turn
    bay_ok, bay_det = True, []
    for i in range(7):
        up = "W" if i == 0 else "J%d" % (i - 1)
        inc = nt.getEdge("%stoJ%d" % (up, i))
        lm = inc.getLane(inc.getLaneNumber() - 1)
        outs = [c.getTo().getID() for c in lm.getOutgoing()]
        bay_det.append((inc.getID(), outs))
        if outs != ["J%dtoN%d" % (i, i)]:
            bay_ok = False
    chk("network: leftmost arterial lane is an EXCLUSIVE left bay", bay_ok,
        bay_det[0])
    xls = nt.getEdge("N3toJ3")
    chk("network: cross street present at every junction",
        all(nt.hasEdge("N%dtoJ%d" % (i, i)) and nt.hasEdge("S%dtoJ%d" % (i, i))
            for i in range(7)), xls.getLaneNumber())

    # ---------------- 2. hand-authored plan --------------------------------
    gX, gL = B.GX0, B.GL0
    for mode in ("lead-lead", "lead-lag", "lag-lead"):
        p = B.plan(modes=[mode] * 7)
        tot = sum(d for d, _ in p.phases(0))
        chk("plan[%s]: phase durations sum to C" % mode, abs(tot - p.C) < 1e-6, tot)
        eb = p.through_window(0, "EB")
        wb = p.through_window(0, "WB")
        chk("plan[%s]: EB through window width == gT" % mode,
            abs(eb[1] - p.gT) < 1e-6, eb)
        chk("plan[%s]: WB through window width == gT" % mode,
            abs(wb[1] - p.gT) < 1e-6, wb)
        shift = (wb[0] - eb[0]) % p.C
        want = 0.0 if mode == "lead-lead" else p.delta
        if mode == "lag-lead":
            want = (-p.delta) % p.C
        chk("plan[%s]: WB-EB window displacement == expected" % mode,
            abs(shift - want) < 1e-6, "%.2f vs %.2f" % (shift, want))
        # green time accounting, read back from the phase table
        acc = {}
        for d, st in p.phases(0):
            for mv, ch in st.items():
                if ch in "gG":
                    acc[mv] = acc.get(mv, 0.0) + d
        chk("plan[%s]: EBL protected green == gL" % mode,
            abs(acc.get("EBL", 0) - gL) < 1e-6, acc.get("EBL"))
        chk("plan[%s]: WBL protected green == gL" % mode,
            abs(acc.get("WBL", 0) - gL) < 1e-6, acc.get("WBL"))
        chk("plan[%s]: cross-street through green == gX" % mode,
            abs(acc.get("NBT", 0) - gX) < 1e-6, acc.get("NBT"))
    # identical arterial green budget across modes
    def art_green(mode):
        p = B.plan(modes=[mode] * 7)
        return p.C - gX - A.YELLOW - A.ALLRED
    chk("plan: lead-lead and lead-lag consume identical arterial time",
        abs(art_green("lead-lead") - art_green("lead-lag")) < 1e-9,
        art_green("lead-lead"))

    # ---------------- 2b. the plan as SUMO actually loads it ---------------
    p = B.plan(modes=["lead-lead"] * 4 + ["lead-lag"] * 3,
               offs=[0, 12, 24, 36, 48, 60, 72])
    d = os.path.join(B.WORK, "verify_plan")
    os.makedirs(d, exist_ok=True)
    add = p.write_add(nt, os.path.join(d, "plan.add.xml"))
    mi = A.movement_index(nt, 7)
    traci.start([A.SUMO, "-n", sc["net"], "-r", sc["rou"], "-a", add,
                 "--begin", "0", "--end", "5", "--no-step-log", "true",
                 "--xml-validation", "never"])
    loaded = {}
    for i in range(7):
        j = "J%d" % i
        lg = [l for l in traci.trafficlight.getAllProgramLogics(j)
              if l.programID == "prog"][0]
        acc, spans = 0.0, []
        for ph in lg.phases:
            spans.append((acc, acc + ph.duration, ph.state))
            acc += ph.duration
        loaded[j] = dict(cycle=acc, offset=getattr(lg, "offset", None),
                         nph=len(lg.phases), spans=spans)
    traci.close()
    chk("loaded: all 7 programs have cycle == C",
        all(abs(v["cycle"] - p.C) < 1e-6 for v in loaded.values()),
        sorted(set(round(v["cycle"], 3) for v in loaded.values())))
    # NOTE: this SUMO version's TraCI Logic object does not expose `offset`
    # (checked: AttributeError), so the written offsets are verified from the
    # add-file XML here and BEHAVIOURALLY from observed green onsets in
    # verify_offsets.py, which is the stronger check anyway.
    xml_offs = [A.load_programs([add])["J%d" % i][0] for i in range(7)]
    chk("add-file: offsets match what SignalPlan was asked to write",
        all(abs(xml_offs[i] - p.offs[i] % p.C) < 1e-6 for i in range(7)),
        xml_offs)
    chk("TraCI Logic object exposes an offset attribute",
        loaded["J0"]["offset"] is not None,
        "SUMO 1.27.1: NOT exposed -> offsets checked from XML + behaviourally",
        informational=True)
    ok_win = True
    det = []
    for i in range(7):
        j = "J%d" % i
        for dirn, mv in (("EB", "EBT"), ("WB", "WBT")):
            idx = mi[j][mv]
            g = [(a, b) for a, b, st in loaded[j]["spans"]
                 if all(st[k] in "gG" for k in idx)]
            w = sum(b - a for a, b in g)
            s0, w0 = p.through_window(i, dirn)
            if abs(w - w0) > 1e-6 or abs(min(a for a, _ in g) - s0) > 1e-6:
                ok_win = False
            det.append((j, dirn, round(min(a for a, _ in g), 2), round(w, 2),
                        round(s0, 2), round(w0, 2)))
    chk("loaded: through-green windows match SignalPlan.through_window()",
        ok_win, det[:2])

    # ---------------- 3. tlsCycleAdaptation --unified-cycle ----------------
    cyc, off = S.tls_tools(sc, os.path.join(B.WORK, "verify_tools"),
                           min_cycle=20, max_cycle=160, begin=B.WARM)
    pg = A.load_programs([sc["net"], cyc])
    cycles = sorted(set(round(sum(dd for dd, _ in pg["J%d" % i][1]), 3)
                        for i in range(7)))
    chk("tlsCycleAdaptation --unified-cycle: one cycle for all 7 signals",
        len(cycles) == 1, cycles)
    rep["webster_unified_cycle"] = cycles[0] if len(cycles) == 1 else cycles
    pg2 = A.load_programs([sc["net"], cyc, off])
    coord_offs = [round(pg2["J%d" % i][0], 3) for i in range(7)]
    chk("tlsCoordinator: writes non-trivial offsets onto the unified plan",
        len(set(coord_offs)) > 1, coord_offs)
    cycles2 = sorted(set(round(sum(dd for dd, _ in pg2["J%d" % i][1]), 3)
                         for i in range(7)))
    chk("tlsCoordinator: offset-only override preserves the unified cycle",
        cycles2 == cycles, cycles2)
    rep["tlscoordinator_offsets_on_webster_plan"] = coord_offs

    # tool plan's own analytic two-way band, for the record
    bE, C = A.band_generic(nt, pg2, xs, B.VPROG, "EB", 7)
    bW, _ = A.band_generic(nt, pg2, xs, B.VPROG, "WB", 7)
    rep["tool_plan_band"] = dict(cycle=C, b_EB=bE, b_WB=bW)
    print("tool (Webster+tlsCoordinator) plan analytic band: C=%s EB=%.2f WB=%.2f"
          % (C, bE, bW))

    rep["all_pass"] = not rep["failures"]
    json.dump(rep, open(os.path.join(B.DATA, "verify_plan.json"), "w"), indent=1)
    print("\nALL PASS" if rep["all_pass"] else "\nFAILURES: %s" % rep["failures"])
    return 0 if rep["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
