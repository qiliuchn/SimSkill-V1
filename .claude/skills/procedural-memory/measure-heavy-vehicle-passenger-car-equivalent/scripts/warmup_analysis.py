#!/usr/bin/env python3
"""STEP 2b -- determine the warm-up / steady-state truncation point EMPIRICALLY
(per `quantify-sumo-run-to-run-variability`), rather than assuming a cutoff.

MSER-5 (White 1997): batch the series into non-overlapping means of 5, then pick
the truncation index d minimising

        MSER(d) = 1/(n-d)^2 * sum_{i>d} (Y_i - mean_{j>d} Y_j)^2

A truncation point pinned at the END of the search range is the standard
diagnostic that NO steady state exists in that series -- it is reported as such
rather than being forced into a warm-up number.

Series used
  freeway : 60-s discharge counts at the bottleneck station, from t=0
  signal  : vehicles discharged per cycle on the N approach, from t=0
"""
import os
import json
import xml.etree.ElementTree as ET

from common import WORK, GREENS, YELLOW, G_EW
import freeway_rig as F
import signal_rig as S


def mser5(series):
    b = [sum(series[i:i + 5]) / len(series[i:i + 5])
         for i in range(0, len(series) - len(series) % 5, 5)]
    n = len(b)
    if n < 6:
        return None, None, n
    best_d, best_v = None, None
    for d in range(0, n - 3):          # keep >= 3 batches after truncation
        tail = b[d:]
        m = sum(tail) / len(tail)
        v = sum((y - m) ** 2 for y in tail) / (len(tail) ** 2)
        if best_v is None or v < best_v:
            best_v, best_d = v, d
    pinned = best_d >= n - 4
    return best_d, pinned, n


def fwy_series(d):
    rows = F.parse_e1(os.path.join(d, "e1_cap.xml"), 0.0, 1e9)["cap_0"]
    rows.sort(key=lambda r: r["begin"])
    return [r["begin"] for r in rows], [r["n"] for r in rows]


def sig_series(d, g):
    ev = S.parse_instant(os.path.join(d, "instant_N.xml"))
    C = g + YELLOW + G_EW + YELLOW
    onsets = [i * C for i in range(int(2600 // C))]
    ts, ys = [], []
    for t0 in onsets:
        if t0 + g + YELLOW > 2600:
            break
        ts.append(t0)
        ys.append(len([e for e in ev if t0 <= e[0] < t0 + g + YELLOW]))
    return ts, ys


def main():
    out = {}
    for tag, d in (("freeway_p0", os.path.join(WORK, "pilot", "fwy_p0")),
                   ("freeway_p30", os.path.join(WORK, "pilot", "fwy_p30"))):
        ts, ys = fwy_series(d)
        dd, pinned, nb = mser5(ys)
        out[tag] = dict(kind="freeway 60-s bottleneck discharge count",
                        n_intervals=len(ys), n_batches=nb, mser5_batch_index=dd,
                        mser5_truncation_time_s=None if dd is None else dd * 5 * 60.0,
                        pinned_at_search_boundary=pinned,
                        series_head=ys[:20], series_tail=ys[-10:],
                        adopted_warmup_s=900.0)
    for tag, d, g in (("signal_p0_g32", os.path.join(WORK, "pilot", "sig2_p0_g32"), 32.0),
                      ("signal_p50_g32", os.path.join(WORK, "pilot", "sig2_p50_g32"), 32.0)):
        ts, ys = sig_series(d, g)
        dd, pinned, nb = mser5(ys)
        out[tag] = dict(kind="signal vehicles discharged per cycle (N approach)",
                        n_cycles=len(ys), n_batches=nb, mser5_batch_index=dd,
                        mser5_truncation_time_s=None if dd is None else dd * 5 * (g + YELLOW + G_EW + YELLOW),
                        pinned_at_search_boundary=pinned,
                        series_head=ys[:20], series_tail=ys[-10:],
                        adopted_warmup_s=600.0)
    with open(os.path.join(WORK, "warmup_analysis.json"), "w") as f:
        json.dump(out, f, indent=2)
    for k, v in out.items():
        print("%-16s MSER-5 truncation = %s s  (pinned=%s)  adopted warm-up = %s s"
              % (k, v["mser5_truncation_time_s"], v["pinned_at_search_boundary"],
                 v["adopted_warmup_s"]))
        print("     head:", v["series_head"])
    print("written", os.path.join(WORK, "warmup_analysis.json"))


if __name__ == "__main__":
    main()
