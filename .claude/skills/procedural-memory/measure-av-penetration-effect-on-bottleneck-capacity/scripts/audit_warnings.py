#!/usr/bin/env python3
"""Audit every run's SUMO stderr for collisions and emergency braking.

SUMO's own documentation warns that the ACC/CACC models produce collisions at
coarse step lengths; this study uses the recommended 0.1 s step, so the honest
question is whether collisions still occur and whether they contaminate any
fleet's capacity number.  Written to outputs/warning_audit.csv + .md.
"""
import os
import re
import csv
import glob
import json
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUTDIR = os.environ.get("OUTDIR", os.path.join(os.path.dirname(os.path.dirname(ROOT)), "outputs"))

RE_COLL = re.compile(r"collision with vehicle")
RE_EB = re.compile(r"performs emergency braking")


def main():
    rows = []
    for f in sorted(glob.glob(os.path.join(ROOT, "runs", "*", "s*", "sumo.stderr"))):
        rd = os.path.dirname(f)
        cell = os.path.basename(os.path.dirname(rd))
        seed = os.path.basename(rd)
        txt = open(f, errors="ignore").read()
        nc, ne = len(RE_COLL.findall(txt)), len(RE_EB.findall(txt))
        disc = ntrips = ""
        mj = os.path.join(rd, "metrics.json")
        if os.path.exists(mj):
            try:
                m = json.load(open(mj))
                ntrips = m.get("tripinfo", {}).get("n", "")
            except Exception:
                pass
        rows.append(dict(cell=cell, seed=seed, collisions=nc, emergency_brakings=ne,
                         completed_trips=ntrips))
    with open(os.path.join(OUTDIR, "warning_audit.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["cell", "seed", "collisions",
                                           "emergency_brakings", "completed_trips"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # per-cell rollup
    per = {}
    for r in rows:
        per.setdefault(r["cell"], []).append(r)
    L = ["# Collision / emergency-braking audit\n",
         "SUMO was run with `collision.action = warn`, so a reported collision does **not**",
         "remove the vehicles - the run continues with vehicles that briefly overlapped.",
         "Any fleet with a non-zero collision count therefore has a capacity number that is",
         "to some degree an artefact of the model failing rather than a clean measurement.\n",
         "Step length was 0.1 s throughout, the value SUMO's own ACC/CACC documentation",
         "recommends to avoid exactly this problem.\n",
         "| cell | runs | total collisions | collisions per run | total emergency brakings | "
         "emergency brakings per run |", "|---|---|---|---|---|---|"]
    tot_c = tot_e = 0
    for cell in sorted(per):
        rs = per[cell]
        c = sum(x["collisions"] for x in rs)
        e = sum(x["emergency_brakings"] for x in rs)
        tot_c += c
        tot_e += e
        L.append("| `%s` | %d | %d | %.1f | %d | %.1f |"
                 % (cell, len(rs), c, c / len(rs), e, e / len(rs)))
    L.append("\n**Totals: %d collisions, %d emergency brakings over %d runs.**\n"
             % (tot_c, tot_e, len(rows)))

    # which FLEET family do collisions belong to?
    fam = {}
    for r in rows:
        key = ("ACC" if "ACC" in r["cell"] and "CACC" not in r["cell"] else
               "CACC" if "CACC" in r["cell"] else
               "HUMAN_FAST" if "HUMAN_FAST" in r["cell"] else "HUMAN-family")
        d = fam.setdefault(key, [0, 0, 0])
        d[0] += 1
        d[1] += r["collisions"]
        d[2] += r["emergency_brakings"]
    L += ["## Rolled up by fleet family\n",
          "| fleet family involved | runs | collisions | emergency brakings |", "|---|---|---|---|"]
    for k, v in sorted(fam.items()):
        L.append("| %s | %d | %d | %d |" % (k, v[0], v[1], v[2]))

    # does the collision count correlate with the measured ACC discharge?
    try:
        import sys
        sys.path.insert(0, HERE)
        from analyze import load_all
        cells = load_all()
        L += ["\n## Does the collision count contaminate the ACC capacity estimate?\n",
              "| ACC cell | seed | collisions | measured discharge (veh/h) |", "|---|---|---|---|"]
        xs, ys = [], []
        for cell in sorted(cells):
            if not cell.startswith(("homo__ACC", "sweep__ACC", "arr__ACC")):
                continue
            for sd, r in cells[cell]:
                m = [x for x in rows if x["cell"] == cell and x["seed"] == "s%d" % sd]
                if not m or r["discharge"] != r["discharge"]:
                    continue
                L.append("| `%s` | %d | %d | %.1f |" % (cell, sd, m[0]["collisions"], r["discharge"]))
                xs.append(m[0]["collisions"])
                ys.append(r["discharge"])
        if len(xs) > 3:
            import numpy as np
            rho = float(np.corrcoef(xs, ys)[0, 1])
            L.append("\nCorrelation between a run's collision count and its measured discharge "
                     "across ACC cells: **r = %.3f** (n = %d).\n" % (rho, len(xs)))
    except Exception as e:
        L.append("\n(correlation not computed: %s)\n" % e)

    open(os.path.join(OUTDIR, "warning_audit.md"), "w").write("\n".join(L) + "\n")
    print("wrote warning_audit.csv / warning_audit.md ; totals: %d collisions, %d emergency brakings"
          % (tot_c, tot_e))
    for k, v in sorted(fam.items()):
        print("   %-14s runs=%3d collisions=%6d emergencyBraking=%6d" % (k, v[0], v[1], v[2]))


if __name__ == "__main__":
    main()
