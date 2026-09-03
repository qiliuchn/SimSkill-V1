#!/usr/bin/env python3
"""Sub-goal 5: test the four explicit claims against the measured sweep,
using summary_by_cell.csv / summary_conflicts.csv (mean +/- 95% CI across 5
CRN seeds per variant x density cell). Prints a report; nothing here is
asserted from FHWA/NCHRP guidance -- every number is read back from the
per_run.csv / conflicts.csv this study's own SUMO runs produced."""
import csv
import os

import numpy as np
from scipy import stats as sstats

HERE = os.path.dirname(os.path.abspath(__file__))
DENSITIES = [5.0, 15.0, 30.0, 45.0]
VARIANTS = ["undivided", "twltl", "raised"]


def read_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def by_variant(rows):
    out = {}
    for r in rows:
        out.setdefault(r["variant"], []).append(r)
    for v in out:
        out[v].sort(key=lambda r: float(r["density"]))
    return out


def get(rows, key):
    return np.array([float(r[f"{key}__mean"]) for r in rows])


def raw_by_cell(per_run_rows):
    """dict[(variant,density)] -> list of raw per-seed values for a metric,
    used for paired seed-level significance tests (not just CI overlap).
    Density is normalized to float so lookups with DENSITIES (floats) match
    regardless of how csv.DictReader stringified the column."""
    d = {}
    for r in per_run_rows:
        d.setdefault((r["variant"], float(r["density"])), []).append(r)
    return d


def paired_ttest(rows_a, rows_b, key):
    a = sorted(rows_a, key=lambda r: r["seed"])
    b = sorted(rows_b, key=lambda r: r["seed"])
    assert [r["seed"] for r in a] == [r["seed"] for r in b], "seeds must be CRN-paired"
    va = np.array([float(r[key]) for r in a])
    vb = np.array([float(r[key]) for r in b])
    t, p = sstats.ttest_rel(va, vb)
    return va.mean(), vb.mean(), va.mean() - vb.mean(), p


