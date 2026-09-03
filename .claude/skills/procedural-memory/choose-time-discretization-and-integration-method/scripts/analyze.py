"""Build the deliverables: convergence table, dt-sensitivity ranking, Pareto plot.

Reference cell = dt=0.1 s, ballistic, actionStepLength pinned at 1.0 s  ("dt0.1_ballistic_pin1").
Every metric is expressed as a relative deviation from its own reference value, and each
(metric, family) pair is scored for the coarsest dt at which it is still within 2% / 5%.

Families
  tied_euler / tied_ballistic : actionStepLength follows step-length (naive refinement)
  pin1_euler / pin1_ballistic : actionStepLength pinned at 1.0 s (pure numerical resolution)
NOTE (verified): for dt<1 s SUMO force-enables ballistic whenever actionStepLength >
step-length, so pin1_euler and pin1_ballistic are the SAME simulation. They are reported
together as one family, `pin1`.
"""
import os
import sys
import json
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dtcommon import TAB, FIG, OUT, DTS, mean, sd, ci95, savejson   # noqa

REF = "dt0.1_ballistic_pin1"
FAMS = dict(tied_euler=("euler", "tied"), tied_ballistic=("ballistic", "tied"),
            pin1_euler=("euler", "pin1"), pin1_ballistic=("ballistic", "pin1"))


def load(n):
    p = os.path.join(TAB, n)
    return json.load(open(p)) if os.path.exists(p) else None


def cid(dt, meth, asl):
    return "dt%g_%s_%s" % (dt, meth, asl)


def collect():
    """metric -> {cell_id: (value, ci_halfwidth)}"""
    M = {}

    def put(name, cellid, v, h=float("nan")):
        M.setdefault(name, {})[cellid] = (v, h)

    # ---- (a) ring
    fits = load("a_ring_fits.json")
    if fits:
        for c, d in fits.items():
            f = d.get("fit")
            if not f:
                continue
            put("a_ring:q_max", c, f["q_max"])
            put("a_ring:k_crit", c, f["k_crit"])
            put("a_ring:v_free", c, f["v_free_kmh"])
            put("a_ring:wave_speed", c, abs(f["w_kmh"]))
    # ---- (b) signal
    rows = load("b_signal_runs.json")
    if rows:
        by = {}
        for r in rows:
            if r.get("ok"):
                by.setdefault(r["cell"], []).append(r)
        for c, rr in by.items():
            for key, nm in (("sat_flow", "b_signal:sat_flow"),
                            ("lost_time", "b_signal:startup_lost_time"),
                            ("mean_timeloss", "b_signal:mean_timeloss"),
                            ("mean_dur", "b_signal:mean_duration"),
                            ("co2_g_per_km", "b_signal:CO2_g_per_km"),
                            ("n_completed", "b_signal:n_completed")):
                m, h = ci95([r[key] for r in rr])
                put(nm, c, m, h)
    # ---- (c) merge
    agg = load("c_merge_agg.json")
    if agg:
        for c, d in agg.items():
            put("c_merge:n_conflicts", c, d["n_conflicts"], d["n_conflicts_ci"])
            put("c_merge:n_TTC_lt_1.5s", c, d["n_ttc_lt_15"], d["n_ttc_lt_15_ci"])
            put("c_merge:min_TTC", c, d["min_ttc"])
            put("c_merge:mean_timeloss", c, d["mean_timeloss"])
            put("c_merge:CO2_g_per_km", c, d["co2_g_per_km"])
    # ---- stability
    st = load("a_stability_agg.json")
    if st:
        for c, d in st.items():
            put("a_ring:pulse_depth", c, d["depth_frac"], d["depth_ci"])
            put("a_ring:residual_speed_sd", c, d["v_sd_tail"])
    return M


