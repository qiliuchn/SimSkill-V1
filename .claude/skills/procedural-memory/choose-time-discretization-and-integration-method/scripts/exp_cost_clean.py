"""Clean (SERIAL, unloaded-machine) wall-clock for each of the 16 factorial cells.

The wall-clock recorded inside exp_c_merge.py was measured with 8 worker processes
running concurrently, which inflates and distorts it.  The fidelity-vs-cost Pareto needs
an honest cost axis, so every cell is re-timed here one at a time, 3 repetitions each,
on the identical scenario (merge testbed, SSM + emissions devices enabled, same CRN seed).
"""
import os
import sys
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtcommon import (RUNS, cells, cell_id, cell_args, asl_value, run_sumo, BASE_ARGS,
                      vtype_xml, DEFAULT_CAR, mean, sd, savejson, NET)
import exp_c_merge as C                                     # noqa

REPS = 3
BASE = os.path.join(RUNS, "cost_clean")
os.makedirs(BASE, exist_ok=True)

if __name__ == "__main__":
    out = {}
    print("%-24s %10s %8s %12s" % ("cell", "wall_s", "sd", "RTF"))
    for c in cells():
        d = os.path.join(BASE, cell_id(c))
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        add = os.path.join(d, "add.xml")
        open(add, "w").write("<additional>%s</additional>"
                             % vtype_xml("car", DEFAULT_CAR, asl=asl_value(c), ssm=True))
        args = (["-n", C.MERGE, "-r", C.DEMAND, "-a", add,
                 "--tripinfo-output", os.path.join(d, "t.xml"),
                 "--summary-output", os.path.join(d, "s.xml"),
                 "--device.ssm.file", os.path.join(d, "ssm.xml"),
                 "--device.emissions.probability", "1.0",
                 "--begin", "0", "--end", str(C.END),
                 "--time-to-teleport", "300", "--max-depart-delay", "900",
                 "--collision.action", "warn", "--seed", "1001"] + cell_args(c) + BASE_ARGS)
        ws = []
        for _ in range(REPS):
            r = run_sumo(args, cwd=d)
            assert r["rc"] == 0, r["err"][-300:]
            ws.append(r["wall"])
        out[cell_id(c)] = dict(wall=mean(ws), wall_sd=sd(ws), rtf=C.END / mean(ws),
                               reps=REPS, walls=ws)
        print("%-24s %10.3f %8.3f %12.1f" % (cell_id(c), mean(ws), sd(ws), C.END / mean(ws)))
    savejson("cost_clean.json", out)
    print("\nwritten -> outputs/tables/cost_clean.json")
