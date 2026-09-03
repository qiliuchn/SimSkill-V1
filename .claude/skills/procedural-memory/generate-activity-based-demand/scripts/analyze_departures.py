"""
Departure-time histograms + peak-hour analysis for activity-based demand
(e.g. activitygen output) vs. a flat/control demand set (e.g. randomTrips).

Reads depart times straight from each routed .rou.xml's <vehicle depart=...>,
bins them (default 30 min), computes peak-hour fraction and AM/PM/midday
window shares for both, runs a bimodality check on the activity-based set,
and writes an overlay plot, a side-by-side plot, and CSV data.

Usage:
    python analyze_departures.py \
        --activity-rou activitygen.rou.xml --control-rou random.rou.xml \
        --out-dir plots/ --am-window 7,9 --pm-window 16,18 --midday-window 11,14
"""

import argparse
import csv
import os
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def parse_args():
    p = argparse.ArgumentParser(description="Compare departure-time distributions of two demand sets.")
    p.add_argument("--activity-rou", required=True)
    p.add_argument("--control-rou", required=True)
    p.add_argument("--out-dir", default="plots")
    p.add_argument("--day-seconds", type=float, default=86400)
    p.add_argument("--bin-seconds", type=float, default=1800)
    p.add_argument("--am-window", default="7,9", help="hour,hour (half-open) for the AM peak check")
    p.add_argument("--pm-window", default="16,18")
    p.add_argument("--midday-window", default="11,14")
    return p.parse_args()


def departs(path, day_seconds):
    d = []
    for _, el in ET.iterparse(path):
        if el.tag == "vehicle":
            dep = el.get("depart")
            if dep is not None:
                d.append(float(dep))
            el.clear()
    return np.array([x for x in d if 0 <= x < day_seconds])


