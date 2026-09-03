"""Full Downs-Thomson experiment driver.

Stages (each writes a CSV into outputs/):
  1 curves      cost-vs-mode-share curves, 4 cells (base|expanded x feedback on|off)
  2 equilibria  gap-based bisection to |gap| <= TOL in all 4 cells
  3 msa         natural day-to-day (MSA) adjustment trace, feedback-on cells
  4 perturb     nudge the converged equilibrium up/down and re-simulate
  5 sweep       demand sweep: locate the regime where the paradox switches on/off
  6 headway     verification that realised headways obey the stated rule everywhere
"""
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dt_equilibrium as EQ
import dt_runner as R
import dt_scenario as S

OUT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CSV = os.path.join(OUT, "results")
os.makedirs(CSV, exist_ok=True)

N_MAIN = 3000
SEEDS = [1, 2, 3]                 # Common Random Numbers: identical across all cells
SEEDS_SWEEP = [1, 2]
TOL = 5.0                         # seconds; |C_car - C_transit| target
WORKERS = 8

CELLS = [
    ("base_fbON", S.NET_BASE, True, {}),
    ("expanded_fbON", S.NET_EXPANDED, True, {}),
    ("base_fbOFF", S.NET_BASE, False, {"h_fixed": S.H_FIXED}),
    ("expanded_fbOFF", S.NET_EXPANDED, False, {"h_fixed": S.H_FIXED}),
]


def write_csv(path, rows, fields=None):
    if not rows:
        return
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  wrote {path} ({len(rows)} rows)")


def stage_curves():
    grid = [round(0.05 * i, 2) for i in range(1, 20)]      # 0.05 .. 0.95
    rows = []
    for cell, net, fb, kw in CELLS:
        for p in grid:
            r = R.eval_point(net, N_MAIN, p, SEEDS, feedback=fb,
                             tagbase=f"cur_{cell}_{int(p*100)}", rule_kw=kw, workers=WORKERS)
            run0 = r["_runs"][0]
            rows.append(dict(cell=cell, net=r["net"], feedback=fb, n_total=N_MAIN,
                             p_car=p, n_car=r["n_car"], n_transit=r["n_transit"],
                             headway=r["headway"], headway_realised=run0["headway_realised"],
                             headway_max_dev=run0["headway_realised_max_dev"],
                             n_buses=r["n_buses_sched"],
                             car_cost=r["car_cost"], car_cost_ci=r["car_cost_ci"],
                             car_duration=r["car_duration"], car_departdelay=r["car_departdelay"],
                             transit_cost=r["transit_cost"], transit_cost_ci=r["transit_cost_ci"],
                             transit_wait=r["transit_wait"], transit_ivt=r["transit_ivt"],
                             wait_expected_schedule=run0["wait_expected_schedule"],
                             wait_h_over_2=run0["wait_h_over_2"],
                             gap=r["gap"], person_hours=r["person_hours"],
                             n_car_arrived=r["n_car_arrived"],
                             n_transit_arrived=r["n_transit_arrived"],
                             n_person_no_ride=r["n_person_no_ride"], reps=r["reps"]))
            print(f"  {cell} p={p:.2f} H={r['headway']:7.1f} Ccar={r['car_cost']:8.1f} "
                  f"Ctr={r['transit_cost']:7.1f} gap={r['gap']:+8.1f}")
            sys.stdout.flush()
    write_csv(os.path.join(CSV, "cost_curves.csv"), rows)
    return rows


def stage_equilibria():
    summary, traces, allroots = [], [], []
    for cell, net, fb, kw in CELLS:
        print(f"\n== equilibrium: {cell}")
        eq, tr, diag = EQ.solve(net, N_MAIN, SEEDS, feedback=fb, rule_kw=kw,
                                tag=f"eq_{cell}", iters=13, tol=TOL, workers=WORKERS)
        for t in tr:
            t["cell"] = cell
        traces += tr
        for rt in diag["roots"]:
            allroots.append(dict(cell=cell, n_total=N_MAIN, **rt))
        run0 = eq["_runs"][0]
        summary.append(dict(cell=cell, net=eq["net"], feedback=fb, n_total=N_MAIN,
                            p_car_eq=eq["p_car"], n_car=eq["n_car"], n_transit=eq["n_transit"],
                            headway=eq["headway"], headway_realised=run0["headway_realised"],
                            car_cost=eq["car_cost"], car_cost_ci=eq["car_cost_ci"],
                            transit_cost=eq["transit_cost"], transit_cost_ci=eq["transit_cost_ci"],
                            common_cost=0.5 * (eq["car_cost"] + eq["transit_cost"]),
                            car_duration=eq["car_duration"], car_departdelay=eq["car_departdelay"],
                            transit_wait=eq["transit_wait"], transit_ivt=eq["transit_ivt"],
                            gap=eq["gap"], abs_gap=abs(eq["gap"]),
                            converged=eq.get("converged"), corner=eq.get("corner"),
                            equilibrium_type=eq.get("equilibrium_type"),
                            n_stable_roots=diag["n_stable"], n_unstable_roots=diag["n_unstable"],
                            person_hours=eq["person_hours"], reps=eq["reps"],
                            run_dir=run0["run_dir"]))
    write_csv(os.path.join(CSV, "equilibria.csv"), summary)
    write_csv(os.path.join(CSV, "equilibrium_traces.csv"), traces)
    write_csv(os.path.join(CSV, "equilibrium_roots.csv"), allroots)
    return summary, traces


