#!/usr/bin/env python3
"""MUTCD 2009 Part 4F pedestrian-hybrid-beacon installation guidelines.

Digitised directly from the FHWA long descriptions of Figure 4F-1 (low speed,
<= 35 mph) and Figure 4F-2 (high speed, > 35 mph):
  https://mutcd.fhwa.dot.gov/HTM/2009/part4/fig4f_01_longdesc.htm
  https://mutcd.fhwa.dot.gov/HTM/2009/part4/fig4f_02_longdesc.htm

Each curve is (major-street total volume both directions [veh/h],
pedestrians crossing the major street [ped/h]) for a given crosswalk length.
A point ON OR ABOVE the curve for the applicable crosswalk length means a PHB
"should be considered".  20 ped/h is the stated lower threshold volume.
"""
PPH_FLOOR = 20.0

FIG_4F1_LOW = {          # <= 35 mph
    34:  [(750, 400), (1000, 190), (1250, 90), (1500, 40), (2000, 20)],
    50:  [(500, 350), (750, 125), (1000, 50), (1250, 20), (1500, 20), (2000, 20)],
    72:  [(250, 500), (500, 120), (750, 25), (1000, 20), (1250, 20), (1500, 20), (2000, 20)],
    100: [(225, 500), (250, 250), (500, 30), (750, 20), (1000, 20), (1250, 20),
          (1500, 20), (1750, 20), (2000, 20)],
}
FIG_4F2_HIGH = {         # > 35 mph
    34:  [(750, 150), (1000, 50), (2000, 20)],
    50:  [(500, 150), (750, 25), (1000, 20), (2000, 20)],
    72:  [(250, 300), (500, 25), (750, 20), (1000, 20), (2000, 20)],
    100: [(100, 500), (250, 100), (750, 20), (1000, 20), (1750, 20), (2000, 20)],
}


def _interp(curve, v):
    """ped/h threshold at major-street volume v (veh/h) on one crosswalk-length curve."""
    c = sorted(curve)
    if v <= c[0][0]:
        return c[0][1]           # left of the plotted range: use the leftmost (hardest)
    if v >= c[-1][0]:
        return max(c[-1][1], PPH_FLOOR)
    for (x0, y0), (x1, y1) in zip(c, c[1:]):
        if x0 <= v <= x1:
            f = (v - x0) / (x1 - x0)
            return max(y0 + f * (y1 - y0), PPH_FLOOR)
    return PPH_FLOOR


def threshold_pph(major_vph, crosswalk_ft, speed_mph):
    """Interpolate between the two bracketing crosswalk-length curves."""
    fig = FIG_4F1_LOW if speed_mph <= 35 else FIG_4F2_HIGH
    ls = sorted(fig)
    if crosswalk_ft <= ls[0]:
        return _interp(fig[ls[0]], major_vph), ("extrapolated below %d ft" % ls[0])
    if crosswalk_ft >= ls[-1]:
        return _interp(fig[ls[-1]], major_vph), ("extrapolated above %d ft" % ls[-1])
    for a, b in zip(ls, ls[1:]):
        if a <= crosswalk_ft <= b:
            ya, yb = _interp(fig[a], major_vph), _interp(fig[b], major_vph)
            f = (crosswalk_ft - a) / (b - a)
            return max(ya + f * (yb - ya), PPH_FLOOR), "interpolated %d-%d ft" % (a, b)
    return PPH_FLOOR, "floor"


def warranted(major_vph, pph, crosswalk_ft, speed_mph):
    thr, note = threshold_pph(major_vph, crosswalk_ft, speed_mph)
    return (pph >= thr and pph >= PPH_FLOOR), thr, note


if __name__ == "__main__":
    print("crosswalk 21 ft (1 lane/dir, 30 mph) -- uses the 34 ft curve (extrapolated)")
    for q in (300, 600, 900, 1200, 1500, 1800):
        thr, note = threshold_pph(2 * q, 21, 30)
        print("  q=%4d/dir  major=%4d veh/h  threshold=%6.1f ped/h  (%s)"
              % (q, 2 * q, thr, note))
    print("crosswalk 42 ft (2 lanes/dir, 30 mph)")
    for q in (300, 600, 900, 1200, 1500, 1800):
        thr, note = threshold_pph(2 * q, 42, 30)
        print("  q=%4d/dir  major=%4d veh/h  threshold=%6.1f ped/h  (%s)"
              % (q, 2 * q, thr, note))
