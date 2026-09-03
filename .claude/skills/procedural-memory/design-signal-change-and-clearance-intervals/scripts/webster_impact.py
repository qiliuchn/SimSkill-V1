"""H3 part 2: feed the MEASURED total lost time back into Webster's method and quantify how
much the usual "lost time = yellow + all-red" assumption shifts C_opt and delay.

Webster (1958), implemented independently here (not consumed from any SUMO tool):
    y_i   = q_i / s
    Y     = sum_i y_i
    L     = total lost time per cycle
    C_opt = (1.5 L + 5) / (1 - Y)
    lam_i = g_eff,i / C ,  g_eff,i = (C - L) y_i / Y
    x_i   = q_i / (lam_i s)
    d_i(C)= C (1-lam)^2 / (2 (1 - lam x)) + x^2 / (2 q (1-x))
            - 0.65 (C/q^2)^(1/3) x^(2 + 5 lam)
"""
import json
import os

from common import ANA_DIR


def webster_c_opt(L, Y):
    if Y >= 1.0:
        return None
    return (1.5 * L + 5.0) / (1.0 - Y)


def webster_delay(C, L, qs, s):
    """Total per-vehicle delay, flow-weighted across phases. qs in veh/s, s in veh/s."""
    ys = [q / s for q in qs]
    Y = sum(ys)
    if Y >= 1.0 or C <= L:
        return None
    tot = 0.0
    wsum = 0.0
    for q, y in zip(qs, ys):
        g_eff = (C - L) * y / Y
        lam = g_eff / C
        x = q / (lam * s) if lam > 0 else 2.0
        if x >= 1.0 or lam <= 0:
            return None
        d = (C * (1 - lam) ** 2 / (2 * (1 - lam * x))
             + x * x / (2 * q * (1 - x))
             - 0.65 * (C / (q * q)) ** (1.0 / 3.0) * x ** (2 + 5 * lam))
        tot += d * q
        wsum += q
    return tot / wsum


def main():
    lt = json.load(open(os.path.join(ANA_DIR, "lost_time.json")))
    base = [r for r in lt if r["green"] == 30.0 and r["truck_share"] == 0.0]
    out = []
    for r in sorted(base, key=lambda x: (x["yellow"], x["allred"])):
        s = r["sat_flow"] / 3600.0                    # veh/s/lane, MEASURED
        L_meas = 2.0 * r["L_total"]                   # two critical phases
        L_assum = 2.0 * r["assumed_intergreen"]
        for vc in (0.70, 0.85):
            # The cycle length is not carried into the aggregated lost_time.json record;
            # reconstruct it with the same definition measure_lost_time.py used when the
            # runs were built:  cycle = 2 * (green + yellow + allred).
            cycle = 2.0 * (r["green"] + r["yellow"] + r["allred"])
            # Per-phase demand corresponding to a degree of saturation vc under the
            # timing that was actually simulated: capacity of a phase is s * g_eff / C,
            # with g_eff the MEASURED effective green from the lost-time experiment.
            #   q_i = vc * s * g_eff / C   =>   y_i = q_i/s = vc * g_eff / C
            q = vc * s * (r["g_eff"] / cycle)
            qs = [q, q]
            Y = sum(x / s for x in qs)
            if Y >= 1.0:
                continue
            C_m = webster_c_opt(L_meas, Y)
            C_a = webster_c_opt(L_assum, Y)
            if not C_m or not C_a:
                continue
            # truth uses the MEASURED lost time; the two candidate cycle lengths are compared
            d_m = webster_delay(C_m, L_meas, qs, s)
            d_a = webster_delay(C_a, L_meas, qs, s)
            if d_m is None or d_a is None:
                continue
            out.append(dict(case="y=%.1f ar=%.1f vc=%.2f MEASURED L" % (r["yellow"],
                                                                        r["allred"], vc),
                            yellow=r["yellow"], allred=r["allred"], vc=vc,
                            L=L_meas, Y=Y, C_opt=C_m, d_at_own=d_m, d_at_other=d_a,
                            penalty=0.0, penalty_pct=0.0))
            out.append(dict(case="y=%.1f ar=%.1f vc=%.2f ASSUMED L=y+ar" % (r["yellow"],
                                                                            r["allred"], vc),
                            yellow=r["yellow"], allred=r["allred"], vc=vc,
                            L=L_assum, Y=Y, C_opt=C_a, d_at_own=webster_delay(C_a, L_assum,
                                                                              qs, s),
                            d_at_other=d_a, penalty=d_a - d_m,
                            penalty_pct=100.0 * (d_a - d_m) / d_m))
    json.dump(out, open(os.path.join(ANA_DIR, "webster_impact.json"), "w"), indent=2)
    for r in out:
        print("%-42s L=%6.2f  C_opt=%6.1f  d_own=%6.2f  d_true=%6.2f  pen=%+.3f s (%+.2f%%)"
              % (r["case"], r["L"], r["C_opt"], r["d_at_own"] or -1, r["d_at_other"],
                 r["penalty"], r["penalty_pct"]))


if __name__ == "__main__":
    main()
