"""Figures + the population-corrected H4 optimum.

The raw "total person-hours" curve in h4h5_spacing.json uses each arm's OWN rider
population, which shrinks as spacing widens (persons whose nearest boarding and
alighting stops coincide cannot make a transit trip at all and vanish).  Here the
rider population is held FIXED at the matched cohort so the corridor-total
comparison across spacings is apples-to-apples.
"""
import os
import sys
import json
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(ROOT, "results")
FIG = os.path.join(ROOT, "figures")
os.makedirs(FIG, exist_ok=True)


def load(n):
    return json.load(open(os.path.join(RES, n)))


def h4_corrected():
    d = load("h4h5_spacing.json")
    rows = {r["spacing_m"]: r for r in d["rows"]}
    coh = {c["spacing_m"]: c for c in d["matched_cohort"]}
    N = coh[list(coh)[0]]["cohort_n_per_seed"]
    out = []
    for sp in sorted(rows):
        car = rows[sp]["car_person_hours"]
        rid_fixed = coh[sp]["cohort_mean_total_s"] * N / 3600.0
        out.append({"spacing_m": sp, "n_stops": rows[sp]["n_stops"],
                    "car_person_hours": car,
                    "cohort_rider_person_hours": round(rid_fixed, 3),
                    "corrected_total_person_hours": round(car + rid_fixed, 3),
                    "raw_total_person_hours": rows[sp]["total_person_hours"],
                    "cohort_mean_rider_time_s": coh[sp]["cohort_mean_total_s"],
                    "car_mean_loss_s": rows[sp]["car_mean_loss"]})
    best = min(out, key=lambda r: r["corrected_total_person_hours"])
    res = {"fixed_cohort_size_per_seed": N, "rows": out,
           "optimum_corrected_total_person_hours_m": best["spacing_m"],
           "note": ("rider population held fixed at the matched cohort; car "
                    "person-hours use the study's assumed car occupancy of 1.2")}
    json.dump(res, open(os.path.join(RES, "h4_population_corrected.json"), "w"), indent=1)
    print("H4 population-corrected corridor total (fixed rider cohort):")
    for r in out:
        print(f"  s={r['spacing_m']:6.0f} stops={r['n_stops']:2d} carPH={r['car_person_hours']:8.2f} "
              f"riderPH(fixed N)={r['cohort_rider_person_hours']:7.2f} "
              f"TOTAL={r['corrected_total_person_hours']:8.2f}  (raw was "
              f"{r['raw_total_person_hours']:8.2f})")
    print(f"  -> corrected optimum spacing = {best['spacing_m']} m")
    return res


def fig_h1():
    d = load("h1_bay_trap.json")
    fig, axs = plt.subplots(1, 2, figsize=(13, 5))
    for ax, L in zip(axs, (2, 1)):
        cells = [c for c in d["cells"] if c["lanes"] == L]
        for pax in sorted({c["pax_rate"] for c in cells}):
            cs = sorted([c for c in cells if c["pax_rate"] == pax], key=lambda c: c["q_per_lane"])
            x = [c["q_per_lane"] for c in cs]
            ax.errorbar(x, [c["d_car_ph"]["diff"] for c in cs],
                        yerr=[c["d_car_ph"]["half_width"] for c in cs],
                        marker="o", ls="-", label=f"cars, pax={int(pax)}/h")
            ax.errorbar(x, [c["d_rider_ph"]["diff"] for c in cs],
                        yerr=[c["d_rider_ph"]["half_width"] for c in cs],
                        marker="s", ls="--", label=f"bus riders, pax={int(pax)}/h")
        ax.axhline(0, color="k", lw=1)
        ax.set_title(f"{L} lane(s)/direction")
        ax.set_xlabel("car flow per lane (veh/h)")
        ax.set_ylabel("person-hours:  BAY  minus  IN-LANE\n(<0 = bay better)")
        ax.legend(fontsize=7, ncol=2)
        ax.grid(alpha=.3)
    fig.suptitle("H1: a bay always moves person-hours from cars to bus riders; "
                 "in SUMO's native mechanics the car saving dominates")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "h1_bay_vs_inlane.png"), dpi=140)
    print("wrote h1_bay_vs_inlane.png")


