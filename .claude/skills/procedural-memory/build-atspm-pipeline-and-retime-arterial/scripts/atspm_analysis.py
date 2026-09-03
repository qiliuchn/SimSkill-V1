#!/usr/bin/env python3
"""ATSPM measures computed from the enumerated event log ALONE.

INPUTS (the only two files this script is permitted to open):
  outputs/logs/events_<tag>.csv    -- the high-resolution controller event log
  outputs/det/detector_config.csv  -- detector configuration metadata
                                      (channel -> signal / phase / movement),
                                      which every real ATSPM deployment stores.

It reads NO simulator state: no tripinfo, no queue file, no network, no timing
plan. Cycle length, green/red boundaries, splits and offsets are all RECOVERED
from the event log itself.

MEASURES
  1. Purdue Coordination Diagram (PCD): advance-detector arrival time-in-cycle
     vs. time of day, with the per-cycle green band overlaid.
  2. Percent Arrival on Green (AoG) and Platoon Ratio PR = AoG / (g/C).
     Reported both raw (detector actuation time, the field convention) and
     setback-corrected, where the setback travel time is itself ESTIMATED FROM
     THE LOG (5th percentile of advance-on -> next stop-bar-on lag).
  3. Split failure via GOR5 / ROR5 on stop-bar presence detectors:
        GOR5 = occupancy ratio over the first 5 s of green
        ROR5 = occupancy ratio over the first 5 s of red
        flag  = GOR5 >= 0.80 AND ROR5 >= 0.80
  4. Approach volume and effective green utilisation.

OUTPUTS
  outputs/atspm/cycles_<tag>.csv        per phase-green instance
  outputs/atspm/coordination_<tag>.csv  per signal x direction summary
  outputs/atspm/pcd_points_<tag>.csv    every plotted PCD arrival
  outputs/plots/pcd_<tag>.png
"""
import argparse
import csv
import os
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

E_GREEN, E_YELLOW, E_RED = 1, 8, 10
E_DET_OFF, E_DET_ON = 81, 82
COORD_PHASE = {"EB": 6, "WB": 2}
GOR_ROR_WINDOW = 5.0
SF_THRESHOLD = 0.80
PHASE_MOVEMENT = {1: "EBL", 2: "WBT", 3: "SBL", 4: "NBT", 5: "WBL", 6: "EBT", 7: "NBL", 8: "SBT"}


class Occupancy:
    """Per-channel on/off intervals reconstructed from 81/82 events."""

    def __init__(self, on_off_events, t_end):
        starts, ends = [], []
        cur = None
        for t, code in on_off_events:
            if code == E_DET_ON and cur is None:
                cur = t
            elif code == E_DET_OFF and cur is not None:
                starts.append(cur); ends.append(t); cur = None
        if cur is not None:
            starts.append(cur); ends.append(t_end)
        self.s = np.array(starts); self.e = np.array(ends)

    def occ(self, a, b):
        if b <= a or len(self.s) == 0:
            return 0.0
        i = np.searchsorted(self.e, a, side="right")
        jm = np.searchsorted(self.s, b, side="left")
        if jm <= i:
            return 0.0
        ov = np.minimum(self.e[i:jm], b) - np.maximum(self.s[i:jm], a)
        return float(np.clip(ov, 0, None).sum() / (b - a))

    def n_on(self, a, b):
        return int(np.sum((self.s >= a) & (self.s < b)))


def load(tag):
    ev_path = os.path.join(ROOT, "outputs", "logs", f"events_{tag}.csv")
    cfg_path = os.path.join(ROOT, "outputs", "det", "detector_config.csv")
    cfg = list(csv.DictReader(open(cfg_path)))
    chan = {}
    for r in cfg:
        chan[(r["signal_id"], int(r["channel"]))] = r
    phase_ev = defaultdict(list)     # (sig, phase) -> [(t, code)]
    det_ev = defaultdict(list)       # (sig, channel) -> [(t, code)]
    t_end = 0.0
    with open(ev_path) as f:
        rd = csv.reader(f); next(rd)
        for t, sig, code, param in rd:
            t = float(t); code = int(code); param = int(param)
            t_end = t
            if code in (E_DET_ON, E_DET_OFF):
                det_ev[(sig, param)].append((t, code))
            elif code in (E_GREEN, E_YELLOW, E_RED):
                phase_ev[(sig, param)].append((t, code))
    occ = {k: Occupancy(v, t_end) for k, v in det_ev.items()}
    return cfg, chan, phase_ev, occ, t_end


