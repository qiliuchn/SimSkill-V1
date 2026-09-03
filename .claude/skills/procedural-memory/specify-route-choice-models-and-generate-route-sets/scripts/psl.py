#!/usr/bin/env python3
"""Standalone Path-Size Logit (PSL) calculator over a fixed route set (Ben-Akiva &
Bierlaire 1999 path-size formula), plus a standalone C-Logit calculator for comparison.
Reusable deliverable for sub-goal 7 ("PSL/C-Logit calculator").

Both operate purely on route definitions -- {route_id: [(link_id, link_length), ...]} plus
{route_id: cost} -- with NO SUMO call required, so they can be validated against an
independent ground truth (probit SUE) and then used to compute probabilities for ANY route
set (including ones from sub-goal 4's route-set generators).
"""
import math


def path_size(routes_links):
    """routes_links: {route_id: [(link_id, link_length), ...]}
    Returns {route_id: PS_i} using PS_i = sum_{a in i} (l_a/L_i) / sum_j delta_aj (L_i/L_j)^gamma,
    gamma=1 (the standard default).
    """
    totals = {r: sum(l for _, l in links) for r, links in routes_links.items()}
    # which routes use each link
    link_users = {}
    for r, links in routes_links.items():
        for a, l in links:
            link_users.setdefault(a, []).append(r)
    ps = {}
    for r, links in routes_links.items():
        Li = totals[r]
        s = 0.0
        for a, la in links:
            denom = sum((Li / totals[j]) for j in link_users[a])
            s += (la / Li) / denom
        ps[r] = s
    return ps


def psl_probabilities(costs, routes_links, theta, beta_ps=1.0):
    """costs: {route_id: cost}. Returns {route_id: probability}."""
    ps = path_size(routes_links)
    order = list(costs.keys())
    utils = [-theta * costs[r] + beta_ps * math.log(ps[r]) for r in order]
    m = max(utils)
    ex = [math.exp(u - m) for u in utils]
    s = sum(ex)
    return {r: e / s for r, e in zip(order, ex)}, ps


def clogit_commonality(routes_links, gamma=1.0):
    """SUMO-style commonality factor CF_i = ln( sum_j (L_ij/sqrt(Li*Lj))^gamma ), where
    L_ij is the shared physical length between routes i and j (i=j included, giving 1).
    Verified in sub-goal 1 to be exactly what duarouter's C-logit implements (times beta).
    """
    totals = {r: sum(l for _, l in links) for r, links in routes_links.items()}
    linkset = {r: {a: l for a, l in links} for r, links in routes_links.items()}
    cf = {}
    for i, links_i in linkset.items():
        s = 0.0
        for j, links_j in linkset.items():
            shared = sum(l for a, l in links_i.items() if a in links_j)
            ratio = shared / math.sqrt(totals[i] * totals[j])
            s += ratio ** gamma
        cf[i] = math.log(s)
    return cf


def clogit_probabilities(costs, routes_links, theta, beta, gamma=1.0):
    cf = clogit_commonality(routes_links, gamma)
    order = list(costs.keys())
    utils = [-theta * (costs[r] + beta * cf[r]) for r in order]
    m = max(utils)
    ex = [math.exp(u - m) for u in utils]
    s = sum(ex)
    return {r: e / s for r, e in zip(order, ex)}, cf


if __name__ == "__main__":
    # sanity check against the sub-goal-2 Daganzo-Sheffi testbed's hand-derived formula:
    # PS_A=1, PS_B=PS_C=1-phi/2 (see sg3_psl/run_sg3.py for the full validation)
    L = 1000.0
    for phi in (0.0, 0.25, 0.5, 0.75, 0.95):
        routes = {
            "A": [("A", L)],
            "B": [("shared", phi * L), ("B_only", (1 - phi) * L)],
            "C": [("shared", phi * L), ("C_only", (1 - phi) * L)],
        }
        ps = path_size(routes)
        print(f"phi={phi:.2f}  PS_A={ps['A']:.4f}  PS_B={ps['B']:.4f}  PS_C={ps['C']:.4f}"
              f"   (hand-derived: PS_A=1, PS_B=PS_C={1-phi/2:.4f})")
