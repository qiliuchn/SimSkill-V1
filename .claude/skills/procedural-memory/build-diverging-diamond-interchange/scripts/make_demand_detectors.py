#!/usr/bin/env python3
"""Write the SHARED demand (routes + fixed flows) and the E1 detector additional-file.
Identical edges exist in both the DDI and conventional nets, so one demand file serves both.
Heavy arterial-to-on-ramp LEFT turns: WB_left (west terminal) and EB_left (east terminal)."""
import os

OUT = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-30_09-43-42/attempts/attempt-1/outputs"
END = 1200

# route_id : (edge list, is_heavy_left)
ROUTES = {
    "EB_through": ("Aw_EB I_EB Ae_EB", False),
    "WB_through": ("Ae_WB I_WB Aw_WB", False),
    "WB_left":    ("Ae_WB I_WB SBon fw_sb_3 fw_sb_4", True),   # WB -> SB on-ramp LEFT (west terminal)
    "EB_left":    ("Aw_EB I_EB NBon fw_nb_3 fw_nb_4", True),   # EB -> NB on-ramp LEFT (east terminal)
    "EB_right":   ("Aw_EB SBon fw_sb_3 fw_sb_4", False),       # EB -> SB on-ramp right (west)
    "WB_right":   ("Ae_WB NBon fw_nb_3 fw_nb_4", False),       # WB -> NB on-ramp right (east)
    "SBoff_EB":   ("fw_sb_1 SBoff I_EB Ae_EB", False), # SB off-ramp -> EB arterial
    "SBoff_WB":   ("fw_sb_1 SBoff Aw_WB", False),      # SB off-ramp -> WB arterial
    "NBoff_EB":   ("fw_nb_1 NBoff Ae_EB", False),      # NB off-ramp -> EB arterial
    "NBoff_WB":   ("fw_nb_1 NBoff I_WB", False),       # NB off-ramp -> WB arterial
    "SB_thru":    ("fw_sb_1 fw_sb_2 fw_sb_3 fw_sb_4", False),  # freeway SB mainline
    "NB_thru":    ("fw_nb_1 fw_nb_2 fw_nb_3 fw_nb_4", False),  # freeway NB mainline
}
# vehicles per hour per flow.
# Heavy LEFT (420/h) sits between the conventional protected-left capacity (~1 lane x1800
# x13/60s ~= 390/h, so conv is OVER-saturated on the left) and the DDI's unopposed-left
# capacity (~1 lane x1800 x26/60s ~= 780/h, comfortable). Other movements kept moderate so
# the interchange is LOADED but not trivially gridlocked, isolating the left-turn effect.
VPH = {
    "EB_through": 240, "WB_through": 240,
    "WB_left": 470, "EB_left": 470,          # HEAVY left turns (the headline movement)
    "EB_right": 70, "WB_right": 70,
    "SBoff_EB": 130, "SBoff_WB": 45,
    "NBoff_EB": 130, "NBoff_WB": 45,
    "SB_thru": 380, "NB_thru": 380,
}

def write_demand():
    L = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<routes>',
         '    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5" minGap="2.5" maxSpeed="30"/>']
    for rid, (edges, _) in ROUTES.items():
        L.append(f'    <route id="r_{rid}" edges="{edges}"/>')
    L.append("")
    for rid in ROUTES:
        L.append(f'    <flow id="{rid}" type="car" route="r_{rid}" begin="0" end="{END}" '
                 f'vehsPerHour="{VPH[rid]}" departLane="best" departSpeed="max"/>')
    L.append('</routes>')
    with open(os.path.join(OUT, "demand.rou.xml"), "w") as f:
        f.write("\n".join(L) + "\n")

def write_detectors():
    # E1 on interchange exits AND on-ramp entrances. (from,lanes)
    dets = [
        ("SBon",   1, "onramp_SB"),   # on-ramp entrance (served left+right onto SB freeway)
        ("NBon",   1, "onramp_NB"),   # on-ramp entrance (served left+right onto NB freeway)
        ("Ae_EB",  2, "exit_EB"),     # EB arterial exit (east)
        ("Aw_WB",  2, "exit_WB"),     # WB arterial exit (west)
        ("fw_sb_4", 2, "exit_SB"),    # SB freeway exit (downstream of on-ramp merge)
        ("fw_nb_4", 2, "exit_NB"),    # NB freeway exit (downstream of on-ramp merge)
    ]
    L = ['<?xml version="1.0" encoding="UTF-8"?>', '<additional>']
    for edge, nl, name in dets:
        for ln in range(nl):
            L.append(f'    <inductionLoop id="e1_{name}_{ln}" lane="{edge}_{ln}" pos="5.0" '
                     f'period="60" file="e1_out.xml"/>')
    L.append('</additional>')
    with open(os.path.join(OUT, "detectors.add.xml"), "w") as f:
        f.write("\n".join(L) + "\n")

if __name__ == "__main__":
    write_demand()
    write_detectors()
    print("wrote demand.rou.xml and detectors.add.xml")
