#!/usr/bin/env python3
"""Aggregate cells across seeds, attach CIs, run paired CRN tests, make plots."""
import csv
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cfgutil                                    # noqa: E402

# two-sided t critical values for small n (n-1 dof), alpha = 0.05
TCRIT = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
         8: 2.306, 9: 2.262, 10: 2.228, 14: 2.145, 19: 2.093, 29: 2.045}


def tcrit(df):
    if df in TCRIT:
        return TCRIT[df]
    return min((v for k, v in sorted(TCRIT.items()) if k >= df),
               default=1.96) if df < 30 else 1.96


def mean_ci(v):
    v = [x for x in v if x is not None]
    n = len(v)
    if n == 0:
        return None, None, 0
    m = sum(v) / n
    if n == 1:
        return m, 0.0, 1
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    return m, tcrit(n - 1) * sd / math.sqrt(n), n


def paired_diff_ci(a, b):
    """CI on mean(a-b) using CRN pairing (same seed order)."""
    d = [x - y for x, y in zip(a, b)]
    m, h, n = mean_ci(d)
    return m, h, (m - h > 0 or m + h < 0)      # (diff, halfwidth, significant)


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            for k, v in list(r.items()):
                if v in ("", None):
                    r[k] = None
                    continue
                try:
                    r[k] = float(v)
                except ValueError:
                    pass
            rows.append(r)
    return rows


NUMCOLS = ["delay", "wait", "stops", "tt", "delay_major", "delay_minor",
           "stops_major", "stops_minor", "throughput", "completion",
           "delay_robust", "teleports", "n_scheduled",
           "A_mean_green", "A_f_gapout", "A_f_maxout", "A_f_minout",
           "A_f_cut_with_blind_queue", "A_f_premature_gapout",
           "A_mean_blind_veh", "A_mean_blind_slow", "A_mean_imminent",
           "A_mean_unseen_imminent", "A_f_premature_gapout_anyimminent",
           "A_mean_queued_at_end",
           "C_mean_green", "C_f_gapout", "C_f_maxout",
           "C_f_cut_with_blind_queue", "C_f_premature_gapout",
           "C_mean_blind_veh", "C_mean_blind_slow", "C_mean_imminent",
           "C_mean_unseen_imminent", "C_f_premature_gapout_anyimminent",
           "C_mean_queued_at_end",
           "B_mean_green", "B_f_maxout", "D_mean_green", "D_f_maxout"]


def compact(rows):
    """(exp,name,level) -> dict of mean/ci per metric + the per-seed vectors."""
    g = defaultdict(list)
    for r in rows:
        g[(r["exp"], r["name"], r["level"])].append(r)
    out = {}
    for k, rs in g.items():
        rs.sort(key=lambda r: r["seed"])
        d = dict(exp=k[0], name=k[1], level=k[2], nseeds=len(rs),
                 setback=rs[0]["setback"], max_gap=rs[0]["max_gap"],
                 maxdur_mode=rs[0]["maxdur_mode"], mode=rs[0]["mode"],
                 auto_det=rs[0]["auto_det"], dead=rs[0]["dead"],
                 stuckon=rs[0]["stuckon"],
                 stuckon_max_tsd=rs[0].get("stuckon_max_tsd"))
        for c in NUMCOLS:
            v = [r.get(c) for r in rs]
            m, h, n = mean_ci(v)
            d[c] = None if m is None else round(m, 4)
            d[c + "_ci"] = None if h is None else round(h, 4)
            d["_v_" + c] = v
        out[k] = d
    return out


