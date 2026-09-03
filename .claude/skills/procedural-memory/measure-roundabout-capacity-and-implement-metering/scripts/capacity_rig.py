"""
PART 2 -- empirical entry-capacity vs circulating-flow curve, and the
car-following / junction parameter that controls it.

Rig (single-lane roundabout `sl`; `two` for the two-lane multiplier):

  * CIRCULATING generator: a flow E -> S (3rd exit from E).  Its path is
        in_E -> rg_E -> rl_N -> rg_N -> rl_W -> rg_W -> out_S
    so it occupies rl_N, the ring segment between the N leg's EXIT node xN and
    the N leg's ENTRY node eN -- exactly the HCM "circulating flow passing in
    front of the subject entry".  rl_E is empty so the E entry is unimpeded and
    delivers its requested volume.
    Its headways are NEGATIVE-EXPONENTIAL (`period="exp(rate)"`).  This matters
    enormously: SUMO's plain `vehsPerHour` emits vehicles at exactly equal
    spacing, and a deterministic circulating stream whose constant headway sits
    just under the entry's critical gap blocks the entry almost completely
    (measured 220 veh/h at v_c=600 with uniform headways vs 734 veh/h with
    exponential ones) -- a rig artifact, not roundabout physics.  HCM's
    gap-acceptance capacity model likewise assumes random arrivals.
  * SUBJECT entry N, loaded far above capacity.  Single-lane: N->W (1st exit).
    Two-lane: N->W forced onto lane 0 (right turn from the right lane) and N->E
    forced onto lane 1 (left turn from the left lane).  The explicit departLane
    is REQUIRED: with departLane="best"/"free"/"random" SUMO concentrated ~92% of
    the entering traffic on lane 0 and the measured "two-lane" capacity came out
    barely above the single-lane value -- a lane-choice artifact.

  Measurement
  * det_entry_i : E1 loops at the N stop line  -> entry discharge
  * det_circ_i  : E1 loops on rl_N             -> MEASURED v_c (never assumed)
  * det_q       : E2 on in_N_0, endPos clipped to the lane -> proves the standing
                  queue never cleared.  Points where it DID clear are censored:
                  there the entry is limited by the approach's own saturation
                  flow, not by gap acceptance, and they are excluded from the
                  exponential fit and reported separately as the ceiling.
"""
import argparse
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import run_sumo, vtype_xml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(HERE, "networks")

WARMUP = 600.0
MEASURE = 1800.0
END = WARMUP + MEASURE
HCM = dict(A=1130.0, B=0.001)


def detectors_xml(path, lanes_entry, lanes_ring, entry_edge="in_N"):
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>"]
    for i in range(lanes_entry):
        L.append(f'    <inductionLoop id="det_entry_{i}" lane="{entry_edge}_{i}" pos="-3" '
                 f'friendlyPos="true" period="60" file="det_entry.xml"/>')
    for i in range(lanes_ring):
        L.append(f'    <inductionLoop id="det_circ_{i}" lane="rl_N_{i}" pos="10" '
                 f'friendlyPos="true" period="60" file="det_circ.xml"/>')
    L.append(f'    <laneAreaDetector id="det_q" lane="{entry_edge}_0" pos="0" endPos="-1" '
             f'friendlyPos="true" period="60" file="det_q.xml"/>')
    L.append("</additional>")
    open(path, "w").write("\n".join(L) + "\n")
    return path


def routes_xml(path, vc, subject, vtype_overrides=None):
    """subject: list of (dest_arm, departLane, vehsPerHour)"""
    L = ['<?xml version="1.0" encoding="UTF-8"?>', "<routes>",
         vtype_xml(overrides=vtype_overrides)]
    if vc > 0:
        L.append(f'    <flow id="f_ES" type="car" from="in_E" to="out_S" begin="0" end="{END}" '
                 f'period="exp({vc/3600.0:.6f})" departLane="free" departSpeed="max" departPos="last"/>')
    for dest, lane, vph in subject:
        L.append(f'    <flow id="f_N{dest}" type="car" from="in_N" to="out_{dest}" begin="0" end="{END}" '
                 f'vehsPerHour="{vph}" departLane="{lane}" departSpeed="max" departPos="last"/>')
    L.append("</routes>")
    open(path, "w").write("\n".join(L) + "\n")
    return path


