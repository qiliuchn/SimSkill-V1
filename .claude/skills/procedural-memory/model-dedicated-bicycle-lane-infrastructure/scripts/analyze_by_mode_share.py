#!/usr/bin/env python3
"""
Parse the 6 raw tripinfo files (2 variants x 3 mode-share levels) directly and
compute, SEPARATELY for cars and bicycles at each level+variant:
  - throughput (number of arrived tripinfo records)
  - mean travel time (s)   = mean(duration)
  - mean time loss (s)     = mean(timeLoss)
  - mean speed (m/s)       = mean(routeLength/duration) per vehicle
  - mean route length (m)  = mean(routeLength)   [route-length artifact check]

Writes comparison_table.csv + comparison_table.md and a PNG plot of car delay
vs bicycle mode share overlaying both infrastructure variants.
All numbers come straight from the tripinfo XML -- nothing is hand-entered.
"""
import csv
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LEVELS = [("05", 5), ("20", 20), ("40", 40)]
VARIANTS = ["mixed", "dedicated"]
VCLASSES = {"car": "car", "bike": "bike"}   # vType -> label
WORK = "."


def load(tag):
    """tag like 'mixed_20' -> {'car':[recs], 'bike':[recs]}"""
    out = {"car": [], "bike": []}
    for _, t in ET.iterparse(f"{WORK}/tripinfo_{tag}.xml", events=("end",)):
        if t.tag != "tripinfo":
            continue
        vt = t.get("vType")
        if vt in out:
            dur = float(t.get("duration"))
            rl = float(t.get("routeLength"))
            out[vt].append({
                "duration": dur,
                "timeLoss": float(t.get("timeLoss")),
                "routeLength": rl,
                "speed": rl / dur if dur > 0 else float("nan"),
            })
        t.clear()
    return out


def mean(rows, k):
    return sum(r[k] for r in rows) / len(rows) if rows else float("nan")


def main():
    rows = []
    data = {}   # (variant, lvlstr) -> loaded
    for lvlstr, pct in LEVELS:
        for var in VARIANTS:
            tag = f"{var}_{lvlstr}"
            d = load(tag)
            data[(var, lvlstr)] = d
            for vt in ("car", "bike"):
                r = d[vt]
                rows.append({
                    "bike_share_pct": pct,
                    "variant": var,
                    "vClass": vt,
                    "throughput": len(r),
                    "mean_travel_time_s": round(mean(r, "duration"), 2),
                    "mean_time_loss_s": round(mean(r, "timeLoss"), 2),
                    "mean_speed_mps": round(mean(r, "speed"), 3),
                    "mean_route_len_m": round(mean(r, "routeLength"), 1),
                })

    cols = ["bike_share_pct", "variant", "vClass", "throughput",
            "mean_travel_time_s", "mean_time_loss_s", "mean_speed_mps", "mean_route_len_m"]

    with open("comparison_table.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    # Markdown table
    with open("comparison_table.md", "w") as f:
        f.write("| " + " | ".join(cols) + " |\n")
        f.write("|" + "|".join(["---"] * len(cols)) + "|\n")
        for r in rows:
            f.write("| " + " | ".join(str(r[c]) for c in cols) + " |\n")

    # ---- Plot: CAR delay vs bicycle mode share, both variants ----
    xs = [pct for _, pct in LEVELS]
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.5))
    styles = {"mixed": dict(color="#d1495b", marker="o"),
              "dedicated": dict(color="#2e86ab", marker="s")}
    for var in VARIANTS:
        tt = [data[(var, l)]["car"] for l, _ in LEVELS]
        travel = [mean(r, "duration") for r in tt]
        tloss = [mean(r, "timeLoss") for r in tt]
        ax[0].plot(xs, travel, label=f"{var}", **styles[var])
        ax[1].plot(xs, tloss, label=f"{var}", **styles[var])
    for a, title, yl in ((ax[0], "Car mean travel time", "mean travel time (s)"),
                         (ax[1], "Car mean time loss", "mean time loss (s)")):
        a.set_xlabel("bicycle mode share (%)")
        a.set_ylabel(yl)
        a.set_title(title)
        a.set_xticks(xs)
        a.grid(True, alpha=0.3)
        a.legend()
    fig.suptitle("Car delay vs bicycle mode share: MIXED lane vs DEDICATED bike lane\n"
                 "(2 km single-direction arterial, 200 trips, identical demand/seed per level)")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig("car_delay_vs_bike_share.png", dpi=130)
    print("Wrote comparison_table.csv, comparison_table.md, car_delay_vs_bike_share.png")

    # console summary of headline
    print("\nCAR mean travel time (s):")
    for var in VARIANTS:
        vals = [round(mean(data[(var, l)]["car"], "duration"), 1) for l, _ in LEVELS]
        print(f"  {var:10s} 5%={vals[0]:7.1f}  20%={vals[1]:7.1f}  40%={vals[2]:7.1f}")
    print("CAR mean time loss (s):")
    for var in VARIANTS:
        vals = [round(mean(data[(var, l)]["car"], "timeLoss"), 1) for l, _ in LEVELS]
        print(f"  {var:10s} 5%={vals[0]:7.1f}  20%={vals[1]:7.1f}  40%={vals[2]:7.1f}")
    g_tt = mean(data[("mixed", "40")]["car"], "duration") - mean(data[("dedicated", "40")]["car"], "duration")
    g_tl = mean(data[("mixed", "40")]["car"], "timeLoss") - mean(data[("dedicated", "40")]["car"], "timeLoss")
    print(f"\nHEADLINE at 40% bikes: car travel-time gap (mixed-dedicated) = {g_tt:.1f} s; "
          f"time-loss gap = {g_tl:.1f} s")


if __name__ == "__main__":
    main()
