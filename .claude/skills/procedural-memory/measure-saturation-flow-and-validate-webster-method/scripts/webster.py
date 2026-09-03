#!/usr/bin/env python3
"""STEP 4 -- Webster's method implemented from first principles, driven ONLY by
the parameters measured in measure_saturation.py.  Nothing here comes from
tlsCycleAdaptation.py.

Definitions used (Webster 1958; Webster & Cobbe 1966)
----------------------------------------------------
  y_i    = q_i / s                     critical flow ratio of phase i
  Y      = sum_i y_i
  l_i    = l1 + l2                     lost time of phase i
           l1 = startup lost time (measured)
           l2 = (yellow + allred) - e  clearance lost time, e = measured
                                        discharge extension into yellow
  L      = sum_i l_i  (+ any extra all-red already inside l2)
  C_opt  = (1.5 L + 5) / (1 - Y)
  g_eff,i = (C - L) * y_i / Y          effective green
  g_disp,i = g_eff,i + l_i - (yellow_i + allred_i)   displayed green
             (so that sum_i g_disp,i + sum_i(yellow_i+allred_i) = C exactly)

Webster's average delay per vehicle on an approach:
  lambda = g_eff / C ,  c = lambda * s ,  x = q / c
  d = C(1-lambda)^2 / (2(1 - lambda*x))
      + x^2 / (2 q (1-x))
      - 0.65 (C/q^2)^(1/3) x^(2+5 lambda)
with q, s, c in veh/s.  Undefined for x >= 1 (returns None).
Intersection average = flow-weighted mean over all approaches.
"""
import math


class WebsterDesign:
    def __init__(self, s_vph, l1, l2, yellow, allred=0.0):
        self.s = s_vph                 # veh/h/lane
        self.l1 = l1
        self.l2 = l2
        self.yellow = yellow
        self.allred = allred
        self.l_phase = l1 + l2

    # ---------------------------------------------------------------- core
    def flow_ratios(self, crit_flows):
        """crit_flows: list of critical lane flows q_i [veh/h] per phase."""
        return [q / self.s for q in crit_flows]

    def total_lost_time(self, nphase):
        return nphase * self.l_phase

    def c_opt(self, crit_flows):
        y = self.flow_ratios(crit_flows)
        Y = sum(y)
        L = self.total_lost_time(len(crit_flows))
        if Y >= 1.0:
            return None, Y, L          # Webster undefined / negative
        return (1.5 * L + 5.0) / (1.0 - Y), Y, L

    def splits(self, C, crit_flows, min_green=5.0):
        """-> (g_eff list, g_displayed list).  Webster-proportional splits."""
        y = self.flow_ratios(crit_flows)
        Y = sum(y)
        n = len(crit_flows)
        L = self.total_lost_time(n)
        avail = C - L
        if Y <= 0:
            geff = [avail / n] * n
        else:
            geff = [avail * yi / Y for yi in y]
        gdisp = [ge + self.l_phase - (self.yellow + self.allred) for ge in geff]
        # enforce a minimum displayed green, renormalise so the cycle closes
        gdisp = [max(min_green, g) for g in gdisp]
        inter = n * (self.yellow + self.allred)
        scale = (C - inter) / sum(gdisp)
        gdisp = [g * scale for g in gdisp]
        geff = [g - self.l_phase + (self.yellow + self.allred) for g in gdisp]
        return geff, gdisp

    # -------------------------------------------------------------- delay
    def delay(self, C, g_eff, q_vph):
        """Webster average delay [s/veh] for one approach."""
        q = q_vph / 3600.0
        s = self.s / 3600.0
        lam = g_eff / C
        cap = lam * s
        if q <= 0:
            return 0.0
        x = q / cap
        if x >= 1.0:
            return None
        d1 = C * (1 - lam) ** 2 / (2 * (1 - lam * x))
        d2 = x ** 2 / (2 * q * (1 - x))
        d3 = 0.65 * (C / q ** 2) ** (1.0 / 3.0) * x ** (2 + 5 * lam)
        return d1 + d2 - d3

    def intersection_delay(self, C, crit_flows, approach_flows, min_green=5.0):
        """approach_flows: list of (phase_index, q_vph) for every approach."""
        geff, gdisp = self.splits(C, crit_flows, min_green)
        num = den = 0.0
        parts = []
        for ph, q in approach_flows:
            d = self.delay(C, geff[ph], q)
            parts.append(d)
            if d is None:
                return None, geff, gdisp, parts
            num += q * d
            den += q
        return num / den, geff, gdisp, parts

    def degree_of_saturation(self, C, crit_flows, min_green=5.0):
        geff, _ = self.splits(C, crit_flows, min_green)
        return [q / ((ge / C) * self.s) for q, ge in zip(crit_flows, geff)]