def fig_h1b():
    d = load("h1b_bay_trap_probe.json")
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for c in d["cells"]:
        x = [r["extra_penalty_s"] for r in c["by_penalty"]]
        y = [r["d_total_ph"]["diff"] for r in c["by_penalty"]]
        e = [r["d_total_ph"]["half_width"] for r in c["by_penalty"]]
        ax.errorbar(x, y, yerr=e, marker="o",
                    label=f"L{c['lanes']} q/lane={c['q_per_lane']:.0f} occ={c['bus_occupancy']:.0f} "
                          f"{c['n_stops']} stops")
    ax.axhline(0, color="k", lw=1.2)
    ax.set_xlabel("extra pull-out (re-entry) penalty per bay stop, s")
    ax.set_ylabel("total person-hours: BAY minus IN-LANE\n(>0 = the BAY TRAP)")
    ax.set_title("H1b: how large a pull-out penalty is needed before a bay costs\n"
                 "more person-hours than an in-lane stop")
    ax.legend(fontsize=8)
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "h1b_bay_trap_crossover.png"), dpi=140)
    print("wrote h1b_bay_trap_crossover.png")


def fig_h2():
    d = load("h2_nearside_farside_tsp.json")
    ps = ["nearside", "farside", "midblock"]
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.6))
    axs[0].bar(ps, [-d["placements"][p]["d_bus_loss"]["diff"] for p in ps],
               yerr=[d["placements"][p]["d_bus_loss"]["half_width"] for p in ps],
               color=["#d1495b", "#2a9d8f", "#457b9d"])
    axs[0].set_ylabel("bus time-loss SAVED by TSP (s/bus)")
    axs[0].set_title("TSP benefit to the bus")
    axs[1].bar(ps, [d["placements"][p]["tsp_grants"] for p in ps],
               color=["#d1495b", "#2a9d8f", "#457b9d"])
    axs[1].set_ylabel("priority grants per run")
    axs[1].set_title("priority grants issued")
    axs[2].bar(ps, [d["placements"][p]["d_total_ph"]["diff"] for p in ps],
               yerr=[d["placements"][p]["d_total_ph"]["half_width"] for p in ps],
               color=["#d1495b", "#2a9d8f", "#457b9d"])
    axs[2].axhline(0, color="k", lw=1)
    axs[2].set_ylabel("total person-hours, TSP minus no-TSP\n(<0 = TSP helps)")
    axs[2].set_title("net corridor person-hours effect of TSP")
    for a in axs:
        a.grid(alpha=.3, axis="y")
    fig.suptitle("H2: a near-side stop consumes the priority green -- 2x the grants, "
                 "half the benefit, and a NET LOSS in corridor person-hours")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "h2_placement_tsp.png"), dpi=140)
    print("wrote h2_placement_tsp.png")


def fig_h3():
    d = load("h3_inlane_bottleneck.json")
    fig, axs = plt.subplots(1, 2, figsize=(13, 5))
    for pax in sorted({c["pax_rate"] for c in d["cells"]}):
        cs = [c for c in d["cells"] if c["pax_rate"] == pax]
        cs = sorted(cs, key=lambda c: c["mean_dwell_s"])
        dw = [c["mean_dwell_s"] for c in cs]
        axs[0].plot(dw, [c["excess_car_loss_s"] for c in cs], "o-", label=f"pax={int(pax)}/h")
        axs[1].plot(dw, [c["n_links_spillback"] for c in cs], "o-", label=f"pax={int(pax)}/h")
    axs[0].set_xlabel("mean dwell per stop (s)")
    axs[0].set_ylabel("excess car time-loss vs no-transit control (s/veh)")
    axs[0].set_title("car delay vs INDIVIDUAL dwell length\n(each curve holds passenger demand fixed and varies bus frequency)")
    axs[1].set_xlabel("mean dwell per stop (s)")
    axs[1].set_ylabel("links whose max queue reaches 95% of link storage")
    axs[1].set_title("spillback to the upstream signal")
    for a in axs:
        a.legend()
        a.grid(alpha=.3)
    fig.suptitle("H3: one lane per direction, q=700 veh/h/dir (v/c~0.68) -- the in-lane stop as a bottleneck")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "h3_duty_cycle.png"), dpi=140)
    print("wrote h3_duty_cycle.png")