def main():
    args = parse_args()
    am_lo, am_hi = (int(x) for x in args.am_window.split(","))
    pm_lo, pm_hi = (int(x) for x in args.pm_window.split(","))
    mid_lo, mid_hi = (int(x) for x in args.midday_window.split(","))
    day, binsec = args.day_seconds, args.bin_seconds
    nbins = int(day // binsec)

    ag = departs(args.activity_rou, day)
    rn = departs(args.control_rou, day)

    def hist_bins(d, n, rng):
        counts, _ = np.histogram(d, bins=n, range=rng)
        return counts

    ag_c = hist_bins(ag, nbins, (0, day))
    rn_c = hist_bins(rn, nbins, (0, day))
    ag_h = hist_bins(ag, 24, (0, day))
    rn_h = hist_bins(rn, 24, (0, day))

    def peak_hour_fraction(h):
        total = h.sum()
        return h.max() / total, int(h.argmax()), total

    def window_frac(h, lo, hi):
        return h[lo:hi].sum() / h.sum()

    ag_pf, ag_ph, ag_tot = peak_hour_fraction(ag_h)
    rn_pf, rn_ph, rn_tot = peak_hour_fraction(rn_h)
    ag_am, ag_pm, ag_mid = window_frac(ag_h, am_lo, am_hi), window_frac(ag_h, pm_lo, pm_hi), window_frac(ag_h, mid_lo, mid_hi)
    rn_am, rn_pm, rn_mid = window_frac(rn_h, am_lo, am_hi), window_frac(rn_h, pm_lo, pm_hi), window_frac(rn_h, mid_lo, mid_hi)

    mean_ag, mean_rn = ag_h.mean(), rn_h.mean()
    am_hours, pm_hours, mid_hours = ag_h[am_lo:am_hi + 1], ag_h[pm_lo:pm_hi + 1], ag_h[am_hi:pm_lo]
    am_peak_h = am_lo + int(am_hours.argmax())
    pm_peak_h = pm_lo + int(pm_hours.argmax())
    bimodal = (am_hours.max() >= 2 * mean_ag and pm_hours.max() >= 2 * mean_ag
               and mid_hours.min() < mean_ag and am_peak_h < pm_peak_h)
    cv_ag, cv_rn = ag_h.std() / ag_h.mean(), rn_h.std() / rn_h.mean()

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "departure_histogram_bins.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bin_start_hhmm", "bin_start_sec", "activity_count", "control_count"])
        for i in range(nbins):
            sec = i * binsec
            hhmm = f"{int(sec // 3600):02d}:{int((sec % 3600) // 60):02d}"
            w.writerow([hhmm, int(sec), int(ag_c[i]), int(rn_c[i])])
    with open(os.path.join(args.out_dir, "departure_hourly.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hour", "activity_count", "control_count"])
        for h in range(24):
            w.writerow([h, int(ag_h[h]), int(rn_h[h])])

    AG_COL, RN_COL = "#2f6fed", "#e5893b"
    centers = (np.arange(nbins) * binsec + binsec / 2) / 3600.0
    width = binsec / 3600.0

    fig, ax = plt.subplots(figsize=(11, 5.2), dpi=130)
    ax.bar(centers - width * 0.22, ag_c, width=width * 0.44, color=AG_COL, label=f"activity-based (n={ag_tot})")
    ax.bar(centers + width * 0.22, rn_c, width=width * 0.44, color=RN_COL, label=f"flat control (n={rn_tot})")
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 2))
    ax.set_xlabel("Departure time (hour of day)")
    ax.set_ylabel(f"Trips per {binsec / 60:.0f}-min bin")
    ax.set_title("Departure-time distribution: activity-based vs. flat control demand")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, "departure_histograms_overlay.png"))
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), dpi=130, sharey=True)
    for ax, c, col, title, tot in ((axes[0], ag_c, AG_COL, "activity-based", ag_tot),
                                    (axes[1], rn_c, RN_COL, "flat control", rn_tot)):
        ax.bar(centers, c, width=width * 0.9, color=col)
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 4))
        ax.set_xlabel("Hour of day")
        ax.set_title(f"{title}  (n={tot})", fontsize=11)
        ax.grid(axis="y", alpha=0.25)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axes[0].set_ylabel(f"Trips per {binsec / 60:.0f}-min bin")
    fig.suptitle("Same total demand, different temporal structure")
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, "departure_histograms_sidebyside.png"))
    plt.close(fig)

    print("=== DEPARTURE-TIME ANALYSIS ===")
    print(f"activity total trips: {ag_tot}   control total trips: {rn_tot}")
    print(f"activity busiest hour: {ag_ph:02d}:00 ({ag_pf * 100:.1f}% of day)   "
          f"control busiest hour: {rn_ph:02d}:00 ({rn_pf * 100:.1f}% of day)")
    print(f"activity AM({am_lo}-{am_hi}h)={ag_am * 100:.1f}%  PM({pm_lo}-{pm_hi}h)={ag_pm * 100:.1f}%  "
          f"midday({mid_lo}-{mid_hi}h)={ag_mid * 100:.1f}%")
    print(f"control  AM({am_lo}-{am_hi}h)={rn_am * 100:.1f}%  PM({pm_lo}-{pm_hi}h)={rn_pm * 100:.1f}%  "
          f"midday({mid_lo}-{mid_hi}h)={rn_mid * 100:.1f}%")
    print(f"hourly coefficient of variation: activity={cv_ag:.2f}  control={cv_rn:.2f}  (higher = peakier)")
    print(f"AM peak hour={am_peak_h:02d}:00 ({ag_h[am_peak_h]} trips, {ag_h[am_peak_h] / mean_ag:.1f}x mean)")
    print(f"PM peak hour={pm_peak_h:02d}:00 ({ag_h[pm_peak_h]} trips, {ag_h[pm_peak_h] / mean_ag:.1f}x mean)")
    print(f"BIMODAL (AM & PM each >=2x mean, midday trough < mean, AM before PM): {bimodal}")
    print("activity hourly counts:", list(ag_h))
    print("control  hourly counts:", list(rn_h))


if __name__ == "__main__":
    main()