def phase_instances(phase_ev, sig, p):
    """[(green_start, green_end/yellow_start, red_start)] for one phase."""
    out = []
    gs = ge = None
    for t, code in phase_ev[(sig, p)]:
        if code == E_GREEN:
            gs = t; ge = None
        elif code == E_YELLOW and gs is not None:
            ge = t
        elif code == E_RED and gs is not None and ge is not None:
            out.append((gs, ge, t)); gs = ge = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--warmup", type=float, default=600.0)
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args()

    cfg, chan, phase_ev, occ, t_end = load(args.tag)
    signals = sorted({r["signal_id"] for r in cfg})
    outd = os.path.join(ROOT, "outputs", "atspm")
    os.makedirs(outd, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "outputs", "plots"), exist_ok=True)

    stopbar = defaultdict(list)   # (sig, phase) -> [channel]
    advance = defaultdict(list)   # (sig, dir) -> [channel]
    for r in cfg:
        c = int(r["channel"])
        if r["det_class"] == "stopbar":
            stopbar[(r["signal_id"], int(r["phase"]))].append(c)
        else:
            advance[(r["signal_id"], r["approach_dir"])].append(c)

    # ---------------- 1-2. coordination: PCD, AoG, platoon ratio ----------------
    coord_rows = [("signal_id", "direction", "coord_phase", "cycles", "cycle_len_s",
                   "mean_green_s", "gC_ratio", "arrivals", "arrivals_per_h",
                   "AoG_pct_raw", "PR_raw", "setback_tt_est_s", "AoG_pct_corr", "PR_corr")]
    pcd_rows = [("signal_id", "direction", "cycle_idx", "cycle_start_s", "green_len_s",
                 "cycle_len_s", "arrival_t_s", "time_in_cycle_s", "on_green")]
    pcd_data = {}
    for sig in signals:
        for d, cp in COORD_PHASE.items():
            inst = [x for x in phase_instances(phase_ev, sig, cp) if x[0] >= args.warmup]
            if len(inst) < 3:
                continue
            gstarts = np.array([x[0] for x in inst])
            glens = np.array([x[1] - x[0] for x in inst])
            clens = np.diff(gstarts)
            C = float(np.median(clens))

            adv_ch = advance[(sig, d)]
            arr = np.sort(np.concatenate([occ[(sig, c)].s for c in adv_ch if (sig, c) in occ]))
            arr = arr[(arr >= gstarts[0]) & (arr < gstarts[-1])]

            # Setback travel time, ESTIMATED FROM THE LOG ALONE.
            # Per LANE, take advance-on events that are ISOLATED (no other advance
            # actuation on that lane within +/-8 s) and whose lane stop-bar detector
            # was unoccupied at that instant -- then the next stop-bar rising edge on
            # the same lane is almost certainly the same vehicle. The 10th percentile
            # of those lags approximates the free-flow setback travel time.
            lags = []
            for ac in advance[(sig, d)]:
                lane = chan[(sig, ac)]["lane"]
                sc = [c for c in stopbar[(sig, cp)] if chan[(sig, c)]["lane"] == lane]
                if not sc or (sig, ac) not in occ:
                    continue
                A = occ[(sig, ac)].s
                S = occ[(sig, sc[0])]
                if len(A) < 3:
                    continue
                iso = np.ones(len(A), bool)
                iso[1:] &= np.diff(A) > 8.0
                iso[:-1] &= np.diff(A) > 8.0
                for a in A[iso]:
                    if S.occ(a - 0.1, a + 0.1) > 0:      # stop-bar already busy -> ambiguous
                        continue
                    nxt = S.s[np.searchsorted(S.s, a, "left"):][:1]
                    if len(nxt) and 0 < nxt[0] - a < 60:
                        lags.append(nxt[0] - a)
            tt = float(np.percentile(lags, 10)) if len(lags) > 30 else 0.0

            def summarize(shift):
                ci = np.searchsorted(gstarts, arr + shift, side="right") - 1
                good = (ci >= 0) & (ci < len(glens))
                tic = (arr + shift)[good] - gstarts[ci[good]]
                ong = tic < glens[ci[good]]
                return ci[good], tic, ong, arr[good]

            ci0, tic0, ong0, arr0 = summarize(0.0)
            _, _, ongc, _ = summarize(tt)
            gC = float(np.mean(glens) / C)
            aog_raw = 100.0 * ong0.mean() if len(ong0) else 0.0
            aog_cor = 100.0 * ongc.mean() if len(ongc) else 0.0
            dur_h = (gstarts[-1] - gstarts[0]) / 3600.0
            coord_rows.append((sig, d, cp, len(inst), f"{C:.1f}", f"{glens.mean():.1f}",
                               f"{gC:.3f}", len(arr), f"{len(arr)/dur_h:.0f}",
                               f"{aog_raw:.1f}", f"{(aog_raw/100)/gC:.3f}", f"{tt:.2f}",
                               f"{aog_cor:.1f}", f"{(aog_cor/100)/gC:.3f}"))
            for k in range(len(tic0)):
                pcd_rows.append((sig, d, int(ci0[k]), f"{gstarts[ci0[k]]:.1f}",
                                 f"{glens[ci0[k]]:.1f}", f"{C:.1f}", f"{arr0[k]:.1f}",
                                 f"{tic0[k]:.2f}", int(ong0[k])))
            pcd_data[(sig, d)] = dict(gstarts=gstarts, glens=glens, C=C, arr=arr0,
                                      tic=tic0, ci=ci0, ong=ong0, aog=aog_raw,
                                      pr=(aog_raw / 100) / gC, gC=gC, tt=tt)

    # ---------------- 3-4. split failure, volume, green utilisation ----------------
    cyc_rows = [("signal_id", "phase", "movement", "green_start_s", "green_end_s", "red_start_s",
                 "green_len_s", "GOR5", "ROR5", "split_failure", "sf_refined", "sf_sustained",
                 "occ_tail10", "green_util", "volume_veh", "n_detectors", "det_length_m")]
    for sig in signals:
        for p in range(1, 9):
            chs = [c for c in stopbar[(sig, p)] if (sig, c) in occ]
            if not chs:
                continue
            dlen = float(chan[(sig, chs[0])]["length_m"])
            block = []
            for gs, ge, rs in phase_instances(phase_ev, sig, p):
                if gs < args.warmup:
                    continue
                gor = np.mean([occ[(sig, c)].occ(gs, gs + GOR_ROR_WINDOW) for c in chs])
                ror = np.mean([occ[(sig, c)].occ(rs, rs + GOR_ROR_WINDOW) for c in chs])
                # continuity of occupancy across the end of green into red: a genuine
                # residual queue is still DISCHARGING over the detector right up to the
                # end of green, whereas a fresh arrival that stops for the red leaves a
                # gap. This distinguishes the two, using only the event log.
                tail = np.mean([occ[(sig, c)].occ(ge - 10.0, rs + GOR_ROR_WINDOW) for c in chs])
                util = np.mean([occ[(sig, c)].occ(gs, ge) for c in chs])
                vol = sum(occ[(sig, c)].n_on(gs, rs) for c in chs)
                std = int(gor >= SF_THRESHOLD and ror >= SF_THRESHOLD)
                ref = int(std and tail >= 0.90)
                block.append([sig, p, PHASE_MOVEMENT[p], f"{gs:.1f}", f"{ge:.1f}", f"{rs:.1f}",
                              f"{ge-gs:.1f}", f"{gor:.3f}", f"{ror:.3f}", std, ref, 0,
                              f"{tail:.3f}", f"{util:.3f}", vol, len(chs), f"{dlen:.1f}"])
            # "sustained" = the field rule that an isolated failed cycle is not
            # actionable: >=3 of any 5 consecutive cycles flagged.
            fl = [r[9] for r in block]
            for i in range(len(block)):
                lo, hi = max(0, i - 2), min(len(fl), i + 3)
                block[i][11] = int(fl[i] == 1 and sum(fl[lo:hi]) >= 3)
            cyc_rows.extend(tuple(r) for r in block)

    for name, rows in (("coordination", coord_rows), ("cycles", cyc_rows), ("pcd_points", pcd_rows)):
        with open(os.path.join(outd, f"{name}_{args.tag}.csv"), "w", newline="") as f:
            csv.writer(f).writerows(rows)

    # ---------------- console summary ----------------
    print(f"\n{'='*96}\nATSPM SUMMARY  (run '{args.tag}')  -- computed from the event log alone\n{'='*96}")
    print("\nCOORDINATION (Purdue) per signal x direction")
    hdr = ("sig", "dir", "cyc", "C", "green", "g/C", "arr/h", "AoG%", "PR", "setbk", "AoG%c", "PRc")
    print("  " + " ".join(f"{h:>6s}" for h in hdr))
    for r in coord_rows[1:]:
        print("  " + " ".join(f"{str(x):>6s}" for x in
                              (r[0], r[1], r[3], r[4], r[5], r[6], r[8], r[9], r[10], r[11], r[12], r[13])))
    print("\n  Platoon Ratio interpretation (HCM): PR<0.85 poor progression, ~1.0 random,")
    print("  1.15-1.5 favourable, >1.5 highly favourable.")

    print("\nSPLIT FAILURE by signal x phase   sf_std = GOR5>=0.80 AND ROR5>=0.80;")
    print("  sf_ref adds occupancy-continuity across end-of-green; sf_sus adds the 3-of-5 rule")
    print(f"  {'sig':4s} {'ph':3s} {'mvmt':5s} {'det_m':6s} {'cyc':5s} {'sf_std%':8s} {'sf_ref%':8s} "
          f"{'sf_sus%':8s} {'GOR5':6s} {'ROR5':6s} {'tail':6s} {'g_util':7s} {'sb_vol/h':9s}")
    agg = defaultdict(list)
    for r in cyc_rows[1:]:
        agg[(r[0], r[1], r[2], r[16])].append(r)
    for (sig, p, mv, dlen), rs in sorted(agg.items()):
        n = len(rs)
        dur_h = (float(rs[-1][3]) - float(rs[0][3])) / 3600.0
        print(f"  {sig:4s} {str(p):3s} {mv:5s} {dlen:6s} {n:5d} "
              f"{100*sum(int(x[9]) for x in rs)/n:7.1f}% {100*sum(int(x[10]) for x in rs)/n:7.1f}% "
              f"{100*sum(int(x[11]) for x in rs)/n:7.1f}% "
              f"{np.mean([float(x[7]) for x in rs]):6.3f} {np.mean([float(x[8]) for x in rs]):6.3f} "
              f"{np.mean([float(x[12]) for x in rs]):6.3f} "
              f"{np.mean([float(x[13]) for x in rs]):7.3f} {sum(int(x[14]) for x in rs)/dur_h:9.0f}")

    print("\nVOLUME SOURCE CHECK -- stop-bar PRESENCE detectors vs advance COUNT detectors")
    print("  (coordinated through movements only; a presence zone cannot resolve vehicles")
    print("   inside a discharging platoon, so it structurally under-counts)")
    print(f"  {'sig':4s} {'dir':4s} {'advance veh/h':>14s} {'stop-bar veh/h':>15s} {'ratio':>7s}")
    for r in coord_rows[1:]:
        sig, d, cp = r[0], r[1], r[2]
        rs = agg.get((sig, cp, PHASE_MOVEMENT[cp], "15.0"))
        if not rs:
            continue
        dur_h = (float(rs[-1][3]) - float(rs[0][3])) / 3600.0
        sb = sum(int(x[14]) for x in rs) / dur_h
        adv = float(r[8])
        print(f"  {sig:4s} {d:4s} {adv:14.0f} {sb:15.0f} {sb/adv:7.2f}")

    if args.plot:
        plot_pcd(pcd_data, args.tag)
    return pcd_data


