#!/usr/bin/env python3
"""Traffic-flow finding or SUMO artifact?  The dedicated-lane bicycle penalty.

On identical demand and an identical (uncoordinated) signal plan, compares the
two geometry variants under SUMO's DEFAULT lane model and under the SUBLANE model
(--lateral-resolution 0.4, which restores in-lane overtaking):

  dedicated / default   one 2.0 m bicycle lane, strictly single file
  dedicated / sublane   same lane, bicycles may overtake laterally within it
  mixed     / default   bicycles share two 3.2 m general lanes (so they can
                        overtake each other by CHANGING LANES even without sublane)
  mixed     / sublane

If the dedicated lane's bicycle penalty largely disappears once in-lane
overtaking is allowed, the penalty is a property of SUMO's lane discretisation,
not of the infrastructure.

Also records each condition's bicycle progression speed so the mechanism is
visible, and the per-vClass route length so a routing artifact is ruled out.

Writes data/artifact_check.csv / .json.
"""
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A  # noqa: E402
import bikelib as B       # noqa: E402
import csvutil            # noqa: E402
import fcdbike            # noqa: E402
import scenario as S      # noqa: E402

SEEDS = [1, 2, 3]
WARM, END = 900.0, 5400.0
SUB = ["--lateral-resolution", "0.4"]


def prog_speed(fcd, variant, mode="bike"):
    sl_eb, sl_wb = S.stoplines(variant)
    recs = fcdbike.trips(fcd, S.XS, 90.0, t0=WARM + 60, xs_eb=sl_eb, xs_wb=sl_wb)
    tr = fcdbike.load(fcd)
    vs = []
    for x in recs:
        if x["mode"] != mode:
            continue
        tc, pts = x["t_cross"], tr[x["id"]]
        xl = sl_eb if x["dir"] == "EB" else sl_wb
        for i in range(len(tc) - 1):
            a, b = ((tc[i], tc[i + 1]) if x["dir"] == "EB"
                    else (tc[i + 1], tc[i]))
            if a is None or b is None or b <= a:
                continue
            seg = [q for q in pts if a <= q[0] <= b]
            if len(seg) < 3 or min(q[2] for q in seg) < fcdbike.STOP_V:
                continue
            vs.append(abs(xl[i + 1] - xl[i]) / (b - a))
    return (round(statistics.median(vs), 4), len(vs)) if vs else (None, 0)


def main():
    rows, blob = [], {}
    for variant in ("dedicated", "mixed"):
        for tag, extra in (("default", []), ("sublane", SUB)):
            plan = B.BikePlan(C=90., gX=22., gL=10., n_int=S.N_INT,
                              variant=variant, offs=[0.0] * S.N_INT)
            per = []
            vprog = None
            for sd in SEEDS:
                d = os.path.join(S.WORK, "artifact", variant, tag, "s%d" % sd)
                want_fcd = (sd == 1)
                r = S.evaluate(S.scen(variant), plan, d, seed=sd,
                               fcd=want_fcd, keep_fcd=want_fcd, warm=WARM,
                               end=END, extra=extra)
                per.append(r["stats"])
                if want_fcd:
                    vprog = prog_speed(r["fcd"], variant)
                    os.remove(r["fcd"])
            rec = dict(variant=variant, model=tag, n_seeds=len(per),
                       bike_progression_speed_mps=vprog[0],
                       n_unimpeded_links=vprog[1])
            for grp in ("bike_thru", "car_thru", "car_nonthru", "car_all"):
                for m in ("delay_per_km", "stops_per_km", "dur", "routeLength",
                          "speed", "zero_stop"):
                    vals = [p[grp][m] for p in per]
                    mean, hw, _, _ = A.tconf(vals)
                    rec["%s_%s" % (grp, m)] = round(mean, 4)
                    if m in ("delay_per_km", "stops_per_km"):
                        rec["%s_%s_ci" % (grp, m)] = round(hw, 4)
            rows.append(rec)
            blob["%s_%s" % (variant, tag)] = [
                {g: {k: v[g][k] for k in ("n", "delay_per_km", "stops_per_km",
                                          "routeLength", "speed")}
                 for g in ("bike_thru", "car_thru", "car_all")} for v in per]
            print("%-10s %-8s v_prog=%s  bike %6.2f s/km  car_thru %6.2f s/km  "
                  "car_all %6.2f s/km"
                  % (variant, tag, vprog[0], rec["bike_thru_delay_per_km"],
                     rec["car_thru_delay_per_km"], rec["car_all_delay_per_km"]))
    csvutil.write_csv(os.path.join(S.DATA, "artifact_check.csv"), rows)
    with open(os.path.join(S.DATA, "artifact_check.json"), "w") as f:
        json.dump(dict(seeds=SEEDS, per_seed=blob, agg=rows), f, indent=2)

    dd = [r for r in rows if r["variant"] == "dedicated" and r["model"] == "default"][0]
    ds = [r for r in rows if r["variant"] == "dedicated" and r["model"] == "sublane"][0]
    md = [r for r in rows if r["variant"] == "mixed" and r["model"] == "default"][0]
    gap = dd["bike_thru_delay_per_km"] - md["bike_thru_delay_per_km"]
    closed = dd["bike_thru_delay_per_km"] - ds["bike_thru_delay_per_km"]
    print("\ndedicated-minus-mixed bicycle delay penalty (default model): "
          "%.2f s/km" % gap)
    print("of which removed by enabling the sublane model on the dedicated "
          "lane: %.2f s/km (%.0f%%)" % (closed, 100 * closed / gap if gap else 0))


if __name__ == "__main__":
    main()