def stage_msa():
    rows = []
    starts = {"base_fbON": [0.05, 0.50, 0.95], "expanded_fbON": [0.05, 0.50, 0.95]}
    for cell, net, fb, kw in CELLS[:2]:
        for p0 in starts[cell]:
            print(f"\n== MSA adjustment dynamics: {cell} from p0={p0}")
            tr = EQ.msa_loop(net, N_MAIN, SEEDS, feedback=fb, rule_kw=kw,
                             tag=f"msa_{cell}_{int(p0*100)}", p0=p0, iters=18,
                             workers=WORKERS)
            for t in tr:
                t["cell"] = cell
            rows += tr
    write_csv(os.path.join(CSV, "msa_traces.csv"), rows)
    return rows


def stage_perturb(equilibria):
    """Nudge p away from the converged fixed point and check the sign of the gap:
    gap<0 means car is cheaper so travellers move TOWARDS car (p increases)."""
    rows = []
    byname = {e["cell"]: e for e in equilibria}
    for cell in ("base_fbON", "expanded_fbON"):
        e = byname[cell]
        net = S.NET_BASE if "base" in cell else S.NET_EXPANDED
        kw = {} if e["feedback"] else {"h_fixed": S.H_FIXED}
        pstar = e["p_car_eq"]
        for d in (-0.10, -0.05, 0.0, +0.05, +0.10):
            p = min(0.99, max(0.01, pstar + d))
            r = R.eval_point(net, N_MAIN, p, SEEDS, feedback=e["feedback"],
                             tagbase=f"pert_{cell}_{int(round(p*1000))}", rule_kw=kw,
                             workers=WORKERS)
            # direction the natural adjustment pushes p
            push = "increase p (towards car)" if r["gap"] < 0 else "decrease p (towards transit)"
            restoring = (d < 0 and r["gap"] < 0) or (d > 0 and r["gap"] > 0) or d == 0
            rows.append(dict(cell=cell, p_star=pstar, delta=d, p_car=p,
                             headway=r["headway"], car_cost=r["car_cost"],
                             transit_cost=r["transit_cost"], gap=r["gap"],
                             gap_ci=(r["car_cost_ci"] ** 2 + r["transit_cost_ci"] ** 2) ** 0.5,
                             adjustment_pushes=push, restoring=restoring))
            print(f"  {cell} p*={pstar:.4f} d={d:+.2f} p={p:.4f} gap={r['gap']:+8.1f} "
                  f"-> {push}  restoring={restoring}")
            sys.stdout.flush()
    write_csv(os.path.join(CSV, "perturbation.csv"), rows)
    return rows