def plot_pcd(pcd, tag):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    SURF, INK, MUTED = "#fcfcfb", "#0b0b0b", "#52514e"
    GREEN_FILL, GREEN_LINE = "#c9e8c9", "#0ca30c"
    DOT = "#2a78d6"
    signals = sorted({k[0] for k in pcd})
    dirs = ["EB", "WB"]
    fig, axes = plt.subplots(len(dirs), len(signals), figsize=(4.1 * len(signals), 3.5 * len(dirs)),
                             sharey=True, facecolor=SURF)
    for i, d in enumerate(dirs):
        for j, sig in enumerate(signals):
            ax = axes[i][j]
            ax.set_facecolor(SURF)
            k = pcd.get((sig, d))
            if k is None:
                ax.axis("off"); continue
            x = k["gstarts"] / 3600.0
            ax.fill_between(x, 0, k["glens"], color=GREEN_FILL, step="post",
                            label="green (coordinated phase)", zorder=1)
            ax.step(x, k["glens"], where="post", color=GREEN_LINE, lw=2,
                    label="end of green", zorder=3)
            ax.scatter(k["arr"] / 3600.0, k["tic"], s=2.2, color=DOT, alpha=0.55,
                       linewidths=0, label="advance-detector arrival", zorder=2)
            ax.set_ylim(0, k["C"])
            ax.set_title(f"{sig}  {d}   AoG {k['aog']:.0f}%   PR {k['pr']:.2f}",
                         fontsize=10, color=INK, pad=6)
            ax.tick_params(colors=MUTED, labelsize=8)
            for s in ax.spines.values():
                s.set_color("#dcdbd6")
            ax.grid(axis="y", color="#eeedea", lw=0.7)
            ax.set_axisbelow(True)
            if j == 0:
                ax.set_ylabel("time in cycle (s)\nfrom start of coordinated green",
                              fontsize=8.5, color=MUTED)
            if i == len(dirs) - 1:
                ax.set_xlabel("time of day (h)", fontsize=8.5, color=MUTED)
    h, l = axes[0][0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=3, frameon=False, fontsize=9,
               labelcolor=MUTED, bbox_to_anchor=(0.5, -0.005))
    fig.suptitle(f"Purdue Coordination Diagrams — run '{tag}'   "
                 f"(arrivals below the green line arrive on green)",
                 fontsize=12.5, color=INK, y=0.99)
    fig.tight_layout(rect=[0, 0.045, 1, 0.97])
    p = os.path.join(ROOT, "outputs", "plots", f"pcd_{tag}.png")
    fig.savefig(p, dpi=150, facecolor=SURF)
    print(f"\nWrote {p}")


if __name__ == "__main__":
    main()
