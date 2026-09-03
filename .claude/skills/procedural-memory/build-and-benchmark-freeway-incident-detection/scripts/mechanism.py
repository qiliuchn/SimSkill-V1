"""WHY does a trivial single-station threshold beat the comparative California algorithm here?

Hypothesis: under SUMO's default Krauss car-following, RECURRENT congestion relaxes into a
smooth, low-variance queue whose spot speed/occupancy stay well away from the standing-queue
values produced by a fully stopped blocker. In the field the two overlap heavily (recurrent
stop-and-go routinely produces near-zero spot speeds), which is the entire reason
comparative spatial-difference algorithms exist. If the two distributions are separable by a
single scalar in SUMO, the comparative machinery buys nothing.

This script measures that separability directly instead of assuming it.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from score import load, J0, J1

lines = []
def say(s=""):
    print(s); lines.append(s)


def main():
    say("=== Separability of recurrent congestion vs incident queue (station-interval level) ===")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    summary = {}
    for lv in DEMAND_LEVELS:
        inc, ctl = load(lv)
        # A: recurrent-congestion population = control-day station-intervals that are congested
        occ_c = np.stack([d["occ"][:, J0:J1] for d in ctl])
        spd_c = np.stack([np.nan_to_num(d["spd"][:, J0:J1], nan=33.33) for d in ctl])
        cong = spd_c < 25.0                       # anything meaningfully below free flow
        recur_occ = occ_c[cong]
        recur_spd = spd_c[cong]

        # B: incident-queue population = the station immediately upstream of the incident,
        #    during the incident window, on incident days
        iq_occ, iq_spd = [], []
        for d in inc:
            m = d["meta"]; ic = m["incident"]
            j0 = int(m["injected_t"] // DET_PERIOD) + 1
            j1 = int((m["injected_t"] + ic["dur"]) // DET_PERIOD)
            k = ic["seg"]                          # detector at pos 5 of the incident's own edge
            iq_occ.append(d["occ"][k, j0:j1])
            iq_spd.append(np.nan_to_num(d["spd"][k, j0:j1], nan=33.33))
        iq_occ = np.concatenate(iq_occ); iq_spd = np.concatenate(iq_spd)

        def q(a, p):
            return float(np.percentile(a, p)) if len(a) else float("nan")

        say(f"\n-- demand={lv}")
        say(f"   recurrent congestion  n={len(recur_occ):6d}  occ p50/p90/p99 = "
            f"{q(recur_occ,50):5.1f}/{q(recur_occ,90):5.1f}/{q(recur_occ,99):5.1f} %   "
            f"speed p50/p10/p1 = {q(recur_spd,50):5.1f}/{q(recur_spd,10):5.1f}/{q(recur_spd,1):5.1f} m/s")
        say(f"   incident queue        n={len(iq_occ):6d}  occ p50/p90/p99 = "
            f"{q(iq_occ,50):5.1f}/{q(iq_occ,90):5.1f}/{q(iq_occ,99):5.1f} %   "
            f"speed p50/p10/p1 = {q(iq_spd,50):5.1f}/{q(iq_spd,10):5.1f}/{q(iq_spd,1):5.1f} m/s")
        # overlap of the two populations under the best single scalar cut
        for nm, a, b, sign in (("occupancy", recur_occ, iq_occ, +1), ("speed", recur_spd, iq_spd, -1)):
            cuts = np.unique(np.concatenate([a, b]))
            best = max(((((sign * b >= sign * c).mean() + (sign * a < sign * c).mean()) / 2), c)
                       for c in cuts[::max(1, len(cuts)//400)])
            say(f"   best single-scalar {nm:10s} cut = {best[1]:6.1f}  -> balanced accuracy "
                f"{best[0]*100:5.1f}%  (50% = inseparable)")
            summary[(lv, nm)] = best
        # stop-and-go check: how oscillatory is SUMO's recurrent congestion?
        if len(recur_spd):
            osc = []
            for d in ctl:
                s = np.nan_to_num(d["spd"][:, J0:J1], nan=33.33)
                m = s < 25.0
                for k in range(s.shape[0]):
                    if m[k].sum() >= 6:
                        osc.append(np.std(s[k][m[k]]) / max(np.mean(s[k][m[k]]), 1e-6))
            say(f"   CV of spot speed WITHIN congested station-series (stop-and-go proxy): "
                f"mean={np.mean(osc):.3f} (n={len(osc)})")
            say(f"   share of congested station-intervals with speed < 8 m/s: "
                f"{(recur_spd < 8).mean()*100:.1f}%   (incident queue: {(iq_spd < 8).mean()*100:.1f}%)")

        ax = axes[0]
        ax.hist(recur_occ, bins=60, range=(0, 60), density=True, histtype="step", lw=1.6,
                label=f"recurrent, {lv}")
        ax.hist(iq_occ, bins=60, range=(0, 60), density=True, histtype="step", lw=1.6, ls="--",
                label=f"incident queue, {lv}")
        ax = axes[1]
        ax.hist(recur_spd, bins=60, range=(0, 34), density=True, histtype="step", lw=1.6,
                label=f"recurrent, {lv}")
        ax.hist(iq_spd, bins=60, range=(0, 34), density=True, histtype="step", lw=1.6, ls="--",
                label=f"incident queue, {lv}")
    axes[0].set_xlabel("station occupancy (%)"); axes[0].set_ylabel("density")
    axes[1].set_xlabel("station space-mean speed (m/s)")
    for a in axes:
        a.grid(alpha=.3); a.legend(fontsize=7)
    fig.suptitle("Why a single-station threshold suffices in SUMO: recurrent congestion and\n"
                 "incident-queue signatures barely overlap under default Krauss car-following")
    fig.tight_layout()
    p = os.path.join(PLOTS_DIR, "mechanism_separability.png")
    fig.savefig(p, dpi=130); plt.close(fig)
    say(f"\n-> {p}")
    with open(os.path.join(RESULTS_DIR, "mechanism.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