def stage_sweep():
    rows, traces = [], []
    for n in (1500, 2000, 2500, 3000, 3750, 4500):
        for cell, net, fb, kw in CELLS[:2]:          # feedback ON only
            eq, tr, diag = EQ.solve(net, n, SEEDS_SWEEP, feedback=fb, rule_kw=kw,
                                    tag=f"sw_{cell}_{n}", iters=11, tol=TOL,
                                    grid=[round(0.05 + 0.05 * i, 3) for i in range(19)],
                                    workers=WORKERS, verbose=False)
            for t in tr:
                t["cell"] = cell
                t["n_total"] = n
            traces += tr
            rows.append(dict(n_total=n, cell=cell, p_car_eq=eq["p_car"],
                             n_car=eq["n_car"], n_transit=eq["n_transit"],
                             headway=eq["headway"], car_cost=eq["car_cost"],
                             transit_cost=eq["transit_cost"],
                             common_cost=0.5 * (eq["car_cost"] + eq["transit_cost"]),
                             gap=eq["gap"], corner=eq.get("corner"),
                             equilibrium_type=eq.get("equilibrium_type"),
                             n_stable_roots=diag["n_stable"],
                             n_unstable_roots=diag["n_unstable"],
                             converged=eq.get("converged"),
                             person_hours=eq["person_hours"], reps=eq["reps"]))
            print(f"  N={n} {cell}: p*={eq['p_car']:.4f} H={eq['headway']:7.1f} "
                  f"Ccar={eq['car_cost']:8.1f} Ctr={eq['transit_cost']:7.1f} "
                  f"gap={eq['gap']:+7.1f} corner={eq.get('corner')}")
            sys.stdout.flush()
    # paradox verdict per demand level
    verdict = []
    for n in sorted({r["n_total"] for r in rows}):
        b = next(r for r in rows if r["n_total"] == n and r["cell"] == "base_fbON")
        x = next(r for r in rows if r["n_total"] == n and r["cell"] == "expanded_fbON")
        d = x["common_cost"] - b["common_cost"]
        verdict.append(dict(n_total=n,
                            base_p=b["p_car_eq"], exp_p=x["p_car_eq"],
                            base_cost=b["common_cost"], exp_cost=x["common_cost"],
                            base_H=b["headway"], exp_H=x["headway"],
                            base_corner=b["corner"], exp_corner=x["corner"],
                            base_type=b["equilibrium_type"], exp_type=x["equilibrium_type"],
                            delta_cost=d, pct_change=100.0 * d / b["common_cost"],
                            paradox=("YES" if d > 0 else "no")))
    write_csv(os.path.join(CSV, "demand_sweep.csv"), rows)
    write_csv(os.path.join(CSV, "demand_sweep_verdict.csv"), verdict)
    write_csv(os.path.join(CSV, "demand_sweep_traces.csv"), traces)
    return rows, verdict


def stage_headway_audit(curve_rows):
    """VERIFICATION (ii): realised headway == rule output everywhere; frozen in control."""
    rows = []
    ok = True
    for r in curve_rows:
        rule_H = S.headway_rule(r["n_transit"], feedback=r["feedback"],
                                **({} if r["feedback"] else {"h_fixed": S.H_FIXED}))
        match = abs(r["headway_realised"] - rule_H) < 1e-6 and r["headway_max_dev"] < 1e-6
        ok = ok and match
        rows.append(dict(cell=r["cell"], p_car=r["p_car"], n_transit=r["n_transit"],
                         rule_headway=rule_H, realised_headway=r["headway_realised"],
                         max_deviation_across_schedule=r["headway_max_dev"],
                         matches_rule=match,
                         observed_mean_wait=r["transit_wait"],
                         schedule_implied_E_wait=r["wait_expected_schedule"],
                         wait_minus_schedule=r["transit_wait"] - r["wait_expected_schedule"],
                         H_over_2=r["wait_h_over_2"]))
    write_csv(os.path.join(CSV, "headway_audit.csv"), rows)
    frozen = {r["realised_headway"] for r in rows if "fbOFF" in r["cell"]}
    print(f"  headway rule matches emitted schedule in ALL {len(rows)} cases: {ok}")
    print(f"  distinct headways in feedback-OFF control cells: {frozen} (expect exactly one)")
    return rows, ok, frozen


if __name__ == "__main__":
    t0 = time.time()
    stages = sys.argv[1:] or ["curves", "eq", "msa", "perturb", "sweep"]
    state = {}
    if "curves" in stages:
        print("\n### STAGE 1: cost-vs-mode-share curves")
        state["curves"] = stage_curves()
        print("\n### STAGE 6: headway audit")
        rows, ok, frozen = stage_headway_audit(state["curves"])
        state["headway_ok"] = ok
        state["frozen_headways"] = sorted(frozen)
    if "eq" in stages:
        print("\n### STAGE 2: equilibria (gap bisection)")
        state["equilibria"], _ = stage_equilibria()
    if "msa" in stages:
        print("\n### STAGE 3: MSA adjustment dynamics")
        stage_msa()
    if "perturb" in stages and "equilibria" in state:
        print("\n### STAGE 4: perturbation / stability test")
        stage_perturb(state["equilibria"])
    if "sweep" in stages:
        print("\n### STAGE 5: demand sweep")
        state["sweep"], state["verdict"] = stage_sweep()
    with open(os.path.join(CSV, "state.json"), "w") as f:
        json.dump({k: v for k, v in state.items() if k != "curves"}, f, indent=2, default=str)
    print(f"\nTOTAL ELAPSED {time.time() - t0:.0f}s")
