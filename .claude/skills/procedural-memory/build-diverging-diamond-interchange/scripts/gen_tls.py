#!/usr/bin/env python3
"""Generate fixed-time tlLogic for both designs PROGRAMMATICALLY from each compiled net's
own linkIndex map (per compare-left-turn-signal-treatments, to avoid G/g/r case drift).

Same cycle length (60 s) for both designs so the comparison isolates geometry, not cycle.

  DDI  terminal = TWO-PHASE : phase A serves EB-side, phase B serves WB-side. The
       arterial-to-on-ramp LEFT is unopposed, so it rides inside its direction's phase.
       No protected-left phase.
  CONV terminal = THREE-PHASE : through (both dirs) + PROTECTED arterial-left + off-ramp.
       The extra protected-left phase is exactly what the DDI eliminates.
"""
import os, xml.etree.ElementTree as ET

OUT = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-30_09-43-42/attempts/attempt-1/outputs"

# movement (from,to) definitions per terminal
MOV = {
    "W": {
        "EB_through":   ("Aw_EB", "I_EB"),
        "WB_through":   ("I_WB", "Aw_WB"),
        "onramp_left":  ("I_WB", "SBon"),   # WB -> SB on-ramp (heavy left)
        "onramp_right": ("Aw_EB", "SBon"),  # EB -> SB on-ramp (right)
        "off_to_eb":    ("SBoff", "I_EB"),
        "off_to_wb":    ("SBoff", "Aw_WB"),
    },
    "E": {
        "EB_through":   ("I_EB", "Ae_EB"),
        "WB_through":   ("Ae_WB", "I_WB"),
        "onramp_left":  ("I_EB", "NBon"),   # EB -> NB on-ramp (heavy left)
        "onramp_right": ("Ae_WB", "NBon"),  # WB -> NB on-ramp (right)
        "off_to_eb":    ("NBoff", "Ae_EB"),
        "off_to_wb":    ("NBoff", "I_WB"),
    },
}
# which on-ramp movement is EB-origin vs WB-origin (differs per terminal)
EB_ONRAMP = {"W": "onramp_right", "E": "onramp_left"}
WB_ONRAMP = {"W": "onramp_left",  "E": "onramp_right"}


def link_map(net, term):
    m = {}
    n = 0
    for c in net.findall("connection"):
        if c.get("tl") == term:
            m.setdefault((c.get("from"), c.get("to")), []).append(int(c.get("linkIndex")))
            n = max(n, int(c.get("linkIndex")))
    return m, n + 1


def phase(nlinks, spec):
    """spec: dict movement-key -> char ; resolved to link indices, default 'r'."""
    s = ["r"] * nlinks
    return s  # filled by caller via set_mov


def build_program(net, term, design):
    m, n = link_map(net, term)
    mv = MOV[term]

    def idxs(key):
        return m.get(mv[key], [])

    def mkphase(dur, greens):
        """greens: dict movement-key -> char"""
        s = ["r"] * n
        for key, ch in greens.items():
            for i in idxs(key):
                s[i] = ch
        return dur, "".join(s)

    def toyellow(dur, greens):
        s = ["r"] * n
        for key, ch in greens.items():
            if ch in ("G", "g"):
                for i in idxs(key):
                    s[i] = "y"
        return dur, "".join(s)

    phases = []
    if design == "ddi":
        # ---- 2-phase ----
        A = {"EB_through": "G", EB_ONRAMP[term]: "G", "off_to_eb": "g"}
        B = {"WB_through": "G", WB_ONRAMP[term]: "G", "off_to_wb": "g"}
        phases.append(mkphase(26, A)); phases.append(toyellow(4, A))
        phases.append(mkphase(26, B)); phases.append(toyellow(4, B))
    else:
        # ---- 3-phase : through / protected-left / off-ramp ----
        THRU = {"EB_through": "G", "WB_through": "G",
                EB_ONRAMP[term]: "g" if EB_ONRAMP[term] == "onramp_right" else "r",
                WB_ONRAMP[term]: "g" if WB_ONRAMP[term] == "onramp_right" else "r"}
        PROT = {"onramp_left": "G"}                       # protected arterial left
        OFF  = {"off_to_eb": "G", "off_to_wb": "G"}       # off-ramp discharge
        phases.append(mkphase(22, THRU)); phases.append(toyellow(4, THRU))
        phases.append(mkphase(13, PROT)); phases.append(toyellow(4, PROT))
        phases.append(mkphase(13, OFF));  phases.append(toyellow(4, OFF))
    return phases, m, n


def main():
    for design in ("ddi", "conv"):
        net = ET.parse(os.path.join(OUT, f"{design}.net.xml")).getroot()
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 f'<!-- {design.upper()} fixed-time tlLogic. '
                 f'{"2-phase, no protected-left" if design=="ddi" else "3-phase incl. PROTECTED arterial left"}. '
                 f'Cycle = 60 s (identical across designs). -->',
                 '<additional>']
        summary = []
        for term in ("W", "E"):
            phases, m, n = build_program(net, term, design)
            cyc = sum(d for d, _ in phases)
            ngreen = sum(1 for _, s in phases if "G" in s or "g" in s)
            summary.append((term, cyc, len(phases), ngreen))
            lines.append(f'    <tlLogic id="{term}" type="static" programID="fixed" offset="0">')
            for dur, st in phases:
                lines.append(f'        <phase duration="{dur}" state="{st}"/>')
            lines.append('    </tlLogic>')
        lines.append('</additional>')
        with open(os.path.join(OUT, f"{design}.tll.xml"), "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"=== {design.upper()} tlLogic ===")
        for term, cyc, np_, ng in summary:
            print(f"  terminal {term}: cycle={cyc}s  total phase entries={np_}  GREEN intervals={ng}")
        # print the actual phase strings for the record
        net2 = ET.parse(os.path.join(OUT, f"{design}.net.xml")).getroot()
        for term in ("W", "E"):
            phases, m, n = build_program(net2, term, design)
            print(f"  --- {term} phases ---")
            for dur, st in phases:
                print(f"      {dur:2d}s  {st}")
        print()


if __name__ == "__main__":
    main()