def fig_h4h5(corr):
    d = load("h4h5_spacing.json")
    rows = d["rows"]
    coh = d["matched_cohort"]
    sp = [r["spacing_m"] for r in rows]
    fig, axs = plt.subplots(1, 3, figsize=(17, 5))
    axs[0].plot(sp, [r["rider_access_s"] + r["rider_egress_s"] for r in rows], "o-", label="access+egress walk")
    axs[0].plot(sp, [r["rider_inveh_s"] for r in rows], "s-", label="in-vehicle")
    axs[0].plot(sp, [r["rider_wait_s"] for r in rows], "^-", label="wait at stop")
    axs[0].plot([c["spacing_m"] for c in coh], [c["cohort_mean_total_s"] for c in coh],
                "k*-", ms=10, label="TOTAL (matched cohort)")
    axs[0].axvline(d["analytic"]["s_star_m"], color="r", ls="--",
                   label=f"analytic s*={d['analytic']['s_star_m']:.0f} m")
    axs[0].set_xlabel("stop spacing (m)")
    axs[0].set_ylabel("seconds per rider")
    axs[0].set_title("H4: rider door-to-door time components")
    axs[0].legend(fontsize=8)
    axs[1].plot([r["spacing_m"] for r in corr["rows"]],
                [r["corrected_total_person_hours"] for r in corr["rows"]], "o-",
                label="corridor total (fixed rider cohort)")
    axs[1].plot([r["spacing_m"] for r in corr["rows"]],
                [r["car_person_hours"] for r in corr["rows"]], "s--", label="cars only")
    axs[1].plot([r["spacing_m"] for r in corr["rows"]],
                [r["cohort_rider_person_hours"] for r in corr["rows"]], "^--", label="bus riders only")
    axs[1].set_xlabel("stop spacing (m)")
    axs[1].set_ylabel("person-hours over the measurement window")
    axs[1].set_title("H4: corridor person-hours (cars @1.2 pax/veh)")
    axs[1].legend(fontsize=8)
    axs[2].plot(sp, [r["access_len_p50"] for r in rows], "o-", label="access walk p50")
    axs[2].plot(sp, [r["access_len_p90"] for r in rows], "s-", label="access walk p90")
    axs[2].plot(sp, [r["access_len_p95"] for r in rows], "^-", label="access walk p95")
    axs[2].plot(sp, [r["access_len_max"] for r in rows], "v-", label="access walk max")
    axs[2].set_xlabel("stop spacing (m)")
    axs[2].set_ylabel("access walk distance (m)")
    axs[2].set_title("H5: the tail is what consolidation moves")
    axs[2].legend(fontsize=8)
    for a in axs:
        a.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "h4h5_spacing.png"), dpi=140)
    print("wrote h4h5_spacing.png")


def fig_reentry():
    d = load("verify_dwell_model.json")
    f = load("fit_reentry_gap.json")
    fig, ax = plt.subplots(figsize=(7.5, 5))
    for L in (1, 2):
        pts = [r for r in d["parking_overhead_vs_flow"] if r["lanes_art"] == L]
        ax.plot([r["q_per_lane"] for r in pts], [r["overhead_s"] for r in pts],
                "o-", label=f"measured, {L} lane(s)/dir")
    tau = f["global_fit"]["global_tau_s"]
    xs = [x for x in range(25, 950, 25)]
    ax.plot(xs, [(math.exp(x / 3600 * tau) - 1) / (x / 3600) - tau for x in xs],
            "k--", label=f"gap acceptance, tau={tau:.1f} s")
    ax.set_xlabel("car flow in the lane the bus re-enters (veh/h/lane)")
    ax.set_ylabel("extra fixed dwell of a parking=\"true\" stop (s)")
    ax.set_title('SUMO\'s bay re-entry cost IS gap-dependent -- and it is\nabsorbed into the stop duration, not observable after the stop')
    ax.legend()
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "reentry_gap.png"), dpi=140)
    print("wrote reentry_gap.png")


if __name__ == "__main__":
    corr = h4_corrected()
    fig_h1()
    fig_h1b()
    fig_h2()
    fig_h3()
    fig_h4h5(corr)
    fig_reentry()
