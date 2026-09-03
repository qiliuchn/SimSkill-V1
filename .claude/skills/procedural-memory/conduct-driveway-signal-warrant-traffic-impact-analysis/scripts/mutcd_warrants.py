#!/usr/bin/env python3
"""
MUTCD signal-warrant engine with the threshold tables encoded numerically.

Implemented
  Warrant 1  Eight-Hour Vehicular Volume
             Condition A  Minimum Vehicular Volume        (Table 4C-1)
             Condition B  Interruption of Continuous Traffic (Table 4C-1)
             the 80% COMBINATION case (neither A nor B alone, but both at 80%
             for the SAME eight hours)
  Warrant 2  Four-Hour Vehicular Volume   (Figure 4C-1 / 4C-2 curves)
  Warrant 3  Peak Hour                    (Figure 4C-3 / 4C-4 curves)
             plus Warrant 3 CONDITION A (the delay / volume / total-entering
             three-part test), which is measurable here because minor-approach
             stopped delay comes straight out of tripinfo.

Percentage columns
  100 %  standard
   80 %  used only for the Warrant-1 combination case
   70 %  major-street 85th-percentile speed > 70 km/h (40 mph) OR the
         intersection lies in an isolated community with population < 10 000
   56 %  70 % of the 80 % column (combination case under the 70 % reduction)

IMPORTANT, stated in the output: Warrant 2 and Warrant 3 in the MUTCD are
PLOTTED CURVES (Figures 4C-1 and 4C-3), not tables.  The breakpoint tables below
are a DIGITISED approximation of those curves.  Every reported result therefore
also carries the MARGIN (measured minor volume / threshold), so a reader can see
whether a conclusion depends on the digitisation.  The documented axis-note
floors (80/115 veh/h for Warrant 2, 100/150 veh/h for Warrant 3) are applied as
hard lower bounds exactly as the figures specify.
"""

# ---------------------------------------------------------------- Warrant 1
# (major both approaches, minor higher-volume approach), veh/h, 100 % column
COND_A = {("1", "1"): (500, 150), ("2+", "1"): (600, 150),
          ("2+", "2+"): (600, 200), ("1", "2+"): (500, 200)}
COND_B = {("1", "1"): (750, 75), ("2+", "1"): (900, 75),
          ("2+", "2+"): (900, 100), ("1", "2+"): (750, 100)}

# ------------------------------------------------- Warrant 2  (Figure 4C-1)
# digitised breakpoints: major total (veh/h) -> minor higher approach (veh/h)
W2_CURVES = {
    ("1", "1"):   [(300, 175), (400, 150), (500, 131), (600, 116), (700, 105),
                   (800, 96), (900, 89), (1000, 84), (1100, 80), (1500, 80)],
    ("2+", "1"):  [(300, 205), (400, 180), (500, 158), (600, 140), (700, 126),
                   (800, 114), (900, 105), (1000, 97), (1100, 91), (1200, 85),
                   (1300, 80), (1500, 80)],
    ("2+", "2+"): [(300, 240), (400, 215), (500, 193), (600, 174), (700, 159),
                   (800, 147), (900, 137), (1000, 129), (1100, 123), (1200, 118),
                   (1300, 115), (1500, 115)],
    ("1", "2+"):  [(300, 205), (400, 180), (500, 160), (600, 145), (700, 133),
                   (800, 125), (900, 120), (1000, 117), (1100, 115), (1500, 115)],
}
W2_FLOOR = {"1": 80, "2+": 115}

# ------------------------------------------------- Warrant 3  (Figure 4C-3)
W3_CURVES = {
    ("1", "1"):   [(400, 240), (500, 205), (600, 178), (700, 157), (800, 140),
                   (900, 127), (1000, 117), (1100, 109), (1200, 103), (1300, 100),
                   (2000, 100)],
    ("2+", "1"):  [(400, 285), (500, 247), (600, 217), (700, 193), (800, 174),
                   (900, 159), (1000, 147), (1100, 137), (1200, 129), (1300, 122),
                   (1400, 117), (1500, 112), (1600, 107), (1700, 103), (1800, 100),
                   (2400, 100)],
    ("2+", "2+"): [(400, 335), (500, 295), (600, 262), (700, 236), (800, 215),
                   (900, 198), (1000, 184), (1100, 173), (1200, 164), (1300, 157),
                   (1400, 151), (1500, 150), (2400, 150)],
    ("1", "2+"):  [(400, 290), (500, 253), (600, 224), (700, 202), (800, 185),
                   (900, 172), (1000, 163), (1100, 156), (1200, 152), (1300, 150),
                   (2000, 150)],
}
W3_FLOOR = {"1": 100, "2+": 150}

