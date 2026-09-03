"""Frequency (fleet) allocation under a fixed bus-hour budget.

The decision variable is the INTEGER number of buses N_l on each line.  The
headway is derived from the measured cycle time:  h_l = C_l / N_l, with
C_l = measured mean round-trip time + layover.  Because the service span is
exactly 1 h, "N buses" == "N bus-hours".

Rounding / feasibility rule (stated once, applied everywhere):
  1. every operated line must satisfy the policy headway cap: N_l >= lo_l =
     ceil(C_l / H_MAX_POLICY)  (H_MAX = 1200 s), and N_l >= 1;
  2. no line may go below the headway floor: N_l <= hi_l = max(lo_l,
     floor(C_l / H_MIN_POLICY))  (H_MIN = 150 s);
  3. if sum(lo_l) > B the budget is INFEASIBLE for that route structure -- it is
     reported as such, never silently repaired;
  4. the remaining B - sum(lo_l) buses are distributed by largest-remainder on
     the continuous target, respecting hi_l;
  5. the integer allocation always sums to EXACTLY B.
"""
import math
from tspcore import H_MAX_POLICY, H_MIN_POLICY


def bounds(cycles, line_ids):
    lo, hi = {}, {}
    for l in line_ids:
        C = cycles[l]
        lo[l] = max(1, math.ceil(C / H_MAX_POLICY))
        hi[l] = max(lo[l], int(C // H_MIN_POLICY))
    return lo, hi


def apportion(B, target, cycles, line_ids):
    """Largest-remainder apportionment of B integer buses to the continuous
    target vector, respecting lo/hi bounds.  Returns (buses, feasible, msg)."""
    lo, hi = bounds(cycles, line_ids)
    if sum(lo.values()) > B:
        return None, False, (f"infeasible: sum of minimum fleets {sum(lo.values())} "
                             f"> budget {B} at the {H_MAX_POLICY:.0f}s policy cap")
    if sum(hi.values()) < B:
        return None, False, (f"infeasible: sum of maximum fleets {sum(hi.values())} "
                             f"< budget {B} at the {H_MIN_POLICY:.0f}s headway floor")
    tot = sum(target[l] for l in line_ids)
    cont = {l: B * target[l] / tot for l in line_ids}
    N = {l: min(hi[l], max(lo[l], int(math.floor(cont[l])))) for l in line_ids}
    # top-up / trim by largest remainder
    while sum(N.values()) < B:
        cand = [l for l in line_ids if N[l] < hi[l]]
        l = max(cand, key=lambda l: cont[l] - N[l])
        N[l] += 1
    while sum(N.values()) > B:
        cand = [l for l in line_ids if N[l] > lo[l]]
        if not cand:
            return None, False, "infeasible: cannot trim below minimum fleets"
        l = min(cand, key=lambda l: cont[l] - N[l])
        N[l] -= 1
    return N, True, "ok"


def sqrt_rule(B, cycles, demand, line_ids):
    """Classical square-root rule.

    Minimising total wait  W = sum_l Q_l / (2 f_l)  subject to the fleet budget
    sum_l f_l C_l = B  gives  f_l  ∝ sqrt(Q_l / C_l), hence the FLEET share
        N_l = f_l C_l  ∝  sqrt(Q_l * C_l).
    The policy headway cap H_MAX = 1200 s is applied as the lower bound lo_l.
    """
    target = {l: math.sqrt(max(1.0, demand.get(l, 1.0)) * cycles[l]) for l in line_ids}
    return apportion(B, target, cycles, line_ids)


def equal_rule(B, cycles, line_ids):
    return apportion(B, {l: 1.0 for l in line_ids}, cycles, line_ids)


def proportional_rule(B, cycles, demand, line_ids):
    """Frequency proportional to demand (the other common practitioner rule)."""
    target = {l: max(1.0, demand.get(l, 1.0)) * cycles[l] for l in line_ids}
    return apportion(B, target, cycles, line_ids)
