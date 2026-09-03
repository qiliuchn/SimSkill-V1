#!/usr/bin/env python3
"""Smoke test: one default-parameter run. Verifies runtime, insertion health,
the raw `reason` strings SUMO actually writes, laneData-vs-E1 agreement, and the
feature extractor."""
import os, sys, time, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L

wd = os.path.join(L.RUNS, "smoke")
p = L.full_params()
t = time.time()
r = L.run_scenario(wd, p, seed=101)
print("rc=%d  wall=%.1fs" % (r.returncode, time.time() - t))
print("STDERR tail:", r.stderr[-2000:])

ev = L.parse_lanechanges(os.path.join(wd, "lanechanges.xml"))
print("\ntotal LC events (whole run):", len(ev))
c = collections.Counter(e["reason"] for e in ev)
print("RAW reason strings:")
for k, v in c.most_common():
    print("   %-40s %d" % (repr(k), v))

f = L.extract_features(wd)
print("\nlaneData shares:", {k: round(v, 4) for k, v in f["share_ld"].items()})
print("E1       shares:", {k: round(v, 4) for k, v in f["share_e1"].items()})
print("entered_C:", f["entered_C"], " e1:", f["e1"])
print("station flow veh/h: %.1f" % f["flow_station_vph"])
print("dlc=%.4f coop=%.4f strat=%.4f  vehB=%.0f" % (f["dlc"], f["coop_rate"],
                                                    f["strat_rate"], f["veh_B"]))
print("reason counts (window):", f["reason_counts"])
print("reason counts (edge B):", f["reason_counts_B"])
print("p85=%.1f p50=%.1f n_dlast=%d n_nochange=%d n_cohort=%d fail=%d (%.4f)"
      % (f["p85"], f["p50"], f["n_dlast"], f["n_nochange"], f["n_cohort"],
         f["n_failed"], f["fail_frac"]))
print("teleports=%d (wrong-lane msgs=%d) collisions=%d loaded=%d inserted=%d "
      "notins=%d departDelay=%.2f" % (f["teleports"], f["teleports_wrong_lane"],
      f["collisions"], f["loaded"], f["inserted"], f["not_inserted"],
      f["depart_delay"]))
print("ramp entered=%.0f  E entered=%.0f" % (f["ramp_entered"], f["E_entered"]))
o = L.objective(f)
print("\nobjective:", json.dumps({k: (round(v, 4) if isinstance(v, float) else v)
                                 for k, v in o.items()}, default=str))