# Warrant 3 Condition A three-part test
W3A_DELAY_VEH_H = {"1": 4.0, "2+": 5.0}       # minor-approach stopped-time delay
W3A_MINOR_VOL = {"1": 100, "2+": 150}
W3A_TOTAL_ENTERING = {3: 650, 4: 800}          # by number of intersection approaches


def _interp(curve, x):
    if x <= curve[0][0]:
        return curve[0][1]
    if x >= curve[-1][0]:
        return curve[-1][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return curve[-1][1]


def w2_threshold(major, maj_cat, min_cat, pct=100):
    t = max(_interp(W2_CURVES[(maj_cat, min_cat)], major), W2_FLOOR[min_cat])
    return t * pct / 100.0


def w3_threshold(major, maj_cat, min_cat, pct=100):
    t = max(_interp(W3_CURVES[(maj_cat, min_cat)], major), W3_FLOOR[min_cat])
    return t * pct / 100.0


def w1_thresholds(cond, maj_cat, min_cat, pct=100):
    tbl = COND_A if cond == "A" else COND_B
    mj, mn = tbl[(maj_cat, min_cat)]
    return mj * pct / 100.0, mn * pct / 100.0


def evaluate_hours(hours, maj_cat="2+", min_cat="1", pct=100):
    """hours: list of dicts with keys major, minor (higher-volume approach).
    Returns a per-hour list of pass/fail + threshold + margin for every warrant."""
    out = []
    for h in hours:
        mj, mn = h["major"], h["minor"]
        row = dict(h)
        for cond in ("A", "B"):
            tj, tn = w1_thresholds(cond, maj_cat, min_cat, pct)
            row[f"W1{cond}_thr_major"] = tj
            row[f"W1{cond}_thr_minor"] = tn
            row[f"W1{cond}_pass"] = (mj >= tj) and (mn >= tn)
            row[f"W1{cond}_margin_minor"] = mn / tn if tn else float("inf")
            tj8, tn8 = w1_thresholds(cond, maj_cat, min_cat, pct * 0.8)
            row[f"W1{cond}80_pass"] = (mj >= tj8) and (mn >= tn8)
        t2 = w2_threshold(mj, maj_cat, min_cat, pct)
        row["W2_thr_minor"] = t2
        row["W2_pass"] = mn >= t2
        row["W2_margin"] = mn / t2 if t2 else float("inf")
        t3 = w3_threshold(mj, maj_cat, min_cat, pct)
        row["W3_thr_minor"] = t3
        row["W3_pass"] = mn >= t3
        row["W3_margin"] = mn / t3 if t3 else float("inf")
        out.append(row)
    return out


def summarise(rows, n_approaches=4):
    """Apply the multi-hour rules to a list of evaluated hours."""
    a = sum(1 for r in rows if r["W1A_pass"])
    b = sum(1 for r in rows if r["W1B_pass"])
    combo = sum(1 for r in rows if r["W1A80_pass"] and r["W1B80_pass"])
    n2 = sum(1 for r in rows if r["W2_pass"])
    n3 = sum(1 for r in rows if r["W3_pass"])
    w1a = a >= 8
    w1b = b >= 8
    w1c = (not w1a) and (not w1b) and combo >= 8
    return {
        "W1A_hours": a, "W1A_met": w1a,
        "W1B_hours": b, "W1B_met": w1b,
        "W1_combination_hours": combo, "W1_combination_met": w1c,
        "W1_met": w1a or w1b or w1c,
        "W2_hours": n2, "W2_met": n2 >= 4,
        "W3_hours": n3, "W3_met": n3 >= 1,
        "any_volume_warrant_met": (w1a or w1b or w1c) or (n2 >= 4) or (n3 >= 1),
    }


def w3_condition_a(hour_rows, min_cat="1", n_approaches=4):
    """hour_rows need: minor (veh/h on the higher minor approach),
    minor_delay_veh_h (stopped-time delay in vehicle-hours on that approach),
    total_entering (veh/h)."""
    res = []
    for r in hour_rows:
        d_ok = r["minor_delay_veh_h"] >= W3A_DELAY_VEH_H[min_cat]
        v_ok = r["minor"] >= W3A_MINOR_VOL[min_cat]
        t_ok = r["total_entering"] >= W3A_TOTAL_ENTERING[min(n_approaches, 4)]
        res.append({"hour": r.get("hour"), "delay_ok": d_ok, "volume_ok": v_ok,
                    "entering_ok": t_ok, "all_three": d_ok and v_ok and t_ok,
                    "minor_delay_veh_h": r["minor_delay_veh_h"],
                    "minor": r["minor"], "total_entering": r["total_entering"]})
    return res
