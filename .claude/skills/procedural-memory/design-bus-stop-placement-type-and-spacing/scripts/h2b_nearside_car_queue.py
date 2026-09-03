"""H2b -- does a NEAR-SIDE stop block the intersection approach and worsen car
queues, relative to far-side / mid-block?

H2's 2-lane test found no significant difference (cars simply use the other
lane).  This isolates the approach-blocking mechanism where it can actually bite:
ONE lane per direction, no TSP, E2 detectors spanning each link so the queue on
the approach itself is measured, not inferred from aggregate delay.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg  # noqa: E402
from expbase import run_arms, paired, mean, col, validity, save  # noqa: E402

SEEDS = list(range(1, 13))


def main():
    out = {"seeds": SEEDS, "by_lane_count": {}}
    for lanes, q in ((1, 600.0), (2, 1400.0)):
        base = dict(lanes_art=lanes, q_art=q, q_cross=200.0, pax_rate=1200.0,
                    headway=150.0, stop_type="inlane")
        arms = {f"h2b_L{lanes}_{p}": Cfg(stop_placement=p, **base)
                for p in ("nearside", "farside", "midblock")}
        arms[f"h2b_L{lanes}_nobus"] = Cfg(stop_placement="farside", headway=100000.0,
                                          pax_rate=1.0,
                                          **{k: v for k, v in base.items()
                                             if k not in ("headway", "pax_rate")})
        print(f"H2b lanes={lanes}: {len(arms)} arms x {len(SEEDS)} seeds")
        res, errs = run_arms(arms, SEEDS, workers=9, tag=f"h2b{lanes}", keep=("e2",))
        ref = res[f"h2b_L{lanes}_farside"]
        nb = res[f"h2b_L{lanes}_nobus"]
        rec = {"q_art": q, "nobus": {k: round(mean(col(nb, k)), 3) for k in
                                     ("car_mean_loss", "car_art_mean_loss",
                                      "max_jam_m", "max_mean_storage_ratio")},
               "placements": {}}
        for p in ("nearside", "farside", "midblock"):
            a = res[f"h2b_L{lanes}_{p}"]
            rec["placements"][p] = {
                "car_art_mean_loss": round(mean(col(a, "car_art_mean_loss")), 3),
                "car_mean_loss": round(mean(col(a, "car_mean_loss")), 3),
                "max_jam_m": round(mean(col(a, "max_jam_m")), 2),
                "mean_storage_ratio": round(mean(col(a, "max_mean_storage_ratio")), 4),
                "n_links_spillback": round(mean(col(a, "n_links_spillback")), 2),
                "bus_mean_dur": round(mean(col(a, "bus_mean_dur")), 2),
                "mean_dwell": round(mean(col(a, "mean_dwell")), 2),
                "teleports": round(mean(col(a, "teleports")), 2),
                "vs_farside_art_loss": paired(col(ref, "car_art_mean_loss"),
                                              col(a, "car_art_mean_loss")),
                "vs_farside_jam": paired(col(ref, "max_jam_m"), col(a, "max_jam_m")),
                "vs_nobus_art_loss": paired(col(nb, "car_art_mean_loss"),
                                            col(a, "car_art_mean_loss")),
                "validity": validity(a)}
            r = rec["placements"][p]
            print(f"  {p:9s} artCarLoss={r['car_art_mean_loss']:7.2f} "
                  f"(vs farside {r['vs_farside_art_loss']['diff']:+6.2f}"
                  f"+-{r['vs_farside_art_loss']['half_width']:.2f} "
                  f"{'SIG' if r['vs_farside_art_loss']['significant'] else '   '}) "
                  f"maxJam={r['max_jam_m']:6.1f} storRatio={r['mean_storage_ratio']:.4f} "
                  f"busDur={r['bus_mean_dur']:7.1f}")
        out["by_lane_count"][str(lanes)] = rec
    save(out, "h2b_nearside_car_queue.json")


if __name__ == "__main__":
    main()