def convergence(M):
    tab = {}
    for metric, cells in M.items():
        if REF not in cells or cells[REF][0] in (None,) or (
                isinstance(cells[REF][0], float) and not math.isfinite(cells[REF][0])):
            continue
        ref = cells[REF][0]
        row = dict(reference_value=ref, families={})
        for fam, (meth, asl) in FAMS.items():
            devs = {}
            for dt in DTS:
                c = cid(dt, meth, asl)
                if c not in cells:
                    continue
                v = cells[c][0]
                if v is None or (isinstance(v, float) and not math.isfinite(v)):
                    continue
                devs["%g" % dt] = dict(value=v,
                                       rel_dev_pct=(v - ref) / ref * 100.0 if ref else float("nan"))
            if not devs:
                continue
            # coarsest dt (largest) that is within tol, requiring all finer dt also within tol
            def coarsest(tol):
                ok = None
                for dt in sorted(DTS):                       # fine -> coarse
                    k = "%g" % dt
                    if k not in devs:
                        continue
                    if abs(devs[k]["rel_dev_pct"]) <= tol:
                        ok = dt
                    else:
                        break
                return ok
            # monotonicity of |dev| as dt shrinks
            seq = [abs(devs["%g" % dt]["rel_dev_pct"]) for dt in DTS if "%g" % dt in devs]
            monotone = all(seq[i] >= seq[i + 1] - 1e-9 for i in range(len(seq) - 1))
            row["families"][fam] = dict(dev=devs, within_2pct_at_dt=coarsest(2.0),
                                        within_5pct_at_dt=coarsest(5.0),
                                        monotone_convergence=monotone,
                                        range_pct=max(abs(d["rel_dev_pct"]) for d in devs.values()))
        tab[metric] = row
    return tab


def ranking(tab):
    """Rank metrics by how much they move across the dt sweep, per family."""
    rk = []
    for metric, row in tab.items():
        f = row["families"]
        rk.append(dict(metric=metric,
                       range_tied_euler=f.get("tied_euler", {}).get("range_pct"),
                       range_tied_ballistic=f.get("tied_ballistic", {}).get("range_pct"),
                       range_pin1=f.get("pin1_ballistic", {}).get("range_pct"),
                       trust_at_dt1_tied=(abs(f.get("tied_euler", {})
                                              .get("dev", {}).get("1", {})
                                              .get("rel_dev_pct", float("inf"))) <= 5.0),
                       ))
    rk.sort(key=lambda r: -(r["range_tied_euler"] or 0))
    return rk


def pareto():
    """fidelity error vs wall-clock, using testbed (c) (SSM+emissions+delay basket)."""
    rows = load("c_merge_runs.json")
    agg = load("c_merge_agg.json")
    if not rows or not agg:
        return None
    basket = ["n_conflicts", "n_ttc_lt_15", "mean_timeloss", "co2_g_per_km"]
    ref = agg[REF]
    pts = []
    for c, d in agg.items():
        errs = []
        for b in basket:
            r0 = ref[b]
            if r0 and math.isfinite(r0) and r0 != 0:
                errs.append(abs(d[b] - r0) / abs(r0) * 100.0)
        pts.append(dict(cell=c, wall_s=d["wall"], err_pct=mean(errs),
                        dt=float(c.split("_")[0][2:]),
                        method=c.split("_")[1], asl=c.split("_")[2]))
    pts.sort(key=lambda p: p["wall_s"])
    front, best = [], float("inf")
    for p in pts:
        if p["err_pct"] < best - 1e-9:
            best = p["err_pct"]
            front.append(p["cell"])
    return dict(points=pts, pareto_front=front, basket=basket, reference=REF)


def plot(par, tab):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.4))
    ax = axes[0]
    style = {("euler", "tied"): ("o", "#d1495b", "Euler, asl tied to dt"),
             ("ballistic", "tied"): ("s", "#3a86ff", "ballistic, asl tied to dt"),
             ("euler", "pin1"): ("^", "#8ac926", "Euler, asl pinned 1.0s*"),
             ("ballistic", "pin1"): ("v", "#ffa62b", "ballistic, asl pinned 1.0s")}
    seen = set()
    for p in par["points"]:
        mk, col, lab = style[(p["method"], p["asl"])]
        ax.scatter(p["wall_s"], p["err_pct"], marker=mk, s=90, color=col, zorder=3,
                   edgecolor="k", linewidth=0.5, label=None if lab in seen else lab)
        seen.add(lab)
        ax.annotate("%g" % p["dt"], (p["wall_s"], p["err_pct"]), fontsize=7.5,
                    xytext=(4, 4), textcoords="offset points")
    fr = [p for p in par["points"] if p["cell"] in par["pareto_front"]]
    ax.plot([p["wall_s"] for p in fr], [p["err_pct"] for p in fr], "k--", lw=1, alpha=.6,
            zorder=2, label="Pareto front")
    ax.set_xscale("log")
    ax.set_xlabel("wall-clock per run (s, log)")
    ax.set_ylabel("mean |deviation| from reference cell (%)")
    ax.set_title("Fidelity vs cost - merge testbed\nbasket: conflicts, TTC<1.5s, timeLoss, CO2")
    ax.grid(alpha=.3)
    ax.legend(fontsize=7.5, loc="upper right")

    ax = axes[1]
    order = sorted([(v["families"].get("tied_euler", {}).get("range_pct", 0), k)
                    for k, v in tab.items() if "tied_euler" in v["families"]], reverse=True)
    names = [o[1] for o in order]
    te = [o[0] for o in order]
    pn = [tab[n]["families"].get("pin1_ballistic", {}).get("range_pct", 0) for n in names]
    y = range(len(names))
    ax.barh([i + .2 for i in y], te, height=.4, color="#d1495b",
            label="asl tied to dt (reaction time + numerics)")
    ax.barh([i - .2 for i in y], pn, height=.4, color="#ffa62b",
            label="asl pinned 1.0 s (numerics only)")
    ax.set_yticks(list(y))
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("max |deviation| from reference across dt in {1, 0.5, 0.25, 0.1} s  (%)")
    ax.set_title("dt-sensitivity ranking")
    ax.axvline(5, color="k", ls=":", lw=1)
    ax.grid(alpha=.3, axis="x")
    ax.legend(fontsize=8)
    fig.tight_layout()
    p = os.path.join(FIG, "fig_pareto_and_sensitivity.png")
    fig.savefig(p, dpi=150)
    print("figure ->", p)
    return p