# ---------------------------------------------------------------------------
def main(csv_path, outdir):
    os.makedirs(outdir, exist_ok=True)
    rows = load(csv_path)
    C = compact(rows)

    # ---------- per-cell CSV deliverable ----------
    cols = [c for c in list(next(iter(C.values())).keys()) if not c.startswith("_v_")]
    with open(os.path.join(outdir, "cell_metrics.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for k in sorted(C):
            w.writerow(C[k])

    res = {}

    # ---------- E1 surface + best cell per demand ----------
    surf = {}
    for lv in ("low", "med", "high"):
        cells = {(c["setback"], c["max_gap"]): c for c in C.values()
                 if c["exp"] == "E1" and c["level"] == lv}
        if not cells:
            continue
        best = min(cells.values(), key=lambda c: c["delay"])
        # paired CRN comparison of every other cell against the best
        sig = {}
        for (sb, mg), c in sorted(cells.items()):
            dm, dh, s = paired_diff_ci(c["_v_delay"], best["_v_delay"])
            sig[f"sb{sb:g}_mg{mg:g}"] = dict(
                delay=c["delay"], ci=c["delay_ci"],
                diff_vs_best=round(dm, 3), diff_ci=round(dh, 3),
                worse_than_best_significant=bool(s and dm > 0))
        n_not_sig = sum(1 for v in sig.values()
                        if not v["worse_than_best_significant"])
        surf[lv] = dict(
            best_setback=best["setback"], best_max_gap=best["max_gap"],
            best_delay=best["delay"], best_ci=best["delay_ci"],
            n_cells_statistically_tied_with_best=n_not_sig,
            cells=sig,
            grid={f"{sb:g}|{mg:g}": dict(
                delay=c["delay"], ci=c["delay_ci"],
                delay_major=c["delay_major"], delay_minor=c["delay_minor"],
                stops=c["stops"], throughput=c["throughput"],
                teleports=c["teleports"], completion=c["completion"],
                A_f_gapout=c["A_f_gapout"], A_f_maxout=c["A_f_maxout"],
                A_f_premature_gapout=c["A_f_premature_gapout"],
                A_f_cut_with_blind_queue=c["A_f_cut_with_blind_queue"],
                C_f_premature_gapout=c["C_f_premature_gapout"],
                C_f_cut_with_blind_queue=c["C_f_cut_with_blind_queue"])
                  for (sb, mg), c in sorted(cells.items())})
    res["E1_surface"] = surf

    # ---------- E2: custom-tuned vs SUMO default vs Webster ----------
    e2 = {}
    for lv in ("low", "med", "high"):
        auto = C.get(("E2", "auto_default", lv))
        web = C.get(("E2", "webster", lv))
        if not auto or lv not in surf:
            continue
        bsb, bmg = surf[lv]["best_setback"], surf[lv]["best_max_gap"]
        best = C[("E1", f"sb{bsb:g}_mg{bmg:g}", lv)]
        # the custom cell that reproduces SUMO's own default placement:
        # detector-gap 2.0 s -> 33.3 m major / 22.2 m minor; nearest grid cell
        # with the default max-gap of 3.0 s is setback 25 m.
        near = C.get(("E1", "sb25_mg3", lv))
        dm, dh, s = paired_diff_ci(auto["_v_delay"], best["_v_delay"])
        dw, dwh, sw = paired_diff_ci(auto["_v_delay"], web["_v_delay"])
        e2[lv] = dict(
            webster_delay=web["delay"], webster_ci=web["delay_ci"],
            webster_major=web["delay_major"], webster_minor=web["delay_minor"],
            auto_default_delay=auto["delay"], auto_default_ci=auto["delay_ci"],
            auto_major=auto["delay_major"], auto_minor=auto["delay_minor"],
            best_custom_delay=best["delay"], best_custom_ci=best["delay_ci"],
            best_setback=bsb, best_max_gap=bmg,
            custom25mg3_delay=near["delay"] if near else None,
            auto_minus_best=round(dm, 3), auto_minus_best_ci=round(dh, 3),
            auto_worse_than_best_significant=bool(s and dm > 0),
            auto_minus_webster=round(dw, 3),
            auto_beats_webster_significant=bool(sw and dw < 0))
    res["E2_default_vs_tuned"] = e2

    # ---------- E3: per-approach setback ----------
    e3 = {}
    for exp, road, pre in (("E3major", "major", "A"), ("E3minor", "minor", "C")):
        for lv in ("low", "med", "high"):
            cells = {c["setback"] if exp == "E3major" else c["setback"]: c
                     for c in C.values() if c["exp"] == exp and c["level"] == lv}
            cs = [c for c in C.values() if c["exp"] == exp and c["level"] == lv]
            if not cs:
                continue
            key = "delay_" + road
            cs.sort(key=lambda c: float(c["name"].replace("majsb", "")
                                        .replace("minsb", "")))
            best = min(cs, key=lambda c: c[key])
            rowlist = []
            for c in cs:
                sb = float(c["name"].replace("majsb", "").replace("minsb", ""))
                dm, dh, s = paired_diff_ci(c["_v_" + key], best["_v_" + key])
                rowlist.append(dict(
                    setback=sb, delay=c[key], ci=c[key + "_ci"],
                    diff_vs_best=round(dm, 3), diff_ci=round(dh, 3),
                    significant=bool(s),
                    f_premature_gapout=c[pre + "_f_premature_gapout"],
                    f_cut_with_blind_queue=c[pre + "_f_cut_with_blind_queue"],
                    mean_blind_veh=c[pre + "_mean_blind_veh"],
                    mean_blind_slow=c[pre + "_mean_blind_slow"],
                    mean_imminent=c[pre + "_mean_imminent"],
                    mean_unseen_imminent=c[pre + "_mean_unseen_imminent"],
                    f_premature_gapout_anyimminent=c[pre + "_f_premature_gapout_anyimminent"],
                    f_gapout=c[pre + "_f_gapout"], f_maxout=c[pre + "_f_maxout"],
                    mean_green=c[pre + "_mean_green"]))
            best_sb = float(best["name"].replace("majsb", "").replace("minsb", ""))
            e3[f"{road}_{lv}"] = dict(
                road=road, level=lv, best_setback=best_sb,
                sumo_default_setback=round(2.0 * (16.667 if road == "major"
                                                  else 11.111), 1),
                ties=[r["setback"] for r in rowlist if not r["significant"]],
                rows=rowlist)
    res["E3_per_approach"] = e3

    # ---------- E4/E5: faults ----------
    def fault_table(tag):
      faults = {}
      for lv in ("low", "med", "high"):
        web = C.get(("E2", "webster", lv))
        hea = C.get(("E4" + tag, "healthy", lv))
        if not hea or not web:
            continue
        tbl = {}
        for (exp, nm, l), c in C.items():
            if l != lv or exp not in ("E4" + tag, "E5" + tag):
                continue
            dh_, hh, sh = paired_diff_ci(c["_v_delay_robust"], hea["_v_delay_robust"])
            dw_, wh, sw = paired_diff_ci(c["_v_delay_robust"], web["_v_delay_robust"])
            tbl[nm] = dict(
                exp=exp,
                delay=c["delay"], delay_ci=c["delay_ci"],
                delay_robust=c["delay_robust"], delay_robust_ci=c["delay_robust_ci"],
                throughput=c["throughput"], throughput_ci=c["throughput_ci"],
                completion=c["completion"], teleports=c["teleports"],
                stops=c["stops"],
                A_mean_green=c["A_mean_green"], A_f_maxout=c["A_f_maxout"],
                C_mean_green=c["C_mean_green"],
                stuckon_max_tsd=c.get("stuckon_max_tsd"),
                vs_healthy_diff=round(dh_, 2), vs_healthy_ci=round(hh, 2),
                vs_healthy_sig=bool(sh),
                vs_webster_diff=round(dw_, 2), vs_webster_ci=round(wh, 2),
                vs_webster_sig=bool(sw),
                WORSE_THAN_WEBSTER=bool(sw and dw_ > 0))
        tbl["webster"] = dict(exp="E2", delay=web["delay"], delay_ci=web["delay_ci"],
                              delay_robust=web["delay_robust"],
                              delay_robust_ci=web["delay_robust_ci"],
                              throughput=web["throughput"],
                              throughput_ci=web["throughput_ci"],
                              completion=web["completion"],
                              teleports=web["teleports"], stops=web["stops"])
        faults[lv] = tbl
      return faults
    res["E4_E5_faults"] = fault_table("")            # tuned cell setback 40 / max-gap 2
    res["E4_E5_faults_alt"] = fault_table("b")       # robustness: setback 25 / max-gap 3

    # ---------- critical demand at which a fault beats fixed-time ----------
    crit = {}
    for tag, key in (("", "E4_E5_faults"), ("b", "E4_E5_faults_alt")):
        for nm in ("stuckon_major", "stuckon_partial", "stuckoff_partial",
                   "stuckoff_minor", "stuckoff_major", "healthy",
                   "failsafe_healthy", "failsafe_stuckon_major"):
            worse = [lv for lv in ("low", "med", "high")
                     if res[key].get(lv, {}).get(nm, {}).get("WORSE_THAN_WEBSTER")]
            crit[f"{nm}{'_alt' if tag else ''}"] = dict(
                worse_than_webster_at=worse,
                first_level=worse[0] if worse else None)
    res["critical_demand_vs_webster"] = crit

    # ---------- teleport / validity audit ----------
    tel = [dict(exp=c["exp"], name=c["name"], level=c["level"],
                teleports=c["teleports"], completion=c["completion"],
                delay=c["delay"], delay_robust=c["delay_robust"])
           for c in C.values()
           if (c["teleports"] or 0) > 0 or (c["completion"] or 1) < 0.999]
    tel.sort(key=lambda r: -(r["teleports"] or 0))
    res["validity_audit"] = dict(
        n_cells=len(C),
        n_cells_with_teleports=sum(1 for c in C.values() if (c["teleports"] or 0) > 0),
        n_cells_incomplete=sum(1 for c in C.values() if (c["completion"] or 1) < 0.999),
        max_teleports=max((c["teleports"] or 0) for c in C.values()),
        flagged=tel[:60])

    json.dump(res, open(os.path.join(outdir, "analysis.json"), "w"), indent=2)
    print(json.dumps({k: (v if k in ("validity_audit",) else "...")
                      for k, v in res.items()}, indent=1)[:1500])
    return res, C


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
