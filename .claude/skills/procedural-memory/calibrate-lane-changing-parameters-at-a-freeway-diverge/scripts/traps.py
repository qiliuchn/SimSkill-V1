#!/usr/bin/env python3
"""STEP 6 -- the three traps, each verified from raw SUMO output.

  T1  --lanechange.duration defaults to 0 (instantaneous, zero-width lane
      changes).  Turn it on and quantify what actually changes, and whether the
      calibrated vector transfers.
  T2  what SUMO really does to an exiting vehicle that fails to reach the exit
      lane before the gore -- forced by driving lcStrategic to the bottom of its
      range.  Report the observed MECHANISM, the count, and how it contaminates
      the LC statistics.
  T3  whether enabling the sublane model changes the meaning/effect of the same
      parameters, i.e. whether a calibration done with sublane off is valid with
      it on.

Usage: traps.py [t1|t2|t3|all]
"""
import os, sys, json, math, collections, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L
from lc_eval import evaluate_runs

SEEDS = tuple(1000 + 7 * i for i in range(8))
CALJ = os.path.join(L.TBL, "calibration.json")


def calibrated():
    if os.path.exists(CALJ):
        d = json.load(open(CALJ))
        return {k: float(v) for k, v in d["best_params"].items()}
    return None


def summarize(r):
    return dict(obj=r["obj"], rmsn_lane=r["rmsn_lane"], geh=r["geh"],
                geh_max=r["geh_max"], share=r["share"], dlc=r["dlc"],
                coop_rate=r["coop_rate"], strat_rate=r["strat_rate"],
                p85=r["p85"], p50=r["p50"], fail_frac=r["fail_frac"],
                flow=r["flow"], ramp_entered=r["ramp_entered"],
                E_entered=r["E_entered"], teleports=r["teleports"],
                tel_wrong=r["tel_wrong"], collisions=r["collisions"],
                depart_delay=r["depart_delay"], n_cohort=r["n_cohort"],
                n_nochange=r["n_nochange"])


def reason_table(reps):
    """Mean per-run reason counts over the measurement window."""
    tot = collections.Counter()
    n = 0
    for r in reps:
        if not r.get("ok"):
            continue
        n += 1
        for k, v in r["reason_counts"].items():
            tot[k] += v
    return {k: v / max(n, 1) for k, v in tot.items()}


