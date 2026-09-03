#!/usr/bin/env python3
"""
Build ONE fixed-time, 2-phase coordinated signal plan (identical cycle,
splits, and progression offset -- by design speed -- at every signal, held
IDENTICAL across every median variant and every density) for the 3
signalized junctions SIG1/SIG2/SIG3, as a tlLogic additional file loaded
via WAUT (programID must differ from netconvert's own default "0", per the
gotcha documented in conduct-driveway-signal-warrant-traffic-impact-analysis).

Classifies each controlled link as arterial (EB_*/WB_* edges) or minor
(MIN_IN_* edges) purely from the COMPILED net's own controlled-lane list --
not assumed -- so this works unmodified on every variant/density network,
which all share identical SIG1/2/3 local geometry by construction.
"""
import os
import sys

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

CYCLE = 70.0
GREEN_MAIN = 46.0
YELLOW = 3.0
ALLRED = 2.0
GREEN_MINOR = CYCLE - GREEN_MAIN - 2 * (YELLOW + ALLRED)
DESIGN_SPEED = 13.89
SIGNAL_X = {"SIG1": 700.0, "SIG2": 1500.0, "SIG3": 2300.0}


def build(net_path, outdir):
    net = sumolib.net.readNet(net_path)
    lines = ['<additional>']
    for tlid in ["SIG1", "SIG2", "SIG3"]:
        try:
            tl = net.getTLS(tlid)
        except KeyError:
            continue
        conns = tl.getConnections()
        n_links = max(c[2] for c in conns) + 1
        state_main = ["r"] * n_links
        state_minor = ["r"] * n_links
        for inLane, outLane, linkIdx in conns:
            edge_id = inLane.getEdge().getID()
            if edge_id.startswith("MIN_IN"):
                state_minor[linkIdx] = "G"
            else:
                state_main[linkIdx] = "G"
        # yellow/all-red transition states (only touch links that were green)
        def transition(frm, char):
            return ["y" if c == "G" and char == "y" else ("r" if char == "r" else c) for c in frm]

        yellow_main = ["y" if c == "G" else c for c in state_main]
        allred_1 = ["r" if c in ("G", "y") else c for c in state_main]
        yellow_minor = ["y" if c == "G" else c for c in state_minor]
        allred_2 = ["r" if c in ("G", "y") else c for c in state_minor]

        offset = round((SIGNAL_X[tlid] / DESIGN_SPEED) % CYCLE, 2)
        lines.append(f'  <tlLogic id="{tlid}" type="static" programID="1" offset="{offset}">')
        lines.append(f'    <phase duration="{GREEN_MAIN:.1f}" state="{"".join(state_main)}"/>')
        lines.append(f'    <phase duration="{YELLOW:.1f}" state="{"".join(yellow_main)}"/>')
        lines.append(f'    <phase duration="{ALLRED:.1f}" state="{"".join(allred_1)}"/>')
        lines.append(f'    <phase duration="{GREEN_MINOR:.1f}" state="{"".join(state_minor)}"/>')
        lines.append(f'    <phase duration="{YELLOW:.1f}" state="{"".join(yellow_minor)}"/>')
        lines.append(f'    <phase duration="{ALLRED:.1f}" state="{"".join(allred_2)}"/>')
        lines.append('  </tlLogic>')
    lines.append('</additional>')
    with open(os.path.join(outdir, "signals.add.xml"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return os.path.join(outdir, "signals.add.xml")


if __name__ == "__main__":
    net_path, outdir = sys.argv[1], sys.argv[2]
    p = build(net_path, outdir)
    print("wrote", p)
