#!/usr/bin/env python3
"""
Webster fixed-time plan generator for the study's junction, using the MEASURED
saturation flow / startup lost time (measure_sat.py), not a textbook default
(`measure-saturation-flow-and-validate-webster-method`).

Two phase structures on the same 16-link junction:
  p2 -- 2 phases, permissive left  (netconvert's own default structure)
        NS: links 0,1,2 G + 3 g   |   EW: links 4,5,6 G + 7 g   (+ S/W mirrors)
  p4 -- 4 phases, PROTECTED left (lagging), derived from and checked against the
        compiled foe matrix: no two simultaneously-green links may be foes.

Webster:
    y_i   = q_i / s                       (critical flow ratio of phase i)
    L     = sum_i (l1 + l2_i)             (l2 = yellow + all-red clearance)
    C_opt = (1.5 L + 5) / (1 - Y)
    g_i   = (C - L) * y_i / Y
"""
import argparse
import json
import os
import sys

N_LINKS = 16
# link index -> role
RIGHT = [0, 4, 8, 12]
THRU = [1, 2, 5, 6, 9, 10, 13, 14]
LEFT = [3, 7, 11, 15]

P2 = [  # (green links 'G', permissive links 'g')
    ([0, 1, 2, 8, 9, 10], [3, 11]),
    ([4, 5, 6, 12, 13, 14], [7, 15]),
]
P4 = [
    ([0, 1, 2, 8, 9, 10], []),      # NS through + right
    ([0, 3, 8, 11], []),            # NS protected left (+ compatible rights)
    ([4, 5, 6, 12, 13, 14], []),
    ([4, 7, 12, 15], []),
]


def state(g_links, perm_links=()):
    s = ["r"] * N_LINKS
    for i in g_links:
        s[i] = "G"
    for i in perm_links:
        s[i] = "g"
    return "".join(s)


def yellow_of(st):
    return "".join("y" if c in "Gg" else "r" for c in st)


def check_conflicts(struct, foes):
    bad = []
    for gi, (G, P) in enumerate(struct):
        allg = list(G) + list(P)
        for i in allg:
            for j in allg:
                if i != j and j in foes[i]:
                    # permissive lefts are ALLOWED to conflict (they yield);
                    # two protected 'G' links may never conflict
                    if i in G and j in G:
                        bad.append((gi, i, j))
    return bad


def critical_ratios(structure, q, split, s):
    """q = veh/h per approach; split = (right, through, left) fractions."""
    pr, ps, pl = split
    ys = []
    if structure == "p2":
        # each phase serves one whole approach pair over 2 lanes
        ys = [q * (pr + ps + pl) / (2.0 * s)] * 2
    else:
        thru_right = q * (pr + ps) / (2.0 * s)   # 2 lanes
        left = q * pl / (1.0 * s)                # left uses lane 1 only
        ys = [thru_right, left, thru_right, left]
    return ys


def webster(ys, l1, yellow, allred):
    n = len(ys)
    L = n * (l1 + yellow + allred)
    Y = sum(ys)
    C = None if Y >= 1.0 else (1.5 * L + 5.0) / (1.0 - Y)
    return L, Y, C


def build(structure, cycle, ys, l1, yellow, allred, out, program="w"):
    """programID must NOT be "0": SUMO hard-errors on a duplicate id+programID
    against the net's own tlLogic.  A distinct programID loads cleanly AND is the
    one actually used -- verified behaviourally (a 40 s vs 130 s cycle produced
    14.24 s vs 25.69 s mean delay, both different from the net default's 21.55 s),
    not merely by the absence of an error."""
    struct = P2 if structure == "p2" else P4
    n = len(struct)
    L = n * (l1 + yellow + allred)
    Y = sum(ys) if sum(ys) > 0 else 1.0
    eff = max(cycle - L, n * 4.0)
    greens = [max(5.0, eff * y / Y) for y in ys]
    # rescale so the phase durations sum exactly to the cycle
    tot = sum(greens) + n * (yellow + allred)
    greens = [g * (cycle - n * (yellow + allred)) / (tot - n * (yellow + allred))
              for g in greens]
    lines = ['<additional>',
             '  <tlLogic id="center" type="static" programID="%s" offset="0">' % program]
    for (G, P), g in zip(struct, greens):
        st = state(G, P)
        lines.append('    <phase duration="%.0f" state="%s"/>' % (round(g), st))
        lines.append('    <phase duration="%.0f" state="%s"/>' % (yellow, yellow_of(st)))
        lines.append('    <phase duration="%.0f" state="%s"/>' % (allred, "r" * N_LINKS))
    lines += ['  </tlLogic>', '</additional>']
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    return greens


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conflicts", required=True)
    ap.add_argument("--sat", required=True, help="saturation.txt from measure_sat.py")
    ap.add_argument("--structure", default="p2", choices=("p2", "p4"))
    ap.add_argument("--demand", type=float, required=True)
    ap.add_argument("--split", default="0.15,0.70,0.15")
    ap.add_argument("--cycle", type=float, default=0, help="0 = use Webster C_opt")
    ap.add_argument("--yellow", type=float, default=3.0)
    ap.add_argument("--allred", type=float, default=2.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    C = json.load(open(a.conflicts))
    foes = {int(k): set(v) for k, v in C["foes"].items()}
    sat = dict(l.strip().split("=") for l in open(a.sat) if "=" in l)
    s = float(sat["s_regression"])
    l1 = float(sat["l1_regression"])

    if a.check:
        for name, st_ in (("p2", P2), ("p4", P4)):
            bad = check_conflicts(st_, foes)
            print("%s: %s" % (name, "OK - no two protected-green links conflict"
                              if not bad else "CONFLICT %s" % bad[:6]))
        return

    split = tuple(float(x) for x in a.split.split(","))
    ys = critical_ratios(a.structure, a.demand, split, s)
    L, Y, Copt = webster(ys, l1, a.yellow, a.allred)
    cyc = a.cycle if a.cycle > 0 else (min(max(Copt, 40.0), 150.0) if Copt else 150.0)
    greens = build(a.structure, cyc, ys, l1, a.yellow, a.allred, a.out)
    print(json.dumps({"structure": a.structure, "s": s, "l1": l1, "y": [round(v, 4) for v in ys],
                      "Y": round(Y, 4), "L": round(L, 2),
                      "C_opt": None if Copt is None else round(Copt, 1),
                      "cycle_used": round(cyc, 1),
                      "greens": [round(g, 1) for g in greens], "out": a.out}))


if __name__ == "__main__":
    main()
