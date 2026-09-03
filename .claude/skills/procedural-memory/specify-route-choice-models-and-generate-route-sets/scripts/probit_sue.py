#!/usr/bin/env python3
"""Monte-Carlo probit Stochastic User Equilibrium ground truth for the Daganzo-Sheffi
"loop-hole" testbed (route A independent; routes B, C share a common section of length
fraction phi; all three routes have identical true free-flow cost).

Perception model: link-additive Gaussian error. Each PHYSICAL link a has one perception
error xi_a ~ N(0, (k*t_a)^2) drawn once per simulated traveler; a traveler's perceived
route cost is the sum of (true link cost + that traveler's draw of xi_a) over the links in
the route. Because routes B and C share the "shared" link, their perceived costs are
correlated for that traveler (same xi_shared draw) -- this is exactly the mechanism that
should suppress the naive "each route is an independent alternative" IIA assumption as the
shared fraction phi grows. Route A shares no links with B/C (approach edges given a
negligible length) so its perception error is independent of both.

This is a REUSABLE deliverable script (the "probit-SUE Monte-Carlo benchmark" of sub-goal 7).
"""
import random


def probit_shares(phi, L=1000.0, speed=10.0, k=0.25, n_draws=200000, seed=12345):
    """Returns (P_A, P_B, P_C) via Monte Carlo over independent travelers.
    L: total free-flow route length (m); speed: m/s; k: link perception-error coefficient
    of variation (sigma_a = k * t_a); n_draws: number of simulated travelers.
    """
    rng = random.Random(seed)
    t_A = L / speed
    t_shared = (phi * L) / speed
    t_tail = ((1.0 - phi) * L) / speed  # t_B_only == t_C_only by construction
    sA, sSh, sT = k * t_A, k * t_shared, k * t_tail

    countA = countB = countC = 0
    for _ in range(n_draws):
        eA = rng.gauss(0.0, sA) if sA > 0 else 0.0
        eSh = rng.gauss(0.0, sSh) if sSh > 0 else 0.0
        eB = rng.gauss(0.0, sT) if sT > 0 else 0.0
        eC = rng.gauss(0.0, sT) if sT > 0 else 0.0
        cA = t_A + eA
        cB = t_shared + t_tail + eSh + eB
        cC = t_shared + t_tail + eSh + eC
        best = min((cA, "A"), (cB, "B"), (cC, "C"))[1]
        if best == "A":
            countA += 1
        elif best == "B":
            countB += 1
        else:
            countC += 1
    n = float(n_draws)
    return countA / n, countB / n, countC / n


def wilson_ci(p, n, z=1.96):
    """Wilson score interval for a binomial proportion -- more reliable than normal
    approximation near p close to 0/1, used to report the MC ground truth's own noise floor.
    """
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)) / denom
    return center - half, center + half


if __name__ == "__main__":
    import sys
    n_draws = int(sys.argv[1]) if len(sys.argv) > 1 else 200000
    for phi in (0.0, 0.25, 0.5, 0.75, 0.95):
        pa, pb, pc = probit_shares(phi, n_draws=n_draws)
        lo, hi = wilson_ci(pa, n_draws)
        print(f"phi={phi:.2f}  P(A)={pa:.4f} [{lo:.4f},{hi:.4f}]  P(B)={pb:.4f}  P(C)={pc:.4f}")