def main():
    run_rows = by_variant(read_csv(os.path.join(HERE, "summary_by_cell.csv")))
    conf_rows = by_variant(read_csv(os.path.join(HERE, "summary_conflicts.csv")))
    per_run = read_csv(os.path.join(HERE, "per_run.csv"))
    per_run = [r for r in per_run if r["consolidate"] == "1"]
    conflicts_raw = read_csv(os.path.join(HERE, "conflicts.csv"))
    conflicts_raw = [r for r in conflicts_raw if r["consolidate"] == "1"]
    cells = raw_by_cell(per_run)
    conf_cells = raw_by_cell(conflicts_raw)

    print("=" * 78)
    print("CLAIM (i): does corridor delay/travel time degrade monotonically with")
    print("access density, and is the degradation linear or does it have a knee?")
    print("=" * 78)
    for v in VARIANTS:
        rows = run_rows[v]
        x = np.array(DENSITIES)
        y = get(rows, "through_mean_timeloss_s")
        slope, intercept, r, p, se = sstats.linregress(x, y)
        # second-difference test for convexity/knee: is the d30->d45 slope
        # meaningfully steeper than the d5->d15 slope?
        slope_lo = (y[1] - y[0]) / (x[1] - x[0])
        slope_hi = (y[3] - y[2]) / (x[3] - x[2])
        monotone = all(y[i + 1] >= y[i] - 1e-9 for i in range(len(y) - 1))
        print(f"  [{v:10s}] through timeLoss(s) at d=5/15/30/45: "
              f"{y[0]:.2f} / {y[1]:.2f} / {y[2]:.2f} / {y[3]:.2f}")
        print(f"               monotone non-decreasing: {monotone}; linear fit R^2={r**2:.3f}, "
              f"slope={slope:.4f} s per (pt/km/side)")
        print(f"               local slope d5->d15: {slope_lo:.4f} s/unit  vs  d30->d45: {slope_hi:.4f} s/unit "
              f"({'STEEPER at high density (knee/convex)' if slope_hi > 1.5 * slope_lo else 'roughly linear, no strong knee'})")
    print()
    print("  Access-side (driveway) mean travel time -- same test:")
    for v in VARIANTS:
        rows = run_rows[v]
        y = get(rows, "access_mean_traveltime_s")
        x = np.array(DENSITIES)
        slope, intercept, r, p, se = sstats.linregress(x, y)
        print(f"  [{v:10s}] access travel time(s) at d=5/15/30/45: "
              f"{y[0]:.2f} / {y[1]:.2f} / {y[2]:.2f} / {y[3]:.2f}  (R^2={r**2:.3f})")

    print()
    print("=" * 78)
    print("CLAIM (ii): does SSM conflict rate rise with access density the way the")
    print("access-management crash-rate literature asserts?")
    print("=" * 78)
    for v in VARIANTS:
        rows = conf_rows[v]
        x = np.array(DENSITIES)
        y = get(rows, "conflicts_per_Mvkm_total")
        slope, intercept, r, p, se = sstats.linregress(x, y)
        print(f"  [{v:10s}] total conflicts/Mvkm at d=5/15/30/45: "
              f"{y[0]:.0f} / {y[1]:.0f} / {y[2]:.0f} / {y[3]:.0f}  "
              f"slope={slope:.1f}/unit, R^2={r**2:.3f}, p={p:.4f}")
        for cat in ["left_turn_in_per_Mvkm", "left_turn_out_per_Mvkm", "right_turn_in_per_Mvkm"]:
            yc = get(rows, cat)
            s2, i2, r2, p2, se2 = sstats.linregress(x, yc)
            print(f"               {cat:28s}: {yc[0]:.0f}/{yc[1]:.0f}/{yc[2]:.0f}/{yc[3]:.0f}  "
                  f"slope={s2:.1f}, R^2={r2**2:.3f}, p={p2:.4f}")

    print()
    print("=" * 78)
    print("CLAIM (iii): is there a crossover density above which raised beats twltl")
    print("despite forcing U-turn detours (VMT up, VHT down again)?")
    print("=" * 78)
    xr = np.array(DENSITIES)
    vht_r = get(run_rows["raised"], "vht_h")
    vht_t = get(run_rows["twltl"], "vht_h")
    vmt_r = get(run_rows["raised"], "vmt_km")
    vmt_t = get(run_rows["twltl"], "vmt_km")
    diff = vht_r - vht_t
    print(f"  VHT(raised) - VHT(twltl) at d=5/15/30/45: "
          f"{diff[0]:+.1f} / {diff[1]:+.1f} / {diff[2]:+.1f} / {diff[3]:+.1f}  hours")
    print(f"  VMT(raised) - VMT(twltl) at d=5/15/30/45: "
          f"{(vmt_r-vmt_t)[0]:+.1f} / {(vmt_r-vmt_t)[1]:+.1f} / {(vmt_r-vmt_t)[2]:+.1f} / {(vmt_r-vmt_t)[3]:+.1f}  km")
    crossx = None
    for i in range(len(diff) - 1):
        if (diff[i] < 0) != (diff[i + 1] < 0):
            frac = -diff[i] / (diff[i + 1] - diff[i])
            crossx = xr[i] + frac * (xr[i + 1] - xr[i])
    if crossx:
        print(f"  --> VHT crossover interpolated at density ~= {crossx:.1f} pts/km/side")
    else:
        print("  --> no VHT sign-crossing in the tested [5,45] range "
              f"({'raised always higher VHT' if (diff>0).all() else 'raised always lower VHT' if (diff<0).all() else 'mixed, no clean interpolation'})")
    # paired significance at the two extremes
    for d in [5.0, 45.0]:
        m_r, m_t, dlt, p = paired_ttest(cells[("raised", d)], cells[("twltl", d)], "vht_h")
        print(f"  paired seed-level t-test VHT raised vs twltl @ d={d:.0f}: "
              f"raised={m_r:.1f}h twltl={m_t:.1f}h diff={dlt:+.1f}h p={p:.4g}")

    print()
    print("=" * 78)
    print("CLAIM (iv): does TWLTL actually buy anything over undivided at low")
    print("density, or only at high density?")
    print("=" * 78)
    for d in DENSITIES:
        for metric, label in [("through_mean_timeloss_s", "through delay(s)"),
                               ("access_mean_traveltime_s", "access travel time(s)"),
                               ("through_mean_stops", "through stops")]:
            m_u, m_t, dlt, p = paired_ttest(cells[("undivided", d)], cells[("twltl", d)], metric)
            sig = "SIGNIFICANT" if p < 0.05 else "n.s."
            better = "twltl better" if dlt > 0 else ("undivided better" if dlt < 0 else "tie")
            print(f"  d={d:5.1f}  {label:24s}  undivided={m_u:8.2f}  twltl={m_t:8.2f}  "
                  f"diff(undiv-twltl)={dlt:+8.2f}  p={p:.4g}  [{sig}, {better}]")
        # also compare conflict rate (safety side of "does it buy anything")
        m_u, m_t, dlt, p = paired_ttest(conf_cells[("undivided", d)], conf_cells[("twltl", d)],
                                         "conflicts_per_Mvkm_total")
        sig = "SIGNIFICANT" if p < 0.05 else "n.s."
        print(f"  d={d:5.1f}  conflicts/Mvkm            undivided={m_u:8.0f}  twltl={m_t:8.0f}  "
              f"diff(undiv-twltl)={dlt:+8.0f}  p={p:.4g}  [{sig}]")
        print()


if __name__ == "__main__":
    main()
