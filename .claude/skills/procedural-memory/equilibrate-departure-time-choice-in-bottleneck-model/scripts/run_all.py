"""Orchestrator: run every equilibration stage, then the multi-seed evaluation."""
import os, sys, json, subprocess, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vickrey_lib import *

S = SCRIPTS
PY = sys.executable
ITERS = int(os.environ.get("VICK_ITERS", "300"))
COMMON = ["--scheme", "advect", "--iters", str(ITERS),
          "--eta0", "30", "--eta-m0", "80", "--diffuse", "0.04", "--frac-max", "0.25",
          "--rho", "0.3"]


def par(jobs):
    """jobs: list of (logfile, argv)"""
    procs = []
    for log, args in jobs:
        f = open(log, "w")
        procs.append((log, subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT), f))
    ok = True
    for log, p, f in procs:
        rc = p.wait(); f.close()
        print("   %-28s rc=%d" % (os.path.basename(log), rc), flush=True)
        if rc != 0:
            ok = False
            print(open(log).read()[-2000:])
    return ok


def eq(name, extra):
    return ("/tmp/eq_%s.log" % name,
            [PY, os.path.join(S, "equilibrate.py"), "--name", name] + COMMON + extra)


if __name__ == "__main__":
    stage = sys.argv[1]
    t0 = time.time()

    if stage == "1":
        # baseline + sensitivity + two alternative averaging schemes (robustness)
        assert par([
            eq("no_toll",  ["--toll", "none"]),
            eq("gamma4",   ["--toll", "none", "--gamma", "4.0"]),
            eq("alt_logit", ["--toll", "none"][:0] + ["--toll", "none", "--scheme", "logit",
                                                      "--theta-lo", "8", "--anneal", "200",
                                                      "--lam-exp", "0.6"]),
            eq("alt_eg",   ["--toll", "none", "--scheme", "eg", "--kappa", "3.0",
                            "--lam-exp", "0.6"]),
        ])

    elif stage == "2":
        subprocess.check_call([PY, os.path.join(S, "build_toll.py")])
        tv = os.path.join(WORK, "toll_timevarying.npy")
        zero = os.path.join(WORK, "toll_zero.npy")
        np.save(zero, np.zeros(NSLOT))
        assert par([
            eq("tv_toll",   ["--toll", "file:" + tv]),
            eq("zero_toll", ["--toll", "file:" + zero]),
        ])

    elif stage == "3":
        tv = json.load(open(os.path.join(WORK, "eq_tv_toll", "result.json")))
        rev = float(np.dot(np.array(tv["toll"]), np.array(tv["counts"], float)))
        flat = rev / N_COMMUTERS
        json.dump(dict(tv_revenue=rev, flat_toll=flat),
                  open(os.path.join(WORK, "flat_toll.json"), "w"), indent=2)
        print("time-varying toll revenue = %.0f cost-units -> equal-revenue flat toll = %.2f"
              % (rev, flat))
        assert par([eq("flat_toll", ["--toll", "flat:%.6f" % flat])])

    print("stage %s done in %.0f s" % (stage, time.time() - t0))