def md_table(tab):
    lines = ["# Convergence table",
             "",
             "Reference cell: **dt = 0.1 s, ballistic, actionStepLength = 1.0 s** (`%s`)." % REF,
             "`within_2%` / `within_5%` = the COARSEST step length whose deviation from the "
             "reference is within tolerance, requiring every finer dt to be within tolerance too.",
             "`-` means no tested dt in that family met the tolerance.",
             "",
             "NOTE: for dt < 1 s the (Euler, actionStepLength pinned at 1 s) cell does not exist -- "
             "SUMO force-enables ballistic integration whenever actionStepLength > step-length "
             "(it says so on stderr). `pin1_euler` and `pin1_ballistic` are therefore identical runs.",
             ""]
    for fam in ("tied_euler", "tied_ballistic", "pin1_ballistic"):
        lines += ["", "## Family: %s" % fam, "",
                  "| metric | reference | dev @1.0s | dev @0.5s | dev @0.25s | dev @0.1s |"
                  " within 2% | within 5% | monotone |",
                  "|---|---:|---:|---:|---:|---:|:---:|:---:|:---:|"]
        for metric in sorted(tab):
            f = tab[metric]["families"].get(fam)
            if not f:
                continue
            d = f["dev"]
            g = lambda k: ("%+.2f%%" % d[k]["rel_dev_pct"]) if k in d else "-"
            lines.append("| `%s` | %.4g | %s | %s | %s | %s | %s | %s | %s |" %
                         (metric, tab[metric]["reference_value"], g("1"), g("0.5"),
                          g("0.25"), g("0.1"),
                          ("%gs" % f["within_2pct_at_dt"]) if f["within_2pct_at_dt"] else "-",
                          ("%gs" % f["within_5pct_at_dt"]) if f["within_5pct_at_dt"] else "-",
                          "yes" if f["monotone_convergence"] else "NO"))
    return "\n".join(lines)


if __name__ == "__main__":
    M = collect()
    tab = convergence(M)
    savejson("convergence_table.json", tab)
    open(os.path.join(OUT, "CONVERGENCE_TABLE.md"), "w").write(md_table(tab))
    rk = ranking(tab)
    savejson("dt_sensitivity_ranking.json", rk)
    par = pareto()
    if par:
        savejson("pareto.json", par)
        plot(par, tab)
    print("\n=== dt-SENSITIVITY RANKING (max |dev| across dt, %) ===")
    print("%-32s %14s %16s %12s" % ("metric", "tied+Euler", "tied+ballistic", "pinned 1s"))
    for r in rk:
        print("%-32s %14s %16s %12s" % (
            r["metric"],
            "%.1f" % r["range_tied_euler"] if r["range_tied_euler"] is not None else "-",
            "%.1f" % r["range_tied_ballistic"] if r["range_tied_ballistic"] is not None else "-",
            "%.1f" % r["range_pin1"] if r["range_pin1"] is not None else "-"))
    if par:
        print("\n=== PARETO FRONT (fidelity vs wall-clock) ===")
        for p in par["points"]:
            mark = "  <== front" if p["cell"] in par["pareto_front"] else ""
            print("  %-26s wall=%6.2fs  err=%7.2f%%%s" % (p["cell"], p["wall_s"], p["err_pct"], mark))
    print("\nwrote outputs/CONVERGENCE_TABLE.md and outputs/tables/{convergence_table,"
          "dt_sensitivity_ranking,pareto}.json")
