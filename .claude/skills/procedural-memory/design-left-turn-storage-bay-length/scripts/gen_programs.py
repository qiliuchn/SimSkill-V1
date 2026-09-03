#!/usr/bin/env python3
"""
Generate protected-only tlLogic programs at several NS left-turn green splits,
plus an actuated variant.

State strings are built PROGRAMMATICALLY from the COMPILED net's own
linkIndex/dir mapping (per `compare-left-turn-signal-treatments`), never typed
by hand -- a single mistyped G/g/r across a 4-condition x 8-bay-length sweep
would silently invalidate the whole comparison.

Protected-only signature: every left link is 'G' ONLY in its dedicated leading
phase and 'r' everywhere else -- never 'g' (which would be permissive).

Cycle structure (fixed-time, cycle = 90 s):
    P0  NS protected left      gL          <- the swept variable
    P1  NS left yellow          3
    P2  NS through + right     gT = 48-gL  <- absorbs the remainder
    P3  NS through yellow       3
    P4  EW protected left       8
    P5  EW left yellow          3
    P6  EW through + right     22
    P7  EW through yellow       3
Total NS green (gL+gT) is held at 48 s in every fixed-time condition, so the
comparison isolates the LEFT SPLIT rather than confounding it with a different
overall allocation of capacity to the NS street.
"""
import argparse
import os
import xml.etree.ElementTree as ET

CYCLE = 90
NS_GREEN_TOTAL = 48     # gL + gT, held constant
EW_LEFT = 8
EW_THRU = 22
YEL = 3

SPLITS = [8, 16, 24]    # gL values for the fixed-time conditions


def link_map(netfile):
    """movement -> tls link index, read from the compiled net itself."""
    root = ET.parse(netfile).getroot()
    mv = {}
    for c in root.findall("connection"):
        if c.get("tl") != "C":
            continue
        frm = c.get("from")
        if frm.startswith("in_N"):
            appr = "N"
        else:
            appr = frm.split("_")[1]
        mv[(appr, c.get("dir"))] = int(c.get("linkIndex"))
    return mv


def build_programs(netfile, outdir):
    os.makedirs(outdir, exist_ok=True)
    mv = link_map(netfile)
    N = max(mv.values()) + 1
    L = {a: mv[(a, "l")] for a in "NESW"}
    T = {a: mv[(a, "s")] for a in "NESW"}
    R = {a: mv[(a, "r")] for a in "NESW"}

    def phase(spec):
        s = ["r"] * N
        for idx, ch in spec.items():
            s[idx] = ch
        return "".join(s)

    def make(gL):
        gT = NS_GREEN_TOTAL - gL
        return [
            (gL,  phase({L['N']: 'G', L['S']: 'G'})),                                                   # P0 NS left
            (YEL, phase({L['N']: 'y', L['S']: 'y'})),                                                   # P1
            (gT,  phase({R['N']: 'G', T['N']: 'G', R['S']: 'G', T['S']: 'G'})),                         # P2 NS thru
            (YEL, phase({R['N']: 'y', T['N']: 'y', R['S']: 'y', T['S']: 'y'})),                         # P3
            (EW_LEFT, phase({L['E']: 'G', L['W']: 'G'})),                                               # P4 EW left
            (YEL, phase({L['E']: 'y', L['W']: 'y'})),                                                   # P5
            (EW_THRU, phase({R['E']: 'G', T['E']: 'G', R['W']: 'G', T['W']: 'G'})),                     # P6 EW thru
            (YEL, phase({R['E']: 'y', T['E']: 'y', R['W']: 'y', T['W']: 'y'})),                         # P7
        ]

    written = {}
    report = []
    for gL in SPLITS:
        ph = make(gL)
        name = f"split{gL:02d}"
        path = os.path.join(outdir, f"tl_{name}.add.xml")
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>",
                 f'    <tlLogic id="C" type="static" programID="{name}" offset="0">']
        for d, s in ph:
            lines.append(f'        <phase duration="{d}" state="{s}"/>')
        lines += ["    </tlLogic>", "</additional>"]
        open(path, "w").write("\n".join(lines) + "\n")
        written[name] = path
        report.append((name, ph, None))

    # ---- actuated variant ----
    # Same phase sequence and same nominal durations as the middle split, but the
    # two NS phases may extend/gap out on demand. EW phases are pinned
    # (min==max) so only the NS left/through allocation is adaptive.
    ph = make(16)
    name = "actuated"
    path = os.path.join(outdir, f"tl_{name}.add.xml")
    bounds = {0: (5, 28), 2: (8, 36)}   # phase index -> (minDur, maxDur)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>",
             f'    <tlLogic id="C" type="actuated" programID="{name}" offset="0">',
             '        <param key="max-gap" value="3.0"/>',
             '        <param key="detector-gap" value="2.0"/>',
             '        <param key="show-detectors" value="true"/>']
    for i, (d, s) in enumerate(ph):
        if i in bounds:
            lo, hi = bounds[i]
            lines.append(f'        <phase duration="{d}" minDur="{lo}" maxDur="{hi}" state="{s}"/>')
        else:
            lines.append(f'        <phase duration="{d}" state="{s}"/>')
    lines += ["    </tlLogic>", "</additional>"]
    open(path, "w").write("\n".join(lines) + "\n")
    written[name] = path
    report.append((name, ph, bounds))

    return written, (L, T, R, N), report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    written, (L, T, R, N), report = build_programs(a.net, a.outdir)
    print("Link map read from compiled net:")
    print("  LEFT :", L)
    print("  THRU :", T)
    print("  RIGHT:", R)
    print()
    PH = ["NS-LEFT", "ns-l-yel", "NS-THRU", "ns-t-yel",
          "EW-LEFT", "ew-l-yel", "EW-THRU", "ew-t-yel"]
    for name, ph, bounds in report:
        cyc = sum(d for d, _ in ph)
        print(f"=== {name} (nominal cycle={cyc}s) ===")
        print("            idx: " + "".join(str(i % 10) for i in range(N)))
        for i, (d, s) in enumerate(ph):
            lc = "".join(s[L[a]] for a in "NESW")
            tc = "".join(s[T[a]] for a in "NESW")
            b = f" [{bounds[i][0]}-{bounds[i][1]}]" if bounds and i in bounds else ""
            print(f"  P{i} {PH[i]:9s} {d:2d}s  {s}   leftNESW={lc}  thruNESW={tc}{b}")
        # protected-only assertion: no lowercase 'g' on any left link, ever
        bad = [(i, a) for i, (d, s) in enumerate(ph) for a in "NESW" if s[L[a]] == "g"]
        print(f"  protected-only check (no permissive 'g' on any left link): "
              f"{'PASS' if not bad else 'FAIL ' + str(bad)}")
        print()
    for k, v in written.items():
        print("wrote", v)
