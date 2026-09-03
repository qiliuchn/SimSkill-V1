#!/usr/bin/env python3
"""Pedestrian demand for the corridor: <personFlow> + <walk>, Poisson arrivals.

`period="exp(r)"` makes departures a Poisson process at rate r persons/s driven by
the sumo --seed, which is what gives the runs the stochasticity that the CRN
replication design operates on (a bare perHour= is deterministic/equidistant and
would make every seed identical).

Direction split: `frac_fwd` of the total rate walks A->D (with the edge direction);
the remainder walks D->A on the SAME single sidewalk lane, given as an explicit
edge list because the road is one-way.
"""
import argparse


def write_demand(path, rate_total, frac_fwd=1.0, begin=0.0, end=1800.0, warm_ramp=0.0):
    r_f = rate_total * frac_fwd
    r_b = rate_total * (1.0 - frac_fwd)
    L = ['<routes>']
    L.append('  <vType id="ped" vClass="pedestrian"/>')
    if r_f > 1e-9:
        L.append('  <personFlow id="fwd" type="ped" begin="%.2f" end="%.2f" period="exp(%.6f)">'
                 % (begin, end, r_f))
        L.append('    <walk edges="EA EM EO" departPosLat="random" arrivalPos="-1"/>')
        L.append('  </personFlow>')
    if r_b > 1e-9:
        L.append('  <personFlow id="bwd" type="ped" begin="%.2f" end="%.2f" period="exp(%.6f)">'
                 % (begin, end, r_b))
        L.append('    <walk edges="EO EM EA" departPosLat="random" arrivalPos="-1"/>')
        L.append('  </personFlow>')
    L.append('</routes>')
    open(path, "w").write("\n".join(L) + "\n")
    return {"rate_total": rate_total, "rate_fwd": r_f, "rate_bwd": r_b,
            "begin": begin, "end": end}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--rate", type=float, required=True, help="persons/s total")
    ap.add_argument("--frac-fwd", type=float, default=1.0)
    ap.add_argument("--begin", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=1800.0)
    a = ap.parse_args()
    print(write_demand(a.out, a.rate, a.frac_fwd, a.begin, a.end))
