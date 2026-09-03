"""Pilot: one cell end-to-end, to check timing, TLS verification, and the decision log."""
import json
import os
import sys
import time

from common import RUN_DIR
from build_net import build
import sim_rig

if __name__ == "__main__":
    t0 = time.time()
    net, meta = build("pilot", speed=19.44, grade_pct=0.0, lanes=2, arm=400.0)
    print("net built %.1fs  W=%.2f" % (time.time() - t0, meta["W_mean"]))
    cfg = dict(cycle=80.0, yellow=3.0, allred=1.0, vph=650, demand_end=1200,
               sim_end=1500, seed=1, step_length=0.1, warmup=240, ssm=True)
    rd = os.path.join(RUN_DIR, "pilot")
    t1 = time.time()
    log, recs = sim_rig.run_cell(rd, meta, cfg)
    print("sim %.1fs, %d decision records" % (time.time() - t1, len(recs)))
    m = sim_rig.read_metrics(rd)
    print(json.dumps(m, indent=2))
    s = sim_rig.read_ssm(rd)
    s.pop("pets"); s.pop("rear_ttcs")
    print(json.dumps(s, indent=2))
    from collections import Counter
    print(Counter(r["outcome"] for r in recs))
    v = json.load(open(os.path.join(rd, "tls_verify.json")))
    print("loaded program:", json.dumps(v["loaded_program"], indent=2)[:1200])
    print("phase changes:", v["n_phase_changes"], "green-end events:", v["n_green_end_events"])
