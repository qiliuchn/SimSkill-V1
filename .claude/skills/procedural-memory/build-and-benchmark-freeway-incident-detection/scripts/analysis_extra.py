"""Supporting analyses:
  (a) extent of RECURRENT congestion on control days (the masking mechanism), per demand level
  (b) incidents downstream of the last station under coarse spacing
  (c) paired (McNemar) significance test of California #8 vs the naive baselines at matched FAR
  (d) illustrative time-space occupancy heatmaps, incident day vs its CRN-matched control
"""
import os, sys, json, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
import aid_algorithms as A
from score import load, evaluate, J0, J1
from report import load as load_sweep, best_at, ALGOS, NICE

OCC_CONG = 18.0     # occupancy above which a station-interval is called congested
os.makedirs(PLOTS_DIR, exist_ok=True)
out_lines = []


def say(s=""):
    print(s)
    out_lines.append(s)


def main():
    D = load_sweep()
    data = {lv: load(lv) for lv in DEMAND_LEVELS}

    # ---------------------------------------------------------- (a) recurrent congestion
    say("=== (a) RECURRENT congestion on incident-free CONTROL days ===")
    say("    (fraction of scored station-intervals with occupancy > %.0f%%)" % OCC_CONG)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for lv in DEMAND_LEVELS:
        _, ctl = data[lv]
        occ = np.stack([d["occ"][:, J0:J1] for d in ctl])       # days x stations x intervals
        frac_by_station = (occ > OCC_CONG).mean(axis=(0, 2))
        overall = (occ > OCC_CONG).mean()
        st = stations_for_spacing(250)
        say(f"  {lv:9s} overall={overall:6.3f}   per-station (x=1000..5750 m): " +
            " ".join(f"{frac_by_station[k]:.2f}" for k in st))
        ax.plot([STATION_X[k] for k in st], [frac_by_station[k] for k in st],
                marker="o", ms=4, label=f"{lv} ({sum(DEMAND_LEVELS[lv])} veh/h)")
    ax.set_xlabel("distance along mainline x (m)")
    ax.set_ylabel(f"share of intervals with occupancy > {OCC_CONG:.0f}%")
    ax.set_title("Recurrent congestion on incident-free control days\n"
                 "(downstream 3->2 lane drop at x = 6000 m)")
    ax.grid(alpha=.3); ax.legend()
    fig.tight_layout()
    p = os.path.join(PLOTS_DIR, "recurrent_congestion_control_days.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    say(f"  -> {p}")

    # ---------------------------------------------------------- (b) beyond last station
    say("\n=== (b) incidents relative to the LAST station, by spacing ===")
    for spacing in (250, 500, 1000):
        st = stations_for_spacing(spacing)
        last_x = STATION_X[st[-1]]
        inc, _ = data["moderate"]
        beyond = [d["meta"]["incident"]["x"] for d in inc
                  if d["meta"]["incident"]["x"] > last_x]
        say(f"  spacing {spacing:4d} m: {len(st):2d} stations, last at x={last_x:.0f} m, "
            f"{len(beyond):2d}/{len(inc)} incidents downstream of it")
        if beyond:
            for lv in DEMAND_LEVELS:
                sub = []
                for algo in ALGOS:
                    r = best_at(D[(lv, spacing, algo)], 0.05)
                    if r is None or "per_day" not in r:
                        continue
                    bl = [d for d in r["per_day"] if d["x"] > last_x]
                    if bl:
                        sub.append(f"{NICE[algo]}={sum(d['detected'] for d in bl)}/{len(bl)}")
                say(f"      detected among those, demand={lv}, FAR<=0.05: " + ", ".join(sub))

    # ---------------------------------------------------------- (c) paired significance
    say("\n=== (c) paired McNemar test, California #8 vs naive baselines "
        "(same seeds = CRN pairing), FAR<=0.05/det-hr ===")
    rows = []
    for lv in DEMAND_LEVELS:
        for spacing in (250, 500, 1000):
            ref = best_at(D[(lv, spacing, "california8")], 0.05)
            if ref is None or "per_day" not in ref:
                continue
            a = {d["seed"]: d["detected"] for d in ref["per_day"]}
            for algo in ("fixed_occ", "fixed_speed", "snd", "ewma"):
                r = best_at(D[(lv, spacing, algo)], 0.05)
                if r is None or "per_day" not in r:
                    say(f"  {lv:9s} sp{spacing:4d} {NICE[algo]:16s}: NO FEASIBLE OPERATING POINT "
                        f"at FAR<=0.05 (min FAR = "
                        f"{min(x['FAR_per_unit_hour'] for x in D[(lv, spacing, algo)]):.3f}/det-hr)")
                    rows.append(dict(level=lv, spacing=spacing, algo=algo, feasible=False))
                    continue
                b = {d["seed"]: d["detected"] for d in r["per_day"]}
                n01 = sum(1 for s in a if (not a[s]) and b[s])   # only baseline detects
                n10 = sum(1 for s in a if a[s] and (not b[s]))   # only California detects
                pv = stats.binomtest(n10, n10 + n01, 0.5).pvalue if (n10 + n01) > 0 else 1.0
                say(f"  {lv:9s} sp{spacing:4d} Cal8 vs {NICE[algo]:16s}: "
                    f"DR {ref['DR']:.2f} vs {r['DR']:.2f}  "
                    f"discordant Cal-only={n10:2d} base-only={n01:2d}  p={pv:.3f}"
                    f"{'  *' if pv < 0.05 else ''}")
                rows.append(dict(level=lv, spacing=spacing, algo=algo, feasible=True,
                                 dr_cal=ref["DR"], dr_other=r["DR"], n10=n10, n01=n01, p=pv))
    with open(os.path.join(RESULTS_DIR, "paired_tests.json"), "w") as f:
        json.dump(rows, f, indent=1)

    # ---------------------------------------------------------- (d) time-space heatmaps
    say("\n=== (d) time-space occupancy heatmaps ===")
    picks = [("low", None, "1-lane block, sub-capacity"),
             ("moderate", None, "near capacity"),
             ("high", None, "over capacity, recurrent queue")]
    for lv, _, note in picks:
        inc, ctl = data[lv]
        # pick a 1-lane-block incident far from its upstream station (the hard case)
        cand = sorted(range(len(inc)),
                      key=lambda i: -(inc[i]["meta"]["incident"]["offset"]
                                      if inc[i]["meta"]["incident"]["n_block"] == 1 else -1))
        i = cand[0]
        mi = inc[i]["meta"]; ic = mi["incident"]
        fig, axes = plt.subplots(1, 3, figsize=(16, 4.4))
        st = stations_for_spacing(250)
        ext = [0, SIM_END, STATION_X[st[-1]], STATION_X[st[0]]]
        for ax, (ttl, arr) in zip(axes, [("control day (same seed)", ctl[i]["occ"][st]),
                                         ("incident day", inc[i]["occ"][st]),
                                         ("difference", inc[i]["occ"][st] - ctl[i]["occ"][st])]):
            cm = "viridis" if "diff" not in ttl else "coolwarm"
            vm = dict(vmin=0, vmax=45) if "diff" not in ttl else dict(vmin=-25, vmax=25)
            im = ax.imshow(arr, aspect="auto", origin="upper", extent=ext, cmap=cm, **vm)
            ax.axhline(ic["x"], color="r", ls="--", lw=1)
            ax.axvline(mi["injected_t"], color="r", ls=":", lw=1)
            ax.axvline(mi["injected_t"] + ic["dur"], color="r", ls=":", lw=1)
            ax.set_title(ttl); ax.set_xlabel("time (s)")
            fig.colorbar(im, ax=ax, label="occupancy (%)")
        axes[0].set_ylabel("x (m)  [downstream = down]")
        fig.suptitle(f"demand={lv} ({note}) - {ic['n_block']}-lane block at x={ic['x']:.0f} m, "
                     f"t={mi['injected_t']:.0f}-{mi['injected_t']+ic['dur']:.0f} s "
                     f"(seed {mi['seed']})")
        fig.tight_layout()
        p = os.path.join(PLOTS_DIR, f"timespace_{lv}.png")
        fig.savefig(p, dpi=125); plt.close(fig)
        say(f"  -> {p}   (incident {ic['n_block']}-lane at x={ic['x']:.0f}, "
            f"offset {ic['offset']:.0f} m past its upstream station)")

    with open(os.path.join(RESULTS_DIR, "analysis_extra.txt"), "w") as f:
        f.write("\n".join(out_lines) + "\n")
    print("\nwrote", os.path.join(RESULTS_DIR, "analysis_extra.txt"))


if __name__ == "__main__":
    main()
