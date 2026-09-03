#!/usr/bin/env python3
import csv
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("C_real", "g_real", "q_true_vph", "DoS_true", "q_hat_good_vph",
                  "DoS_hat_good", "q_hat_bad_vph", "DoS_hat_bad", "occ_tail_frac"):
            r[k] = float(r[k])
    return rows


def err_stats(rows, key_hat, key_true="DoS_true"):
    e = np.array([r[key_hat] - r[key_true] for r in rows])
    return dict(n=len(e), bias=e.mean(), mae=np.abs(e).mean(), rmse=np.sqrt((e ** 2).mean()),
                sd=e.std())


def report():
    rows = load(os.path.join(HERE, "dos_validation.csv"))
    print("=" * 100)
    print("DoS ESTIMATOR VALIDATION -- overall (n=%d cycle x direction x junction observations)" % len(rows))
    print("=" * 100)
    for label, key in (("good detector (90m setback)", "DoS_hat_good"),
                       ("bad detector (15m setback)", "DoS_hat_bad")):
        s = err_stats(rows, key)
        print("%-32s bias=%+.4f  MAE=%.4f  RMSE=%.4f  sd=%.4f" %
              (label, s["bias"], s["mae"], s["rmse"], s["sd"]))

    print("\nBY REGIME (good detector only)")
    print("%-12s %6s %8s %8s %8s %8s %8s" % ("regime", "n", "bias", "MAE", "RMSE", "meanTrue", "meanOccTail"))
    for reg in ("stationary", "reversal", "surge", "incident", "recovery"):
        rs = [r for r in rows if r["regime"] == reg]
        if not rs:
            continue
        s = err_stats(rs, "DoS_hat_good")
        mt = np.mean([r["DoS_true"] for r in rs])
        ot = np.mean([r["occ_tail_frac"] for r in rs])
        print("%-12s %6d %+8.4f %8.4f %8.4f %8.3f %8.3f" % (reg, s["n"], s["bias"], s["mae"], s["rmse"], mt, ot))

    print("\nBY REGIME (bad-setback detector)")
    print("%-12s %6s %8s %8s %8s" % ("regime", "n", "bias", "MAE", "RMSE"))
    for reg in ("stationary", "reversal", "surge", "incident", "recovery"):
        rs = [r for r in rows if r["regime"] == reg]
        if not rs:
            continue
        s = err_stats(rs, "DoS_hat_bad")
        print("%-12s %6d %+8.4f %8.4f %8.4f" % (reg, s["n"], s["bias"], s["mae"], s["rmse"]))

    print("\nBY TRUE-DoS BUCKET (undersaturated -> oversaturated) -- shows the bias TREND directly")
    print("%-16s %6s %10s %10s %10s %10s %10s" %
          ("DoS_true bucket", "n", "good_bias", "good_MAE", "bad_bias", "bad_MAE", "mean_occTail"))
    buckets = [("<0.3", 0.0, 0.3), ("0.3-0.6", 0.3, 0.6), ("0.6-0.9", 0.6, 0.9),
               ("0.9-1.2", 0.9, 1.2), (">=1.2", 1.2, 1e9)]
    for label, lo_, hi_ in buckets:
        rs = [r for r in rows if lo_ <= r["DoS_true"] < hi_]
        if not rs:
            continue
        sg = err_stats(rs, "DoS_hat_good")
        sb = err_stats(rs, "DoS_hat_bad")
        ot = np.mean([r["occ_tail_frac"] for r in rs])
        print("%-16s %6d %+10.4f %10.4f %+10.4f %10.4f %10.4f" %
              (label, sg["n"], sg["bias"], sg["mae"], sb["bias"], sb["mae"], ot))

    ot_max = max(r["occ_tail_frac"] for r in rows)
    print("\nSPILLBACK PROXY: cycles in the top decile of stop-bar occ_tail_frac (this scenario's most")
    print("queue-persistent-through-green cycles) vs the rest -- observed occ_tail_frac max=%.3f, so this" % ot_max)
    p90 = np.percentile([r["occ_tail_frac"] for r in rows], 90)
    hi = [r for r in rows if r["occ_tail_frac"] >= p90]
    lo = [r for r in rows if r["occ_tail_frac"] < p90]
    print("run never reaches a classic full-spillback (occ_tail~1.0) signature -- see sub-goal 6's dedicated")
    print("oversaturation arm for that regime; this is the top-decile (occ_tail>=%.3f) comparison instead:" % p90)
    for label, rs in (("top decile occ_tail (queue persists longest)", hi), ("remaining 90%%", lo)):
        if not rs:
            continue
        sg = err_stats(rs, "DoS_hat_good")
        sb = err_stats(rs, "DoS_hat_bad")
        print("%-46s n=%4d  good: bias=%+.4f MAE=%.4f | bad: bias=%+.4f MAE=%.4f | meanTrueDoS=%.3f" %
              (label, sg["n"], sg["bias"], sg["mae"], sb["bias"], sb["mae"],
               np.mean([r["DoS_true"] for r in rs])))

    print("\nUNDERSATURATED / LOW-VOLUME NOISE: DoS_true < 0.5 (long-gap regime)")
    lowv = [r for r in rows if r["DoS_true"] < 0.5]
    if lowv:
        s = err_stats(lowv, "DoS_hat_good")
        print("n=%d good-detector bias=%+.4f MAE=%.4f RMSE=%.4f  (RMSE/mean_true=%.2f -- variance-dominated, not bias)"
              % (s["n"], s["bias"], s["mae"], s["rmse"], s["rmse"] / max(np.mean([r["DoS_true"] for r in lowv]), 1e-6)))

    print("\nOVERSATURATED: DoS_true >= 1.0")
    hiv = [r for r in rows if r["DoS_true"] >= 1.0]
    if hiv:
        sg = err_stats(hiv, "DoS_hat_good")
        sb = err_stats(hiv, "DoS_hat_bad")
        print("n=%d  good: bias=%+.4f MAE=%.4f | bad: bias=%+.4f MAE=%.4f" %
              (sg["n"], sg["bias"], sg["mae"], sb["bias"], sb["mae"]))

def main():
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report()
    text = buf.getvalue()
    print(text)
    with open(os.path.join(HERE, "dos_validation_summary.txt"), "w") as f:
        f.write(text)


if __name__ == "__main__":
    main()
