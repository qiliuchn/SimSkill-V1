#!/usr/bin/env python3
"""
Re-run a named subset of arms with the FIXED gen_freight.py (attempt-2 correction).

Usage:  python3 rerun_arms.py E2_hgv25 E2_hgv50 E2_hgv75      (arm-group prefixes)

Deletes the arm's run directory first so run_arm.run()'s DONE-file short-circuit
does not skip it, then re-generates its demand and re-simulates all 8 seeds.
"""
import os, sys, json, shutil, time
from concurrent.futures import ProcessPoolExecutor
from common import *   # noqa
import experiments as ex


def main():
    prefixes = sys.argv[1:] or ["E2_hgv25", "E2_hgv50", "E2_hgv75"]
    arms = [a for a in ex.build_arms()
            if any(a["arm"].rsplit("_s", 1)[0] == p for p in prefixes)]
    print("re-running %d arms: %s" % (len(arms), sorted({a['arm'].rsplit('_s',1)[0] for a in arms})))
    for a in arms:
        d = os.path.join(RUNS, a["arm"])
        if os.path.exists(d):
            shutil.rmtree(d)
    t0 = time.time()
    res = []
    with ProcessPoolExecutor(max_workers=8) as pool:
        for r in pool.map(ex.run_one, arms):
            res.append(r)
            print("  %-18s parcels=%s unservable=%s tours=%s err=%s"
                  % (r.get("arm"), r.get("parcels_delivered"),
                     r.get("addresses_unservable"), r.get("frt_n"), r.get("error", "-")))
    out = os.path.join(TAB, "arm_metrics_rerun_%s.json" % "_".join(prefixes))
    json.dump(res, open(out, "w"), indent=1, default=str)
    bad = [r for r in res if "error" in r]
    print("done in %.0f s; %d arms, %d errors -> %s" % (time.time() - t0, len(res), len(bad), out))


if __name__ == "__main__":
    main()
