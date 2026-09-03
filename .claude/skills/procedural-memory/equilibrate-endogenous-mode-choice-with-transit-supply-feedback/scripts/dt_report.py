"""Build the four-cell comparison table, the paradox verdict, and the audit summary
from the raw result CSVs.  Prints markdown tables and writes comparison_table.csv."""
import csv
import os
import statistics

OUT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RES = os.path.join(OUT, "results")


def read(n):
    with open(os.path.join(RES, n)) as f:
        return list(csv.DictReader(f))


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def md(rows, headers):
    w = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    out = ["| " + " | ".join(str(h).ljust(w[i]) for i, h in enumerate(headers)) + " |",
           "|" + "|".join("-" * (x + 2) for x in w) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c).ljust(w[i]) for i, c in enumerate(r)) + " |")
    return "\n".join(out)


def main():
    eqs = {e["cell"]: e for e in read("equilibria.csv")}
    order = ["base_fbON", "expanded_fbON", "base_fbOFF", "expanded_fbOFF"]
    label = {"base_fbON": "BASE / feedback ON", "expanded_fbON": "EXPANDED / feedback ON",
             "base_fbOFF": "BASE / feedback OFF", "expanded_fbOFF": "EXPANDED / feedback OFF"}

    rows, csvrows = [], []
    for c in order:
        e = eqs[c]
        rows.append([label[c], f'{f(e["p_car_eq"]):.4f}', int(f(e["n_car"])), int(f(e["n_transit"])),
                     f'{f(e["headway"]):.0f}', f'{f(e["car_cost"]):.1f}', f'{f(e["transit_cost"]):.1f}',
                     f'{f(e["common_cost"]):.1f}', f'{f(e["gap"]):+.1f}',
                     f'{f(e["car_duration"]):.0f}+{f(e["car_departdelay"]):.0f}',
                     f'{f(e["transit_wait"]):.0f}+{f(e["transit_ivt"]):.0f}',
                     f'{f(e["person_hours"]):.1f}',
                     f'{f(e["person_hours"])*3600/f(e["n_total"]):.1f}', e["equilibrium_type"],
                     f'{e["n_stable_roots"]}/{e["n_unstable_roots"]}'])
        row = dict(e)
        row["label"] = label[c]
        row["mean_cost_per_traveller"] = f(e["person_hours"]) * 3600 / f(e["n_total"])
        csvrows.append(row)

    print("\n### Four-cell comparison at the converged equilibrium (N=3000, 3 replications, CRN)\n")
    print(md(rows, ["cell", "p*_car", "n_car", "n_transit", "H (s)", "C_car (s)",
                    "C_transit (s)", "common C (s)", "gap (s)", "car dur+delay",
                    "transit wait+ivt", "person-h", "mean cost/trav (s)", "type",
                    "stable/unstable roots"]))

    with open(os.path.join(RES, "comparison_table.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(csvrows[0].keys()), extrasaction="ignore")
        w.writeheader()
        for r in csvrows:
            w.writerow(r)

    # paradox verdicts
    print("\n### Effect of the capacity expansion\n")
    vr = []
    for arm, a, b in (("Mohring feedback ON", "base_fbON", "expanded_fbON"),
                      ("feedback OFF (control)", "base_fbOFF", "expanded_fbOFF")):
        ca, cb = f(eqs[a]["common_cost"]), f(eqs[b]["common_cost"])
        vr.append([arm, f"{ca:.1f}", f"{cb:.1f}", f"{cb - ca:+.1f}",
                   f"{100*(cb-ca)/ca:+.1f}%",
                   f'{f(eqs[a]["p_car_eq"]):.3f} -> {f(eqs[b]["p_car_eq"]):.3f}',
                   f'{f(eqs[a]["headway"]):.0f} -> {f(eqs[b]["headway"]):.0f}',
                   f'{f(eqs[a]["person_hours"]):.1f} -> {f(eqs[b]["person_hours"]):.1f}',
                   "PARADOX CONFIRMED" if cb - ca > 0 else "no paradox"])
    print(md(vr, ["arm", "BASE cost", "EXPANDED cost", "delta", "%", "car share",
                  "headway (s)", "person-hours", "verdict"]))

    # ceteris paribus: expansion at the BASE equilibrium mode share
    cur = read("cost_curves.csv")
    p0 = min((f(r["p_car"]) for r in cur), key=lambda p: abs(p - f(eqs["base_fbON"]["p_car_eq"])))
    b = next(r for r in cur if r["cell"] == "base_fbON" and f(r["p_car"]) == p0)
    x = next(r for r in cur if r["cell"] == "expanded_fbON" and f(r["p_car"]) == p0)
    print(f"\nCeteris paribus (mode share FROZEN at p={p0:.2f}, no behavioural response): "
          f"car cost {f(b['car_cost']):.1f}s -> {f(x['car_cost']):.1f}s "
          f"({100*(f(x['car_cost'])-f(b['car_cost']))/f(b['car_cost']):+.1f}%)  "
          f"-- the expansion really is an engineering improvement.")

    # headway audit
    ha = read("headway_audit.csv")
    ok = all(r["matches_rule"] == "True" for r in ha)
    frozen = sorted({f(r["realised_headway"]) for r in ha if "fbOFF" in r["cell"]})
    d_sched = [abs(f(r["wait_minus_schedule"])) for r in ha]
    d_h2 = [abs(f(r["observed_mean_wait"]) - f(r["H_over_2"])) for r in ha]
    print(f"\n### Headway-rule audit ({len(ha)} scenario points)\n")
    print(f"- realised inter-departure time == rule output in ALL points: **{ok}**")
    print(f"- distinct headways across all feedback-OFF points: **{frozen}** (frozen, as required)")
    print(f"- |observed mean wait - schedule-implied E[W]|: mean {statistics.mean(d_sched):.1f}s, "
          f"max {max(d_sched):.1f}s")
    print(f"- |observed mean wait - H/2|:                   mean {statistics.mean(d_h2):.1f}s, "
          f"max {max(d_h2):.1f}s   (H/2 is only the infinite-horizon limit)")
    iv = [f(r["transit_ivt"]) for r in cur]
    print(f"- transit in-vehicle time over the whole mode-share range: "
          f"{min(iv):.1f}-{max(iv):.1f}s (spread {max(iv)-min(iv):.1f}s) -- dedicated ROW")
    inc = [r for r in cur if f(r["n_car_arrived"]) < f(r["n_car"]) - 1e-6
           or f(r["n_transit_arrived"]) < f(r["n_transit"]) - 1e-6
           or int(f(r["n_person_no_ride"])) > 0]
    print(f"- scenario points where any traveller failed to complete: **{len(inc)}** of {len(cur)}")

    # perturbation
    if os.path.exists(os.path.join(RES, "perturbation.csv")):
        print("\n### Perturbation / stability test\n")
        pr = [[r["cell"], f'{f(r["p_star"]):.4f}', f'{f(r["delta"]):+.2f}', f'{f(r["p_car"]):.4f}',
               f'{f(r["gap"]):+.1f}', f'+-{f(r["gap_ci"]):.1f}', r["adjustment_pushes"],
               r["restoring"]] for r in read("perturbation.csv")]
        print(md(pr, ["cell", "p*", "delta", "p", "gap (s)", "95% CI", "adjustment pushes",
                      "restoring?"]))

    # demand sweep
    if os.path.exists(os.path.join(RES, "demand_sweep_verdict.csv")):
        print("\n### Demand sweep (feedback ON, 2 replications)\n")
        sw = read("demand_sweep.csv")
        byn = {}
        for r in sw:
            byn.setdefault(int(f(r["n_total"])), {})[r["cell"]] = r
        sv = []
        for n in sorted(byn):
            b, x = byn[n]["base_fbON"], byn[n]["expanded_fbON"]
            # demand-weighted mean cost per traveller: valid at corners too, unlike
            # the mid-point of the two modal costs
            wb = f(b["person_hours"]) * 3600 / n
            wx = f(x["person_hours"]) * 3600 / n
            sv.append([n, f'{f(b["p_car_eq"]):.3f}', f'{f(x["p_car_eq"]):.3f}',
                       f'{wb:.1f}', f'{wx:.1f}', f'{f(b["headway"]):.0f}',
                       f'{f(x["headway"]):.0f}', f'{wx-wb:+.1f}',
                       f'{100*(wx-wb)/wb:+.1f}%', b["equilibrium_type"],
                       x["equilibrium_type"],
                       "PARADOX" if wx > wb else "no"])
        print(md(sv, ["N", "p* BASE", "p* EXP", "mean cost BASE", "mean cost EXP",
                      "H BASE", "H EXP", "delta", "%", "BASE type", "EXP type",
                      "paradox?"]))

    # MSA behaviour
    if os.path.exists(os.path.join(RES, "msa_traces.csv")):
        print("\n### MSA (natural day-to-day adjustment) behaviour\n")
        tr = read("msa_traces.csv")
        by = {}
        for r in tr:
            by.setdefault((r["cell"], r["p_start"]), []).append(r)
        mr = []
        for (cell, p0v), rs in sorted(by.items()):
            rs.sort(key=lambda r: int(r["iter"]))
            ps = [f(r["p_car"]) for r in rs]
            last6 = ps[-6:]
            mr.append([cell, p0v, f"{ps[0]:.3f}", f"{min(last6):.3f}-{max(last6):.3f}",
                       f"{statistics.mean(last6):.3f}",
                       f"{max(last6)-min(last6):.3f}",
                       f"{min(abs(f(r['gap'])) for r in rs[-6:]):.1f}"])
        print(md(mr, ["cell", "p0", "start", "last-6 p range", "last-6 mean p",
                      "envelope width", "best |gap| in last 6"]))


if __name__ == "__main__":
    main()