def read_e1(path, ids, t0, t1):
    n, span, per_id = 0.0, 0.0, {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "interval" and el.get("id") in ids:
            b, e = float(el.get("begin")), float(el.get("end"))
            if b >= t0 and e <= t1:
                c = float(el.get("nVehContrib"))
                n += c
                per_id[el.get("id")] = per_id.get(el.get("id"), 0) + c
                if el.get("id") == ids[0]:
                    span += (e - b)
            el.clear()
    return (n / span * 3600.0 if span > 0 else 0.0), per_id, span


def read_e2_minjam(path, t0, t1):
    vals = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "interval":
            b, e = float(el.get("begin")), float(el.get("end"))
            if b >= t0 and e <= t1:
                vals.append(float(el.get("maxJamLengthInVehicles", 0)))
            el.clear()
    return (min(vals) if vals else -1), (sum(vals) / len(vals) if vals else -1)


def one_point(outdir, net, lanes_entry, lanes_ring, vc_req, subject, seed,
              vtype_overrides=None, step=0.25):
    os.makedirs(outdir, exist_ok=True)
    rou = routes_xml(os.path.join(outdir, "d.rou.xml"), vc_req, subject, vtype_overrides)
    add = detectors_xml(os.path.join(outdir, "det.add.xml"), lanes_entry, lanes_ring)
    r = run_sumo(net, rou, outdir, end=END, seed=seed, step=step, ttt=-1,
                 additional=[add], tripinfo=False, summary=True, max_depart_delay=600)
    if r.returncode != 0:
        return None
    ent, ent_per, span = read_e1(os.path.join(outdir, "det_entry.xml"),
                                 [f"det_entry_{i}" for i in range(lanes_entry)], WARMUP, END)
    circ, circ_per, _ = read_e1(os.path.join(outdir, "det_circ.xml"),
                                [f"det_circ_{i}" for i in range(lanes_ring)], WARMUP, END)
    minjam, meanjam = read_e2_minjam(os.path.join(outdir, "det_q.xml"), WARMUP, END)
    return dict(vc_requested=vc_req, vc_measured=round(circ, 1), entry_cap=round(ent, 1),
                entry_per_lane=ent_per, circ_per_lane=circ_per,
                min_jam_veh=minjam, mean_jam_veh=round(meanjam, 2),
                gap_limited=bool(minjam >= 1), seed=seed)


def fit_exp(points):
    xs = [p["vc_measured"] for p in points if p["entry_cap"] > 0]
    ys = [math.log(p["entry_cap"]) for p in points if p["entry_cap"] > 0]
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    yhat = [a + b * x for x in xs]
    ssr = sum((y - yh) ** 2 for y, yh in zip(ys, yhat))
    sst = sum((y - my) ** 2 for y in ys)
    # residual SE of slope -> 95% CI
    se_b = math.sqrt((ssr / (n - 2)) / sxx) if n > 2 and sxx > 0 else float("nan")
    return dict(A=round(math.exp(a), 1), B=round(-b, 6), B_95ci=round(1.96 * se_b, 6),
                R2=round(1 - ssr / sst, 4) if sst > 0 else float("nan"), n=n)


def aggregate(rows):
    agg = {}
    for r in rows:
        agg.setdefault(r["vc_requested"], []).append(r)
    pts = []
    for k, v in sorted(agg.items()):
        m = sum(x["entry_cap"] for x in v) / len(v)
        sd = (sum((x["entry_cap"] - m) ** 2 for x in v) / max(1, len(v) - 1)) ** 0.5
        pts.append(dict(vc_requested=k,
                        vc_measured=round(sum(x["vc_measured"] for x in v) / len(v), 1),
                        entry_cap=round(m, 1), entry_cap_sd=round(sd, 1), n=len(v),
                        gap_limited=all(x["gap_limited"] for x in v),
                        min_jam_veh=min(x["min_jam_veh"] for x in v)))
    return pts


def run_curve(outdir, tag, net, lanes_entry, lanes_ring, ladder, subject, seeds,
              vtype_overrides=None, verbose=True):
    rows = []
    for vc in ladder:
        for s in seeds:
            d = os.path.join(outdir, tag, f"vc{vc}_s{s}")
            p = one_point(d, net, lanes_entry, lanes_ring, vc, subject, s, vtype_overrides)
            if p:
                rows.append(p)
                if verbose:
                    print(f"[{tag}] vc_req={vc:5d} s={s} vc_meas={p['vc_measured']:7.1f} "
                          f"cap={p['entry_cap']:7.1f} minjam={p['min_jam_veh']:5.1f} "
                          f"{'gap-limited' if p['gap_limited'] else 'CENSORED (queue cleared)'}")
    pts = aggregate(rows)
    gl = [p for p in pts if p["gap_limited"]]
    ceiling = [p for p in pts if not p["gap_limited"]]
    return dict(points=pts, raw=rows,
                fit_gap_limited=fit_exp(gl),
                fit_all_points=fit_exp(pts),
                n_gap_limited=len(gl),
                free_flow_ceiling=round(max((p["entry_cap"] for p in ceiling), default=float("nan")), 1),
                subject=subject, ladder=ladder, seeds=seeds)


SL_SUBJECT = [("W", "0", 3000)]
TWO_SUBJECT = [("W", "0", 3000), ("E", "1", 3000)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=os.path.join(HERE, "results", "capacity"))
    ap.add_argument("--seeds", type=int, nargs="+", default=[11, 22, 33])
    ap.add_argument("--skip-sensitivity", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    out = {}

    L1 = [0, 100, 200, 300, 400, 500, 600, 750, 900, 1050, 1200, 1350]
    L2 = [0, 200, 400, 600, 900, 1200, 1500, 1800, 2100, 2400]

    out["single_lane"] = run_curve(args.outdir, "single_lane", os.path.join(NET, "sl.net.xml"),
                                   1, 1, L1, SL_SUBJECT, args.seeds)
    out["two_lane"] = run_curve(args.outdir, "two_lane", os.path.join(NET, "two.net.xml"),
                                2, 2, L2, TWO_SUBJECT, args.seeds)

    f = out["single_lane"]["fit_gap_limited"]
    comp = []
    for p in out["single_lane"]["points"]:
        h = HCM["A"] * math.exp(-HCM["B"] * p["vc_measured"])
        comp.append(dict(vc=p["vc_measured"], sumo=p["entry_cap"], sumo_sd=p["entry_cap_sd"],
                         hcm=round(h, 1), ratio=round(p["entry_cap"] / h, 3),
                         gap_limited=p["gap_limited"]))
    out["single_lane"]["hcm_comparison"] = comp
    # v_c at which the SUMO curve crosses the HCM curve:  A e^{-B v} = 1130 e^{-0.001 v}
    if f and f["B"] != HCM["B"]:
        out["single_lane"]["hcm_crossover_vc"] = round(
            math.log(f["A"] / HCM["A"]) / (f["B"] - HCM["B"]), 1)

    # 2-lane multiplier, both from the fitted curves and directly from matched rungs
    g = out["two_lane"]["fit_gap_limited"]
    if f and g:
        out["two_lane_multiplier_fitted"] = [
            dict(vc=v, single=round(f["A"] * math.exp(-f["B"] * v), 1),
                 two=round(g["A"] * math.exp(-g["B"] * v), 1),
                 multiple=round((g["A"] * math.exp(-g["B"] * v)) / (f["A"] * math.exp(-f["B"] * v)), 3))
            for v in [0, 300, 600, 900, 1200]]
    out["two_lane_multiplier_measured"] = dict(
        single_ceiling=out["single_lane"]["free_flow_ceiling"],
        two_ceiling=out["two_lane"]["free_flow_ceiling"],
        ceiling_multiple=round(out["two_lane"]["free_flow_ceiling"] /
                               out["single_lane"]["free_flow_ceiling"], 3)
        if out["single_lane"]["free_flow_ceiling"] == out["single_lane"]["free_flow_ceiling"] else None)

    # ---- parameter sensitivity: which parameter controls the fitted curve?
    if not args.skip_sensitivity:
        LS = [200, 400, 600, 800, 1000, 1200]
        base = None
        sens = {}
        variants = [("baseline", {}),
                    ("tau=0.7", {"tau": "0.7"}), ("tau=1.4", {"tau": "1.4"}),
                    ("minGap=1.5", {"minGap": "1.5"}), ("minGap=4.0", {"minGap": "4.0"}),
                    ("accel=1.5", {"accel": "1.5"}), ("accel=4.0", {"accel": "4.0"}),
                    ("decel=3.0", {"decel": "3.0"}), ("decel=6.0", {"decel": "6.0"}),
                    ("sigma=0.0", {"sigma": "0.0"}), ("sigma=0.9", {"sigma": "0.9"}),
                    ("jmTimegapMinor=0.2", {"jmTimegapMinor": "0.2"}),
                    ("jmTimegapMinor=2.0", {"jmTimegapMinor": "2.0"}),
                    ("impatience=1.0", {"impatience": "1.0"}),
                    ("jmIgnoreFoeProb=0.2", {"jmIgnoreFoeProb": "0.2", "jmIgnoreFoeSpeed": "5.0"}),
                    ("length=7.0", {"length": "7.0"})]
        for name, ov in variants:
            r = run_curve(os.path.join(args.outdir, "sens"), name.replace("=", "_"),
                          os.path.join(NET, "sl.net.xml"), 1, 1, LS, SL_SUBJECT,
                          [args.seeds[0]], vtype_overrides=ov, verbose=False)
            fit = r["fit_gap_limited"] or r["fit_all_points"]
            sens[name] = dict(fit=fit, points=r["points"])
            if name == "baseline":
                base = fit
            print(f"[sens] {name:24s} A={fit['A']:8.1f} B={fit['B']:.5f} R2={fit['R2']:.3f}")
        for name, v in sens.items():
            if base and v["fit"]:
                v["dA_pct"] = round(100 * (v["fit"]["A"] - base["A"]) / base["A"], 1)
                v["dB_pct"] = round(100 * (v["fit"]["B"] - base["B"]) / base["B"], 1)
                # capacity change at a mid circulating flow, the practically relevant summary
                c_b = base["A"] * math.exp(-base["B"] * 600)
                c_v = v["fit"]["A"] * math.exp(-v["fit"]["B"] * 600)
                v["dC600_pct"] = round(100 * (c_v - c_b) / c_b, 1)
        out["sensitivity"] = sens

    with open(os.path.join(args.outdir, "capacity_results.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    print("\n== single-lane gap-limited fit:", out["single_lane"]["fit_gap_limited"])
    print("== single-lane free-flow ceiling:", out["single_lane"]["free_flow_ceiling"])
    print("== HCM crossover v_c:", out["single_lane"].get("hcm_crossover_vc"))
    print("== two-lane gap-limited fit:", out["two_lane"]["fit_gap_limited"])
    print("== two-lane multiplier (fitted):", out.get("two_lane_multiplier_fitted"))
    print("== two-lane multiplier (ceiling):", out["two_lane_multiplier_measured"])


if __name__ == "__main__":
    main()
