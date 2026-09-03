#!/usr/bin/env python3
"""
Verify, from the running simulation and from the compiled net, that
  (a) the Webster program authored in add.xml is the ACTIVE program at J
      (not netconvert's default program '0'),
  (b) no two simultaneously-green links at J are foes in the compiled net
      (i.e. every phase is genuinely conflict-free / fully protected),
  (c) each phase's green links map to the intended movement set.
"""
import json
import os
import sys

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402
import traci  # noqa: E402

J_MOVES = {
    ("E_XW_J", "E_J_XE"): "AR_EB_THRU", ("E_XW_J", "M_J_N"): "AR_EB_LEFT",
    ("E_XW_J", "M_J_S"): "AR_EB_RIGHT",
    ("W_XE_J", "W_J_XW"): "AR_WB_THRU", ("W_XE_J", "M_J_S"): "AR_WB_LEFT",
    ("W_XE_J", "M_J_N"): "AR_WB_RIGHT",
    ("M_N_J", "M_J_S"): "MI_SB_THRU", ("M_N_J", "E_J_XE"): "MI_SB_LEFT",
    ("M_N_J", "W_J_XW"): "MI_SB_RIGHT",
    ("M_S_J", "M_J_N"): "MI_NB_THRU", ("M_S_J", "W_J_XW"): "MI_NB_LEFT",
    ("M_S_J", "E_J_XE"): "MI_NB_RIGHT",
}


def verify(rundir):
    meta = json.load(open(os.path.join(rundir, "meta.json")))
    net = sumolib.net.readNet(meta["net"])
    node = net.getNode("J")
    tls = net.getTLS("J")
    li2conn = {}
    for c in node.getConnections():
        if c.getFrom().getID().startswith(":"):
            continue
        i = node.getLinkIndex(c)
        li2conn[i] = c
    li2move = {}
    for inl, outl, li in tls.getConnections():
        li2move[li] = J_MOVES.get((inl.getEdge().getID(), outl.getEdge().getID()), "?")

    lbl = f"vs{os.path.basename(rundir)}"
    traci.start(["sumo", "-n", meta["net"], "-r", meta["route_file"],
                 "-a", os.path.join(rundir, "add.xml"), "--begin", "0", "--end", "10",
                 "--no-step-log", "true", "--no-warnings", "true",
                 "--xml-validation", "never"], label=lbl)
    c = traci.getConnection(lbl)
    active = c.trafficlight.getProgram("J")
    logics = c.trafficlight.getAllProgramLogics("J")
    act = [l for l in logics if l.programID == active][0]
    phases = [(p.duration, p.state) for p in act.phases]
    c.close()

    plan = meta["plan"]
    authored = []
    n = plan["n_tls_links"]
    for g, lk in zip(plan["green_s"], plan["phase_link_indices"]):
        authored.append((round(g, 1), "".join("G" if i in lk else "r" for i in range(n))))
    got_green = [(round(d, 1), s) for d, s in phases if "G" in s]
    match = (len(got_green) == len(authored) and
             all(abs(a[0] - b[0]) < 0.11 and a[1] == b[1] for a, b in zip(authored, got_green)))

    # conflict check on every phase of the ACTIVE program
    conflicts = []
    for d, s in phases:
        green = [i for i, ch in enumerate(s) if ch in "Gg"]
        for a in green:
            for b in green:
                if a < b and node.areFoes(a, b):
                    conflicts.append((s, a, b, li2move.get(a), li2move.get(b)))
    phase_moves = [{"dur": d, "state": s,
                    "green_moves": sorted({li2move.get(i, "?") for i, ch in enumerate(s) if ch in "Gg"})}
                   for d, s in phases if "G" in s]
    return {"rundir": os.path.basename(rundir), "variant": meta["variant"],
            "active_program": active, "programs": [l.programID for l in logics],
            "authored_matches_active": match,
            "n_green_phases": len(got_green),
            "phase_moves": phase_moves,
            "intra_phase_foe_conflicts": conflicts,
            "conflict_free": len(conflicts) == 0}


if __name__ == "__main__":
    out = [verify(d) for d in sys.argv[2:]]
    with open(sys.argv[1], "w") as f:
        json.dump(out, f, indent=1)
    for r in out:
        print(f"\n== {r['variant']}: active={r['active_program']} of {r['programs']}  "
              f"authored==active: {r['authored_matches_active']}  "
              f"green phases={r['n_green_phases']}  conflict_free={r['conflict_free']}")
        for p in r["phase_moves"]:
            print(f"   {p['dur']:6.1f}s {p['state']}  {p['green_moves']}")
        for cf in r["intra_phase_foe_conflicts"]:
            print("   CONFLICT", cf)
