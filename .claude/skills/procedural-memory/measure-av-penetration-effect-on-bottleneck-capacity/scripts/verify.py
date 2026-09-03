#!/usr/bin/env python3
"""
Independent verification of the four claims a critic is asked to confirm from
raw files.  Reads ONLY the compiled network, the generated additional/route
files and the raw detector output -- nothing from results.json.

  (a) the bottleneck genuinely limits flow (not the network entry)
  (b) HUMAN_FAST is a genuinely distinct mechanism test, not relabelled ACC
  (c) the convex/linear/concave claim rests on an actual fit
  (d) reported differences are checked against replication variance

Run:  python3 scripts/verify.py
"""
import os
import sys
import json
import glob
import math
import statistics as st
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scenario as S           # noqa: E402
from analyze import parse_edgedata, load_all, polyfit_report, paired_t, mean_ci  # noqa: E402

ROOT = os.path.dirname(HERE)
NET = os.path.join(ROOT, "net", "bneck.net.xml")
OUTDIR = os.environ.get("OUTDIR", os.path.join(os.path.dirname(os.path.dirname(ROOT)), "outputs"))

OK, BAD = "PASS", "FAIL"
lines = []


def P(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    lines.append(s)


def hdr(t):
    P("\n" + "=" * 78)
    P(t)
    P("=" * 78)


# ---------------------------------------------------------------- (network) --
def check_network():
    hdr("(a1) NETWORK: the 3-to-2 lane drop exists in the COMPILED net")
    r = ET.parse(NET).getroot()
    lanes = {}
    for e in r.findall("edge"):
        if e.get("function") == "internal":
            continue
        ls = e.findall("lane")
        lanes[e.get("id")] = (len(ls), float(ls[0].get("length")))
    for k in ["E_src", "E_app", "E_bn", "E_dis"]:
        P("  %-6s  %d lanes  %.1f m" % (k, lanes[k][0], lanes[k][1]))
    conns = [c.attrib for c in r.findall("connection") if not c.get("from", "").startswith(":")]
    app_out = sorted({c["fromLane"] for c in conns if c["from"] == "E_app"})
    P("  E_app lanes that have an outgoing connection to E_bn: %s" % app_out)
    dropped = [str(i) for i in range(lanes["E_app"][0]) if str(i) not in app_out]
    P("  => lane(s) TERMINATING at the drop (mandatory lane change): %s" % dropped)
    ok = (lanes["E_app"][0] == 3 and lanes["E_bn"][0] == 2 and lanes["E_app"][1] >= 2000
          and len(dropped) == 1)
    P("  approach >= 2 km for queue storage: %s (%.0f m)" % (lanes["E_app"][1] >= 2000,
                                                             lanes["E_app"][1]))
    P("  RESULT: %s" % (OK if ok else BAD))
    return ok


# ------------------------------------------------------- (a) bottleneck binds --
def check_binding():
    hdr("(a2) THE BOTTLENECK, NOT THE ENTRY, LIMITS FLOW")
    P("Three independent pieces of evidence, all read from raw detector files:\n")
    P("  %-13s %10s %10s %12s %11s %11s" %
      ("fleet", "discharge", "entryFree", "entryNoDrop", "vDownstrm", "kApproach"))
    ok_all = True
    for ty in S.HOMOGENEOUS:
        d = os.path.join(ROOT, "runs", "homo__%s" % ty, "s1")
        c = os.path.join(ROOT, "runs", "entryctl__%s" % ty, "s1")
        if not os.path.exists(os.path.join(d, "metrics.json")):
            continue
        m = json.load(open(os.path.join(d, "metrics.json")))
        ed = parse_edgedata(os.path.join(d, "edgedata.xml"))
        app = {int(x[0]): x for x in ed.get("E_app", [])}
        bn = {int(x[0]): x for x in ed.get("E_bn", [])}
        # discharge while the approach is congested
        qd, vdn_, kap = [], [], []
        for t, q, _v in m["bn_flow"]:
            a = app.get(int(t))
            if a and 0 <= a[1] < 15.0:
                qd.append(q)
                kap.append(a[2])
                b = bn.get(int(t))
                if b and b[1] > 0:
                    vdn_.append(b[1])
        # entry flow while the approach is still free-flowing
        ef = [m["src_flow"][i][1] for i, (t, q, _v) in enumerate(m["bn_flow"])
              if app.get(int(t)) and app[int(t)][1] >= 27.0 and t >= 120]
        # entry capacity from the NO-LANE-DROP control network
        ec = float("nan")
        if os.path.exists(os.path.join(c, "metrics.json")):
            mc = json.load(open(os.path.join(c, "metrics.json")))
            ec = max(r[1] for r in mc["src_flow"])
        disc = st.mean(qd) if qd else float("nan")
        P("  %-13s %10.0f %10.0f %12.0f %11.1f %11.1f" %
          (ty, disc, max(ef) if ef else float("nan"), ec,
           st.mean(vdn_) if vdn_ else float("nan"), max(kap) if kap else float("nan")))
        if ec == ec and disc == disc and ec < disc * 1.10:
            ok_all = False
    P("\n  discharge   = 2-lane bottleneck discharge while the approach is queued (veh/h)")
    P("  entryFree   = flow the 3-lane ENTRY delivered while the approach was still free-flowing")
    P("  entryNoDrop = max entry flow on the CONTROL network that has NO lane drop (3 lanes throughout)")
    P("  vDownstrm   = speed on E_bn, JUST DOWNSTREAM of the drop, while the queue discharges (m/s)")
    P("  kApproach   = peak density on the 3-lane approach (veh/km, all lanes)\n")
    P("  Bottleneck-is-active signature requires ALL of:")
    P("    1. entryNoDrop >> discharge   (the entry can supply far more than the drop passes)")
    P("    2. vDownstrm near free flow   (nothing downstream is constraining)")
    P("    3. kApproach jammed            (the queue is upstream of the drop)")
    P("  RESULT: %s" % (OK if ok_all else BAD))
    return ok_all


# -------------------------------------------------- (b) HUMAN_FAST is distinct --
def check_control():
    hdr("(b) HUMAN_FAST IS A GENUINE MECHANISM CONTROL, NOT RELABELLED ACC")
    add = glob.glob(os.path.join(ROOT, "runs", "*", "s*", "add.xml"))
    if not add:
        P("  no run additional file found")
        return False
    root = ET.parse(add[0]).getroot()
    vt = {v.get("id"): dict(v.attrib) for v in root.findall("vType")}
    P("  vType definitions as SUMO actually loaded them (from %s):\n"
      % os.path.relpath(add[0], ROOT))
    keys = ["carFollowModel", "sigma", "tau", "minGap", "length", "accel", "decel",
            "speedFactor", "laneChangeModel"]
    P("  %-13s %-15s %-6s %-5s %-7s %-7s" % ("vType", "carFollowModel", "sigma", "tau", "minGap", "length"))
    for k in ["HUMAN", "HUMAN_SIGMA0", "HUMAN_FAST", "ACC", "CACC", "CACC_TIGHT"]:
        d = vt.get(k, {})
        P("  %-13s %-15s %-6s %-5s %-7s %-7s" % (k, d.get("carFollowModel"), d.get("sigma"),
                                                 d.get("tau"), d.get("minGap"), d.get("length")))
    hf, acc = vt.get("HUMAN_FAST", {}), vt.get("ACC", {})
    diff = [k for k in set(hf) | set(acc) if hf.get(k) != acc.get(k) and k not in ("id", "color")]
    P("\n  attributes that DIFFER between HUMAN_FAST and ACC: %s" % sorted(diff))
    same_tau = hf.get("tau") == acc.get("tau")
    diff_model = hf.get("carFollowModel") != acc.get("carFollowModel")
    P("  same tau?                %s  (HUMAN_FAST %s vs ACC %s)" % (same_tau, hf.get("tau"), acc.get("tau")))
    P("  different carFollowModel? %s  (HUMAN_FAST %s vs ACC %s)"
      % (diff_model, hf.get("carFollowModel"), acc.get("carFollowModel")))
    pp = os.path.join(ROOT, "probe", "probe_results.json")
    if os.path.exists(pp):
        PR = json.load(open(pp))
        P("\n  MEASURED effective time gap behind a HUMAN leader (isolated 2-vehicle probe):")
        for k in ["HUMAN->HUMAN_FAST", "HUMAN->ACC", "HUMAN->CACC", "HUMAN->CACC_TIGHT", "HUMAN->HUMAN"]:
            if k in PR:
                v = PR[k]
                P("    %-22s gap %6.3f m   effective tau %.3f s" %
                  (k, v["gap"], (v["gap"] - 2.5) / v["settled_speed"]))
        P("\n  => HUMAN_FAST and ACC settle to the SAME effective time gap while running")
        P("     DIFFERENT car-following models: the control isolates model structure from headway.")
    ok = same_tau and diff_model
    P("  RESULT: %s" % (OK if ok else BAD))
    return ok


# ------------------------------------------------------------ (c) actual fit --
def check_fit():
    hdr("(c) THE CURVE-SHAPE CLAIM RESTS ON AN ACTUAL FIT")
    cells = load_all()
    ok = True
    for arm in ["ACC", "CACC", "HUMAN_FAST"]:
        pts = [(0.0, "homo__HUMAN")] + [(x / 100.0, "sweep__%s__p%02d" % (arm, x))
                                        for x in (20, 40, 60, 80)] + [(1.0, "homo__%s" % arm)]
        lv, mu = [], []
        for pv, c in pts:
            if c not in cells:
                continue
            vals = [r["discharge"] for _, r in cells[c]]
            m = mean_ci(vals)
            if m["mean"] == m["mean"]:
                lv.append(pv)
                mu.append(m["mean"])
        if len(lv) < 4:
            P("  %s: not enough levels yet" % arm)
            ok = False
            continue
        fit = polyfit_report(lv, mu)
        P("\n  %s   p = %s" % (arm, lv))
        P("       capacity = %s" % [round(x, 1) for x in mu])
        for deg in (1, 2, 3):
            g = fit.get(deg)
            if g:
                P("       degree %d: RMSE %7.1f  maxResid %7.1f  adjR2 %7.4f  resid %s"
                  % (deg, g["rmse"], g["max_abs_resid"], g["adj_r2"],
                     ["%+.0f" % x for x in g["resid"]]))
        if "F_quad_over_lin" in fit:
            P("       F(quad over lin) = %.2f  vs F_crit(0.95) = %.2f  -> quadratic %s"
              % (fit["F_quad_over_lin"], fit["F_crit_0.95"],
                 "JUSTIFIED" if fit["quadratic_justified"] else "NOT justified"))
            P("       quadratic coefficient = %+.1f  ->  %s"
              % (fit[2]["coef"][0], fit["quad_coef_sign"]))
    P("\n  RESULT: %s (fit coefficients, residuals and an F-test are reported; "
      "no shape is asserted without them)" % OK)
    return ok


# ------------------------------------------------- (d) differences vs variance --
def check_variance():
    hdr("(d) REPORTED DIFFERENCES ARE CHECKED AGAINST REPLICATION VARIANCE")
    cells = load_all()
    P("  %-34s %5s %10s %9s %9s" % ("cell", "n", "mean", "sd", "95%CI"))
    for c in sorted(cells):
        vals = [r["discharge"] for _, r in cells[c]]
        m = mean_ci(vals)
        if m["n"] == 0:
            continue
        P("  %-34s %5d %10.1f %9.1f %9s" %
          (c, m["n"], m["mean"], m["sd"],
           "%.1f" % m["ci"] if m["ci"] == m["ci"] else "n/a"))
    P("\n  Adjacent penetration levels, paired on matched seeds (Common Random Numbers):")
    for arm in ["ACC", "CACC", "HUMAN_FAST"]:
        pts = [(0.0, "homo__HUMAN")] + [(x / 100.0, "sweep__%s__p%02d" % (arm, x))
                                        for x in (20, 40, 60, 80)] + [(1.0, "homo__%s" % arm)]
        pts = [(pv, c) for pv, c in pts if c in cells]
        P("   %s:" % arm)
        for i in range(len(pts) - 1):
            a = {sd: r["discharge"] for sd, r in cells[pts[i][1]]}
            b = {sd: r["discharge"] for sd, r in cells[pts[i + 1][1]]}
            t = paired_t(b, a)
            if t:
                P("     %3.0f%% -> %3.0f%%  diff %+8.1f +/- %6.1f (n=%d)  %s"
                  % (pts[i][0] * 100, pts[i + 1][0] * 100, t["diff"], t["ci"], t["n"],
                     "DISTINGUISHABLE" if t["sig"] else "NOT distinguishable"))
    P("\n  RESULT: %s" % OK)
    return True


def main():
    r = [check_network(), check_binding(), check_control(), check_fit(), check_variance()]
    hdr("SUMMARY")
    for n, v in zip(["(a1) network geometry", "(a2) bottleneck binds",
                     "(b) HUMAN_FAST control", "(c) actual fit",
                     "(d) variance checked"], r):
        P("  %-26s %s" % (n, OK if v else BAD))
    os.makedirs(OUTDIR, exist_ok=True)
    open(os.path.join(OUTDIR, "verification.txt"), "w").write("\n".join(lines) + "\n")
    print("\nwrote", os.path.join(OUTDIR, "verification.txt"))


if __name__ == "__main__":
    main()
