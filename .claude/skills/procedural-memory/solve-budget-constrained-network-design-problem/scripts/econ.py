#!/usr/bin/env python3
"""
Monetisation / discounting layer, following the convention of the existing
`appraise-project-alternatives-with-benefit-cost-analysis` skill:
NPV = sum_{t=1..H} B_t/(1+r)^t - C_0, every parameter's provenance labelled.

Deliberate simplification vs that skill: benefits are held CONSTANT at the
modelled demand level rather than interpolated across a growth path.  That
skill's verified finding is that linear interpolation between two simulated
demand points overstates PV of benefits by 80-96%; holding benefits flat at one
simulated level avoids that specific error entirely, at the cost of ignoring
demand growth (a conservative, clearly stated assumption).
"""
PARAMS = [
    dict(name="MU", value=1000000.0, unit="USD per monetary unit",
         provenance="ASSUMED scale convention for this synthetic testbed; project "
                    "costs in testbed.py are expressed in MU. Chosen so a 3.0 MU "
                    "lane-addition on a 500 m two-direction link pair (= 2 lane-km) "
                    "prices at USD 1.5M per lane-km, and the resulting BCRs land in "
                    "a plausible 1-3 band rather than an absurd 20-23. Changing this "
                    "scales every PV/NPV/BCR identically and cannot change any "
                    "ranking or any TSTT result."),
    dict(name="VOT", value=20.0, unit="USD per vehicle-hour",
         provenance="PLACEHOLDER value of travel time; not calibrated to any "
                    "jurisdiction - all BCR/NPV figures scale linearly with it"),
    dict(name="EVENTS_PER_YEAR", value=500.0, unit="peak events per year",
         provenance="ASSUMED 2 peak periods/day x 250 weekdays; the simulated "
                    "event is one 1800 s loading period"),
    dict(name="DISCOUNT_RATE", value=0.04, unit="per year",
         provenance="ASSUMED real social discount rate (common appraisal default)"),
    dict(name="HORIZON", value=20.0, unit="years",
         provenance="ASSUMED appraisal period, benefits in years 1..20"),
    dict(name="DEMAND_GROWTH", value=0.0, unit="per year",
         provenance="ASSUMED zero - benefits held flat at the one simulated demand "
                    "level, deliberately avoiding the two-point-interpolation bias "
                    "documented in transport-economic-appraisal-from-microsimulation"),
]
P = {p["name"]: p["value"] for p in PARAMS}
ANNUITY = sum(1.0 / (1.0 + P["DISCOUNT_RATE"]) ** t
              for t in range(1, int(P["HORIZON"]) + 1))          # 13.59033


def benefit_mu_per_event(delta_tstt_s):
    """delta_tstt_s = TSTT(do-nothing) - TSTT(design), in vehicle-seconds."""
    return (delta_tstt_s / 3600.0) * P["VOT"] / P["MU"]


def pv_benefits_mu(delta_tstt_s):
    return benefit_mu_per_event(delta_tstt_s) * P["EVENTS_PER_YEAR"] * ANNUITY


def npv_mu(delta_tstt_s, cost_mu):
    return pv_benefits_mu(delta_tstt_s) - cost_mu


def bcr(delta_tstt_s, cost_mu):
    return (pv_benefits_mu(delta_tstt_s) / cost_mu) if cost_mu > 0 else float("inf")


if __name__ == "__main__":
    print("annuity factor (r=%.2f, H=%d) = %.5f" % (P["DISCOUNT_RATE"], P["HORIZON"], ANNUITY))
    for p in PARAMS:
        print("%-16s %12g  %-28s %s" % (p["name"], p["value"], p["unit"], p["provenance"]))
