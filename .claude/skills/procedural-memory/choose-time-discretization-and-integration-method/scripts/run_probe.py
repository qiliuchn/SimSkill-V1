"""Re-run only the deterministic stop-line / acceleration probes of testbed (b)."""
import os
import sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exp_b_signal as E                      # noqa
from dtcommon import cells, savejson          # noqa

if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=8) as ex:
        probes = list(ex.map(E.probe_stopline, list(cells())))
    savejson("b_stopline_probe.json", probes)
    print("%-24s %11s %11s %11s %10s %10s %6s" %
          ("cell", "accErr_max", "accErr_set", "brakeOnset", "brakeDist", "rest_x", "over"))
    for p in probes:
        if not p.get("ok"):
            print(p)
            continue
        print("%-24s %11.4f %11.4f %11.3f %10.3f %10.4f %6s" %
              (p["cell"], p["accel_max_pos_err"], p["accel_settled_pos_err"],
               p["brake_onset_x"], p["brake_dist"], p["rest_x"], p["overshot"]))
    print("ideal (v^2/2b) brake dist = %.3f m" % probes[0]["ideal_brake_dist"])
