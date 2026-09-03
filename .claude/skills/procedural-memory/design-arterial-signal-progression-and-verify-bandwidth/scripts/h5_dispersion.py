#!/usr/bin/env python3
"""H5 PLATOON DISPERSION - measure spread vs. downstream distance, fit Robertson.

A dedicated single-signal corridor (one signalised junction, a 900 m
unobstructed downstream link) isolates dispersion from re-metering by a
downstream signal.  From FCD:

  * each vehicle's stop-line departure time t0 and its arrival time t(d) at
    cross-sections d = 50, 100, ... 900 m downstream
  * link travel time tau(d) = t(d) - t0 per vehicle
  * platoon spread sigma(d) = sd(tau(d)) and the cyclic arrival-profile
    concentration (max fraction of a cycle's arrivals inside the widest 10 s
    window), which is what a downstream green band actually has to catch

Robertson's recurrence smooths the upstream profile with a geometric kernel of
parameter F; a shifted-geometric kernel has variance (1-F)/F^2 (in 1 s steps),
so each cross-section yields
        F(d) = (-1 + sqrt(1 + 4 sigma^2)) / (2 sigma^2)
and Robertson's model F = 1/(1 + alpha*beta*T) implies
        1/F - 1 = (alpha*beta) * T ,   T = mean cruise travel time to d.
An ordinary least-squares fit through the origin of (1/F - 1) on T gives the
empirical alpha*beta and its R^2.

Finally the "coordination stops paying" length is located two ways:
  (i)  where 2*sigma(d) exceeds the analytic two-way band at that spacing, and
  (ii) directly from the H1 coordinated-vs-uncoordinated benefit vs. L curve.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402
import expbase as B          # noqa: E402
import fcdband               # noqa: E402
import runner as R           # noqa: E402
import scenario as S         # noqa: E402
import sumolib               # noqa: E402

DIST = [50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 800, 900]


def build_probe(seed=1, thru=900.0, cross=350.0, end=3000.0, sdev=0.05):
    d = os.path.join(B.WORK, "h5", "probe_s%d_sd%03d" % (seed, int(sdev * 100)))
    os.makedirs(d, exist_ok=True)
    net = A.build_net(d, n_int=1, L=0.0, stub=1000.0, cross_len=300.0)
    trips, n = A.write_demand(os.path.join(d, "trips.xml"), 1, seed, end=end,
                              thru=thru, cross=cross, art_side=0.0,
                              speed_dev=sdev)
    rou = A.route(net, trips, os.path.join(d, "routes.rou.xml"))
    nt = sumolib.net.readNet(net)
    xs = [nt.getNode("J0").getCoord()[0]]
    return dict(net=net, rou=rou, xs=xs, n_int=1, end=end, dir=d, ntrips=n)


def run_probe(seed=1, sdev=0.05):
    sc = build_probe(seed=seed, sdev=sdev)
    p = B.plan(n=1, offs=[0.0])
    d = os.path.join(B.WORK, "h5", "run_s%d_sd%03d" % (seed, int(sdev * 100)))
    os.makedirs(d, exist_ok=True)
    nt = R.net_of(sc)
    add = p.write_add(nt, os.path.join(d, "plan.add.xml"))
    filt = A.write_edge_filter(os.path.join(d, "sel.txt"), A.arterial_edges(1))
    fcd = os.path.join(d, "fcd.xml")
    A.run_sumo(sc["net"], sc["rou"], [add], d, seed=seed, end=sc["end"],
               fcd=fcd, extra=["--fcd-output.filter-edges.input-file", filt,
                               "--fcd-output.attributes", "x,y,speed,lane",
                               "--device.fcd.begin", "%.0f" % B.WARM])
    return sc, p, fcd


def profile(fcd, x0, warm=B.WARM):
    """vid -> (t0 at stop line, {d: arrival time})."""
    tr = fcdband.load(fcd, prefixes=("thruE",))
    out = {}
    for vid, pts in tr.items():
        t0 = fcdband._cross_time(pts, x0, True)
        if t0 is None or t0 < warm:
            continue
        rec = {}
        for d in DIST:
            t = fcdband._cross_time(pts, x0 + d, True)
            if t is not None:
                rec[d] = t - t0
        if len(rec) == len(DIST):
            out[vid] = (t0, rec)
    return out


def measure(sdev):
    sc, plan, fcd = run_probe(seed=1, sdev=sdev)
    x0 = sc["xs"][0]
    pr = profile(fcd, x0)
    print("sdev=%.2f probe vehicles with full cross-section set: %d"
          % (sdev, len(pr)))
    if len(pr) < 100:
        raise SystemExit("too few probe vehicles (%d)" % len(pr))
    C = plan.C
    rows = []
    for d in DIST:
        taus = [rec[d] for _, rec in pr.values()]
        n = len(taus)
        mu = sum(taus) / n
        var = sum((t - mu) ** 2 for t in taus) / (n - 1)
        sd = math.sqrt(var)
        # cyclic arrival profile concentration at this cross-section
        arr = [((t0 + rec[d]) % C) for t0, rec in pr.values()]
        best = 0
        for k in range(int(C)):
            w = sum(1 for a in arr if ((a - k) % C) < 10.0)
            best = max(best, w)
        conc = best / float(n)
        F = (-1.0 + math.sqrt(1.0 + 4.0 * var)) / (2.0 * var) if var > 0 else 1.0
        rows.append(dict(d_m=d, n=n, mean_tau=mu, sd_tau=sd, var_tau=var,
                         cruise_T=d / B.VPROG, F=F, inv_F_minus1=1.0 / F - 1.0,
                         conc10s=conc, speed_dev=sdev))
    return rows


def fit_robertson(rows):
    # OLS through the origin: (1/F - 1) = (alpha*beta) * T
    xsT = [r["cruise_T"] for r in rows]
    ysY = [r["inv_F_minus1"] for r in rows]
    ab = sum(x * y for x, y in zip(xsT, ysY)) / sum(x * x for x in xsT)
    ybar = sum(ysY) / len(ysY)
    ss_res = sum((y - ab * x) ** 2 for x, y in zip(xsT, ysY))
    ss_tot = sum((y - ybar) ** 2 for y in ysY)
    r2 = 1 - ss_res / ss_tot
    # also fit with a free intercept, to show the origin constraint is not
    # doing the work
    nn = len(xsT)
    sx, sy = sum(xsT), sum(ysY)
    sxx = sum(x * x for x in xsT)
    sxy = sum(x * y for x, y in zip(xsT, ysY))
    slope = (nn * sxy - sx * sy) / (nn * sxx - sx * sx)
    icpt = (sy - slope * sx) / nn
    fit = dict(alpha_beta=ab, r2_through_origin=r2,
               free_slope=slope, free_intercept=icpt,
               note="Robertson F = 1/(1+alpha*beta*T); alpha*beta is the fitted "
                    "product. Literature default alpha=0.35 (uncongested "
                    "friction) with beta=0.8 gives alpha*beta=0.28.",
               implied_alpha_at_beta_0p8=ab / 0.8)
    return fit


def main():
    rows = measure(0.05)
    A.write_csv(os.path.join(B.DATA, "h5_dispersion.csv"), rows)
    fit = fit_robertson(rows)

    # SENSITIVITY: the fitted dispersion is a property of the simulated fleet's
    # speed heterogeneity, not a universal constant. Re-measure with a much more
    # heterogeneous fleet to show the fit responds as Robertson's model says.
    sens = {}
    for sd in (0.15, 0.30):
        try:
            r2rows = measure(sd)
            A.write_csv(os.path.join(B.DATA, "h5_dispersion_sdev%03d.csv"
                                     % int(sd * 100)), r2rows)
            sens["speedDev_%.2f" % sd] = fit_robertson(r2rows)
        except SystemExit as e:
            sens["speedDev_%.2f" % sd] = dict(error=str(e))
    fit["sensitivity_to_fleet_speed_heterogeneity"] = {
        k: dict(alpha_beta=v.get("alpha_beta"), r2=v.get("r2_through_origin"))
        for k, v in sens.items()}

    # where does coordination stop paying? 2*sigma vs analytic two-way band
    p90 = B.plan()
    cross = []
    for Lm in range(100, 901, 25):
        sd = None
        for r in rows:
            if r["d_m"] >= Lm:
                sd = r["sd_tau"]
                break
        if sd is None:
            sd = rows[-1]["sd_tau"]
        xs = [i * Lm for i in range(B.N_INT)]
        o, bE, bW = A.maxband(p90, xs, B.VPROG, objective="min", restarts=6, seed=2)
        cross.append(dict(L=Lm, sd_tau=sd, two_sigma=2 * sd,
                          b_two_way=min(bE, bW),
                          band_exceeds_spread=min(bE, bW) > 2 * sd))
    A.write_csv(os.path.join(B.DATA, "h5_spread_vs_band.csv"), cross)
    fit["L_where_2sigma_exceeds_band_first"] = next(
        (c["L"] for c in cross if not c["band_exceeds_spread"]), None)
    json.dump(fit, open(os.path.join(B.DATA, "h5_robertson_fit.json"), "w"),
              indent=1)
    print(json.dumps(fit, indent=1))
    for r in rows:
        print("d=%4d  T=%5.1f  sd=%5.2f  F=%.3f  conc10s=%.3f"
              % (r["d_m"], r["cruise_T"], r["sd_tau"], r["F"], r["conc10s"]))
    print("H5 done")


if __name__ == "__main__":
    main()
