#!/usr/bin/env python3
"""Generate the four RTOR x LPI signal programs for a compiled net.

EVERY state string is built from the compiled net's own linkIndex map
(linkmap.LinkMap); no character position is ever hand-typed.

Cycle structure (C = 100 s, identical in all four cells):

  per direction pair P in (NS, EW):
     10 s  P protected LEFT              (left of P = G)
      3 s  P left yellow
      2 s  all-red
    [ 5 s  LPI-P : parallel crossings of P = G, ALL vehicle links = r ]
     30 s  P through+right green         (through=G, right=g,
      (25 s if LPI)                       parallel crossings of P = G)
      3 s  P through+right yellow
      2 s  all-red
  -> 50 s per half cycle, 100 s cycle, identical phase boundaries in every cell.

Pedestrian WALK time on the parallel crossings is 30 s in BOTH the LPI and the
no-LPI programs (5+25 vs 30) - only the *vehicle* green shrinks 30 -> 25 s.

RTOR is represented by SUMO's 's' state character ("green right-turn arrow
requires stopping"): every right-turn link that would otherwise be 'r' becomes
's'.  Exception: during the LPI interval all vehicle links are hard 'r', per
the definition of a leading pedestrian interval.
"""
import os
import sys

from linkmap import LinkMap, PAIRS

CYCLE_PLAN = [  # (name, duration_noLPI, duration_LPI)
    ("left", 10, 10),
    ("left_yellow", 3, 3),
    ("allred_a", 2, 2),
    ("lpi", 0, 5),
    ("thru", 30, 25),
    ("thru_yellow", 3, 3),
    ("allred_b", 2, 2),
]


def build_phases(lm, rtor, lpi):
    """Return list of (duration, state, label)."""
    phases = []
    for pair in ("NS", "EW"):
        me = PAIRS[pair]
        par = lm.parallel_crossings(pair)
        for name, d0, d1 in CYCLE_PLAN:
            dur = d1 if lpi else d0
            if dur == 0:
                continue
            s = ["r"] * lm.n            # default: everything red
            if name == "lpi":
                # ALL vehicle links hard red (no 's'), parallel crossings walk
                for x in par:
                    s[x] = "G"
            else:
                # RTOR baseline: every right-turn link that is red -> 's'
                if rtor:
                    for a in "NESW":
                        s[lm.right(a)] = "s"
                if name == "left":
                    for a in me:
                        s[lm.left(a)] = "G"
                elif name == "left_yellow":
                    for a in me:
                        s[lm.left(a)] = "y"
                elif name == "thru":
                    for a in me:
                        s[lm.thru(a)] = "G"
                        s[lm.right(a)] = "g"   # permitted, yields to peds
                    for x in par:
                        s[x] = "G"
                elif name == "thru_yellow":
                    for a in me:
                        s[lm.thru(a)] = "y"
                        s[lm.right(a)] = "y"
                # allred_a / allred_b: nothing but the RTOR baseline
            phases.append((dur, "".join(s), f"{pair}_{name}"))
    return phases


def cell_name(rtor, lpi):
    return ("RTOR" if rtor else "NTOR") + ("_LPI" if lpi else "_noLPI")


def write_program(lm, rtor, lpi, out_path, prog_id):
    phases = build_phases(lm, rtor, lpi)
    C = sum(d for d, _, _ in phases)
    lines = ['<additional>',
             f'    <tlLogic id="{lm.tls_id}" type="static" programID="{prog_id}" offset="0">']
    for d, s, lab in phases:
        lines.append(f'        <phase duration="{d}" state="{s}" name="{lab}"/>')
    lines += ['    </tlLogic>', '</additional>']
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return phases, C


def annotate(lm, phases):
    hdr = ["idx", "dur", "label", "state"]
    rows = [f"{'idx':>3s} {'dur':>4s} {'label':<16s} {'state':<20s} | "
            f"R(N,E,S,W)   T(N,E,S,W)   L(N,E,S,W)   X(N,E,S,W)"]
    t = 0
    for i, (d, s, lab) in enumerate(phases):
        R = "".join(s[lm.right(a)] for a in "NESW")
        T = "".join(s[lm.thru(a)] for a in "NESW")
        L = "".join(s[lm.left(a)] for a in "NESW")
        X = "".join(s[lm.leg_xing[a]] for a in "NESW")
        rows.append(f"{i:3d} {d:4d} {lab:<16s} {s:<20s} | {R:<12s} {T:<12s} {L:<12s} {X}")
        t += d
    rows.append(f"cycle length = {t} s")
    return "\n".join(rows)


if __name__ == "__main__":
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    outdir = os.path.join(base, "outputs", "programs")
    os.makedirs(outdir, exist_ok=True)
    report = []
    for prefix in ("A_excl", "B_shared"):
        net = os.path.join(base, "outputs", "net", f"{prefix}.net.xml")
        lm = LinkMap(net)
        ok, n, nv, nx = lm.state_len_check()
        report.append(f"########## {prefix} ##########")
        report.append(f"link map ({n} links = {nv} vehicle + {nx} crossing); "
                      f"compiled-program state-length check: {'PASS' if ok else 'FAIL'}")
        report.append(lm.describe())
        report.append(f"rights={lm.rights()}  leg_crossings={lm.leg_xing}")
        report.append(f"NS parallel crossings={lm.parallel_crossings('NS')}  "
                      f"EW parallel crossings={lm.parallel_crossings('EW')}")
        for a in "NESW":
            report.append(f"  foe crossings of {a}-right (link {lm.right(a)}): "
                          f"{lm.foe_crossings_of_right(a)}")
        for rtor in (False, True):
            for lpi in (False, True):
                cn = cell_name(rtor, lpi)
                p = os.path.join(outdir, f"{prefix}.{cn}.tll.xml")
                phases, C = write_program(lm, rtor, lpi, p, cn)
                report.append(f"\n----- {prefix} / {cn}  (C={C}s) -> {p}")
                report.append(annotate(lm, phases))
        report.append("")
    txt = "\n".join(report)
    with open(os.path.join(base, "outputs", "program_generation.txt"), "w") as f:
        f.write(txt + "\n")
    print(txt)
