#!/usr/bin/env python3
"""
ONE shared OD matrix per (total demand Q, minor-street share m) -- identical for all
three variants (OD-fair).  od2trips turns it into a trips file; duarouter then
recomputes routes INDEPENDENTLY per variant, so each variant's path set reflects
only its own legal movements.

Movement-class split (fixed):
  arterial origins: 75% through, 15% left, 10% right
  minor    origins: 30% through, 35% left, 35% right   (65% of minor demand is
                                                        banned at J under RCUT)
"""
import os
import subprocess
import sys

ZONES = {  # zone -> (source edge, sink edge)
    "Z_W": ("E_W_XW", "W_XW_W"),
    "Z_E": ("W_E_XE", "E_XE_E"),
    "Z_N": ("M_N_J", "M_J_N"),
    "Z_S": ("M_S_J", "M_J_S"),
}
ART_SPLIT = {"thru": 0.75, "left": 0.15, "right": 0.10}
MIN_SPLIT = {"thru": 0.30, "left": 0.35, "right": 0.35}
# origin -> {movement: destination}
DEST = {
    "Z_W": {"thru": "Z_E", "left": "Z_N", "right": "Z_S"},
    "Z_E": {"thru": "Z_W", "left": "Z_S", "right": "Z_N"},
    "Z_N": {"thru": "Z_S", "left": "Z_E", "right": "Z_W"},
    "Z_S": {"thru": "Z_N", "left": "Z_W", "right": "Z_E"},
}
# (origin, destination) -> movement class label used throughout the study
def movement_class(o, d):
    for mv, dd in DEST[o].items():
        if dd == d:
            fam = "ART" if o in ("Z_W", "Z_E") else "MIN"
            return f"{fam}_{mv.upper()}"
    return "OTHER"


def od_counts(Q, m):
    """Return {(o,d): veh/h} for the 12 OD pairs."""
    out = {}
    art = Q * (1.0 - m) / 2.0
    mino = Q * m / 2.0
    for o in ("Z_W", "Z_E"):
        for mv, sh in ART_SPLIT.items():
            out[(o, DEST[o][mv])] = art * sh
    for o in ("Z_N", "Z_S"):
        for mv, sh in MIN_SPLIT.items():
            out[(o, DEST[o][mv])] = mino * sh
    return out


def write_taz(path):
    with open(path, "w") as f:
        f.write("<additional>\n")
        for z, (src, snk) in ZONES.items():
            f.write(f'  <taz id="{z}">\n'
                    f'    <tazSource id="{src}" weight="1.0"/>\n'
                    f'    <tazSink id="{snk}" weight="1.0"/>\n  </taz>\n')
        f.write("</additional>\n")


def write_matrix(path, Q, m):
    cnt = od_counts(Q, m)
    with open(path, "w") as f:
        f.write("$OR;D2\n* From-Time  To-Time\n0.00 1.00\n* Factor\n1.00\n")
        for (o, d), v in sorted(cnt.items()):
            f.write(f"{o} {d} {v:.2f}\n")
    return cnt


def make_trips(outdir, Q, m, seed=42):
    os.makedirs(outdir, exist_ok=True)
    taz = f"{outdir}/taz.xml"
    mat = f"{outdir}/od.txt"
    trips = f"{outdir}/trips.xml"
    write_taz(taz)
    cnt = write_matrix(mat, Q, m)
    r = subprocess.run(["od2trips", "-n", taz, "-d", mat, "-o", trips,
                        "--seed", str(seed), "--prefix", "v",
                        "--departlane", "best", "--departspeed", "max",
                        "--no-step-log", "true"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit("od2trips failed")
    return trips, cnt


if __name__ == "__main__":
    t, c = make_trips(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]))
    print(t)
    print(sum(c.values()), "veh/h total")