def spatial_profile(wd, t0=L.WARMUP, t1=L.T_END_MEAS, bin_m=100.0):
    ev = L.parse_lanechanges(os.path.join(wd, "lanechanges.xml"))
    prof = collections.defaultdict(collections.Counter)
    for e in ev:
        if not (t0 <= e["t"] < t1):
            continue
        d = L.GORE_X - e["x"]
        if d < 0:
            continue
        b = int(d // bin_m) * bin_m
        prof[b][L.reason_class(e["reason"])] += 1
        prof[b]["all"] += 1
    return prof


# --------------------------------------------------------------------------
def t1(out):
    """--lanechange.duration 0 (SUMO default) vs 1 s vs 3 s."""
    print("\n===== T1: --lanechange.duration =====")
    cal = calibrated()
    rows = []
    for base_name, base in [("default", L.full_params())] + \
                           ([("calibrated", cal)] if cal else []):
        for dur in (0.0, 1.0, 3.0):
            p = dict(base); p["lcDuration"] = dur
            r = evaluate_runs([p], seeds=SEEDS, keep=True)[0]
            s = summarize(r)
            s["vector"] = base_name; s["lcDuration"] = dur
            s["reason_counts_mean"] = reason_table(r["reps"])
            s["lc_total_mean"] = sum(s["reason_counts_mean"].values())
            s["wd_seed0"] = r["reps"][0]["wd"]
            rows.append(s)
            print("  %-10s dur=%.1f  LC/run=%.0f  share=%s  geh_max=%.2f  "
                  "p85=%.0f  flow=%.0f  ramp=%.0f  E=%.0f  fail=%.4f"
                  % (base_name, dur, s["lc_total_mean"],
                     ["%.4f" % x for x in s["share"]], s["geh_max"], s["p85"],
                     s["flow"], s["ramp_entered"], s["E_entered"],
                     s["fail_frac"]))
    # spatial profile for default at dur 0 vs 3
    profs = {}
    for s in rows:
        if s["vector"] == "default" and s["lcDuration"] in (0.0, 3.0):
            pr = spatial_profile(s["wd_seed0"])
            profs["dur%.0f" % s["lcDuration"]] = {
                str(int(k)): dict(v) for k, v in sorted(pr.items())}
    out["t1"] = dict(rows=rows, spatial=profs, seeds=list(SEEDS))


def counts(r):
    return dict(loaded=r["loaded"], inserted=r["inserted"],
                running_end=r["running_end"], ended_total=r["ended_total"],
                halting_end=r["halting_end"])


def mechanism(wd):
    """Classify what SUMO actually did, from the run's own stderr + tripinfo."""
    err = open(os.path.join(wd, "stderr.txt")).read()
    msgs = collections.Counter()
    for line in err.splitlines():
        ls = line.strip()
        if not ls:
            continue
        if "Teleporting" in ls:
            msgs["Teleporting ... " + ls.split(";")[-1].strip()[:70]] += 1
        elif "Vehicle" in ls and "collision" in ls:
            msgs["collision"] += 1
        elif "emergency braking" in ls:
            msgs["emergency braking"] += 1
        else:
            msgs[ls[:80]] += 1
    tri = L.parse_tripinfo(os.path.join(wd, "tripinfo.xml"))
    ex = [t for t in tri if L.is_exiter(t["veh"])]
    thr = [t for t in tri if not L.is_exiter(t["veh"])]
    return dict(stderr_message_counts=dict(msgs.most_common(20)),
                exiter_arrival_lanes=dict(
                    collections.Counter(t["arrivalLane"] for t in ex).most_common()),
                through_arrival_lanes=dict(
                    collections.Counter(t["arrivalLane"] for t in thr).most_common()),
                n_tripinfo_exiters=len(ex), n_tripinfo_through=len(thr),
                stderr_head=err[:3000], wd=wd)


def t2(out):
    """Force the failure and identify the MECHANISM from raw output.

    SUMO's doc says a NEGATIVE lcStrategic disables strategic changing; values
    at/near 0 are checked too, because "near 0" and "disabled" turn out not to
    be the same thing at all.
    """
    print("\n===== T2: exiting vehicles that fail to reach the exit lane =====")
    cases = [(1.0, 1600.0), (0.30, 1600.0), (0.10, 1600.0), (0.05, 1600.0),
             (0.0, 1600.0), (-1.0, 1600.0), (-1.0, 400.0), (1.0, 2200.0)]
    rows = []
    for lcs, per_lane in cases:
        p = L.full_params(); p["lcStrategic"] = lcs
        ctx = dict(mainline_per_lane=per_lane)
        r = evaluate_runs([p], seeds=SEEDS[:4], ctx=ctx, keep=True)[0]
        s = summarize(r); s.update(counts(r))
        s["lcStrategic"] = lcs; s["per_lane"] = per_lane
        s["reason_counts_mean"] = reason_table(r["reps"])
        s["wd_seed0"] = r["reps"][0]["wd"]
        rows.append(s)
        print("  lcStrategic=%5.2f @%6.0f veh/h/ln : ramp=%7.1f E=%7.1f "
              "flow=%7.1f teleports=%6.1f (wrong-lane=%6.1f) loaded=%7.1f "
              "inserted=%7.1f running_end=%6.1f halting_end=%6.1f "
              "tripinfo-fail_frac=%s"
              % (lcs, per_lane, s["ramp_entered"], s["E_entered"], s["flow"],
                 s["teleports"], s["tel_wrong"], s["loaded"], s["inserted"],
                 s["running_end"], s["halting_end"],
                 ("%.4f" % s["fail_frac"]) if s["fail_frac"] == s["fail_frac"]
                 else "nan (see note)"))
    mech = {}
    for lcs, per_lane in [(-1.0, 400.0), (-1.0, 1600.0), (1.0, 2200.0)]:
        row = [r for r in rows if r["lcStrategic"] == lcs
               and r["per_lane"] == per_lane][0]
        mech["lcStrategic=%s_at_%dvphpl" % (lcs, int(per_lane))] = mechanism(
            row["wd_seed0"])
    print("\n  --- observed mechanism ---")
    for k, m in mech.items():
        print("  [%s]  wd=%s" % (k, m["wd"]))
        for kk, vv in list(m["stderr_message_counts"].items())[:6]:
            print("     %6d  %s" % (vv, kk))
        print("     exiter arrival lanes (COMPLETED trips only): %s"
              % dict(list(m["exiter_arrival_lanes"].items())[:6]))
        print("     through arrival lanes: %s"
              % dict(list(m["through_arrival_lanes"].items())[:6]))
    out["t2"] = dict(rows=rows, seeds=list(SEEDS[:4]), mechanism=mech,
                     note=("fail_frac is computed over tripinfo, which lists "
                           "ONLY COMPLETED trips -- when the failure gridlocks "
                           "the corridor the failing vehicles never complete "
                           "and the denominator collapses, so fail_frac is NaN "
                           "rather than 1. Use the summary/statistic counters "
                           "(loaded/inserted/running_end/teleports) instead."))


ARMS = [("LC2013 / sublane off", dict(lcmodel="LC2013")),
        ("SL2015 / sublane off", dict(lcmodel="SL2015")),
        ("SL2015 / sublane 0.8", dict(lcmodel="SL2015", sublane=0.8))]


def t3(out):
    """Sublane model with the SAME lc* parameter values.

    HARD CONSTRAINT found first (verified against the binary): SUMO refuses to
    run LC2013 under `--lateral-resolution` at all --
       "Error: Lane change model 'LC2013' is not compatible with sublane
        simulation"
    so "the same parameters with sublane on" is not even expressible: enabling
    the sublane model FORCES a switch to SL2015.  The comparison therefore has
    three arms so the model switch and the sublane switch are separated.
    """
    print("\n===== T3: sublane model =====")
    # 1. document the hard incompatibility from the binary itself
    wd = os.path.join(L.RUNS, "t3_incompat")
    r0 = L.run_scenario(wd, L.full_params(), seed=11, sublane=0.8,
                        lcmodel="LC2013")
    print("  LC2013 + --lateral-resolution 0.8 -> rc=%d : %s"
          % (r0.returncode, r0.stderr.strip().splitlines()[0]
             if r0.stderr.strip() else ""))
    incompat = dict(returncode=r0.returncode, stderr=r0.stderr.strip()[:400])

    cal = calibrated()
    vecs = [("default", L.full_params())] + ([("calibrated", cal)] if cal else [])
    rows = []
    for name, base in vecs:
        for arm, ctx in ARMS:
            p = dict(base); p["lcDuration"] = 0.0
            r = evaluate_runs([p], seeds=SEEDS[:6], ctx=ctx, keep=True)[0]
            if not r.get("ok"):
                print("  %-10s %-22s FAILED: %s"
                      % (name, arm, r["reps"][0].get("err", "")[:120]))
                rows.append(dict(vector=name, arm=arm, ok=False,
                                 err=str(r["reps"][0].get("err"))[:300]))
                continue
            s = summarize(r); s["vector"] = name; s["arm"] = arm; s["ok"] = True
            s["reason_counts_mean"] = reason_table(r["reps"])
            s["lc_total_mean"] = sum(s["reason_counts_mean"].values())
            rows.append(s)
            print("  %-10s %-22s LC/run=%6.0f share=%s geh_max=%5.2f %s "
                  "p85=%6.0f dlc=%.3f flow=%.0f fail=%.4f reasons=%s"
                  % (name, arm, s["lc_total_mean"],
                     "/".join("%.4f" % x for x in s["share"]), s["geh_max"],
                     "PASS" if s["geh_max"] < 5 else "FAIL", s["p85"],
                     s["dlc"], s["flow"], s["fail_frac"],
                     {k: round(v) for k, v in s["reason_counts_mean"].items()}))
    # does the SAME parameter change do the SAME thing under each arm?
    print("\n  -- same parameter, same change, each arm --")
    sens = []
    for pname, lo, hi in [("lcKeepRight", 0.0, 4.0), ("lcSpeedGain", 0.2, 4.0),
                          ("lcStrategic", 0.2, 4.0)]:
        for arm, ctx in ARMS:
            pl = []
            for v in (lo, hi):
                p = L.full_params(); p[pname] = v; p["lcDuration"] = 0.0
                pl.append(p)
            rr = evaluate_runs(pl, seeds=SEEDS[:4], ctx=ctx)
            if not (rr[0].get("ok") and rr[1].get("ok")):
                continue
            d = dict(param=pname, lo=lo, hi=hi, arm=arm,
                     share_lo=rr[0]["share"], share_hi=rr[1]["share"],
                     d_share0=rr[1]["share"][0] - rr[0]["share"][0],
                     p85_lo=rr[0]["p85"], p85_hi=rr[1]["p85"],
                     dlc_lo=rr[0]["dlc"], dlc_hi=rr[1]["dlc"])
            sens.append(d)
            print("    %-14s %-22s d(share_lane0)=%+.4f  p85 %6.0f->%6.0f  "
                  "dlc %.3f->%.3f" % (pname, arm, d["d_share0"],
                                      d["p85_lo"], d["p85_hi"],
                                      d["dlc_lo"], d["dlc_hi"]))
    out["t3"] = dict(rows=rows, sensitivity=sens, seeds=list(SEEDS[:6]),
                     lc2013_sublane_incompatibility=incompat)


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    outp = os.path.join(L.TBL, "traps.json")
    out = json.load(open(outp)) if os.path.exists(outp) else {}
    if which in ("t1", "all"):
        t1(out)
    if which in ("t2", "all"):
        t2(out)
    if which in ("t3", "all"):
        t3(out)
    json.dump(out, open(outp, "w"), indent=2, default=str)
    print("\nwrote", outp)


if __name__ == "__main__":
    main()
