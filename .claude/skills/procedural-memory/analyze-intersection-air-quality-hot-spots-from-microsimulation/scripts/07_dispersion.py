#!/usr/bin/env python3
"""
Step 7 -- CAL3QHC-style Gaussian FINITE-LINE-SOURCE dispersion model.

What this implements
--------------------
Each 25 m link segment produced by step 6 becomes a finite line source with its
own emission rate q_L (g/(m*s)).  The finite line source is integrated
numerically: it is split into sub-elements of length dl, each treated as a
ground-level Gaussian point source with full ground reflection

    C(x, y) = Q / (pi * u * sigma_y * sigma_z) * exp(-y^2 / (2 sigma_y^2))

(the factor 2 from ground reflection at H=0 has already been folded in: the
usual 1/(2*pi*u*sy*sz) * 2).  x is downwind distance, y crosswind distance, both
in the wind-aligned frame.  Sub-elements with x < X_MIN are dropped (the plume
formula is undefined at/upwind of the source).

Dispersion coefficients: Briggs (1973) URBAN sigma curves, appropriate for an
urban signalised intersection.  Initial dispersion is added in quadrature:
  sigma_z0 = 1.5 m   (CALINE3/CAL3QHC initial vertical dispersion over a road)
  sigma_y0 = W/sqrt(12) with W = roadway width (3 lanes * 3.2 m = 9.6 m),
             i.e. the std-dev of a uniform lateral source of width W -- this
             restores the physical roadway width that collapsing each direction
             onto one centreline removed.

HONEST LIMITATIONS (not a bit-exact EPA CAL3QHC reproduction):
  * CAL3QHC's mixing-zone residence-time formulation and its averaging-time
    correction on sigma_y are NOT reproduced; we use Briggs urban sigmas
    directly for the 1 h average.
  * CAL3QHC's own queue-link module (which estimates idling emissions from
    signal timing analytically) is REPLACED here by microsimulated,
    position-resolved emission rates -- that substitution is the point of the
    exercise.
  * Receptors closer than about one roadway half-width sit inside the mixing
    zone where any Gaussian plume model is least reliable; a sensitivity to
    X_MIN is reported for exactly those receptors.

Outputs go to --out-dir:
    grid_<scen>_<variant>_<poll>.npz   receptor grid concentration per wind dir
    discrete_receptors.csv             all discrete receptor results
    peak_summary.csv                   peak grid concentration + location
    dispersion_config.json
    massfeed_check.csv                 mass fed to the model vs SUMO totals
"""
import argparse
import csv
import json
import math
import os

import numpy as np

# ------------------------------------------------------------------ config --
SIGZ0 = 1.5                     # m, initial vertical dispersion
ROAD_W = 9.6                    # m, one direction's roadway width (3 x 3.2 m)
SIGY0 = ROAD_W / math.sqrt(12)  # m, initial lateral dispersion (2.77 m)
X_MIN = 1.0                     # m, minimum downwind distance kept
SUBEL = 25                      # sub-elements per segment
GRID_HALF = 150.0
GRID_STEP = 5.0          # outer grid
FINE_HALF = 60.0         # inner grid half-width
FINE_STEP = 1.0          # inner grid step (a 5 m grid understates the peak by
                         # ~11%, verified in outputs/dispersion/verification.txt)
HALFROAD = ROAD_W               # distance from centreline to kerb (both dirs)
SETBACKS = [3.0, 10.0, 25.0, 50.0]
QUADRANTS = {"NE": (1, 1), "SE": (1, -1), "SW": (-1, -1), "NW": (-1, 1)}
PPM_CO = 1145.0                 # ug/m3 per ppm CO at 25 C, 1 atm

POLL = ["CO", "NOx", "PMx", "CO2"]


def briggs_urban(x, cls):
    """Briggs (1973) urban dispersion coefficients.  x in m."""
    x = np.maximum(x, 1e-6)
    if cls in ("A", "B"):
        sy = 0.32 * x / np.sqrt(1 + 0.0004 * x)
        sz = 0.24 * x * np.sqrt(1 + 0.001 * x)
    elif cls == "C":
        sy = 0.22 * x / np.sqrt(1 + 0.0004 * x)
        sz = 0.20 * x
    elif cls == "D":
        sy = 0.16 * x / np.sqrt(1 + 0.0004 * x)
        sz = 0.14 * x / np.sqrt(1 + 0.0003 * x)
    else:                                    # E, F
        sy = 0.11 * x / np.sqrt(1 + 0.0004 * x)
        sz = 0.08 * x / np.sqrt(1 + 0.0015 * x)
    return sy, sz


def build_receptors():
    """Nested receptor grid: FINE_STEP inside +-FINE_HALF, GRID_STEP outside."""
    f = np.arange(-FINE_HALF, FINE_HALF + 1e-9, FINE_STEP)
    FX, FY = np.meshgrid(f, f, indexing="ij")
    fine = np.column_stack([FX.ravel(), FY.ravel()])
    g = np.arange(-GRID_HALF, GRID_HALF + 1e-9, GRID_STEP)
    GX, GY = np.meshgrid(g, g, indexing="ij")
    coarse = np.column_stack([GX.ravel(), GY.ravel()])
    keep = (np.abs(coarse[:, 0]) > FINE_HALF) | (np.abs(coarse[:, 1]) > FINE_HALF)
    grid = np.vstack([fine, coarse[keep]])
    axis = f
    disc, names = [], []
    for q, (sx, sy) in QUADRANTS.items():
        for s in SETBACKS:
            disc.append((sx * (HALFROAD + s), sy * (HALFROAD + s)))
            names.append(f"corner_{q}_{int(s)}m")
    # supplementary mid-approach sidewalk receptors, 100 m from the stop line
    for arm, (bx, by) in (("N", (0, 1)), ("S", (0, -1)), ("E", (1, 0)), ("W", (-1, 0))):
        for s in SETBACKS:
            if arm in ("N", "S"):
                disc.append((HALFROAD + s, by * 100.0))
            else:
                disc.append((bx * 100.0, HALFROAD + s))
            names.append(f"midapproach_{arm}_{int(s)}m")
    return grid, axis, np.array(disc), names


def kernel_matrix(recept, segs, wind_from_deg, u, cls, subel=SUBEL, x_min=X_MIN):
    """M[r, s] = sum_i kernel(r, sub-element i of segment s) * dl_i   [s/m^2].

    C[r] = sum_s M[r, s] * q_L[s]   with q_L in g/(m*s)  ->  C in g/m^3.
    """
    phi = math.radians(wind_from_deg)
    ux, uy = -math.sin(phi), -math.cos(phi)      # direction the wind blows TO
    vx, vy = -uy, ux                             # crosswind unit vector
    M = np.zeros((len(recept), len(segs)), dtype=np.float64)
    rx = recept[:, 0][:, None]
    ry = recept[:, 1][:, None]
    for si, (x0, y0, x1, y1, L) in enumerate(segs):
        n = subel
        f = (np.arange(n) + 0.5) / n
        px = x0 + f * (x1 - x0)
        py = y0 + f * (y1 - y0)
        dl = L / n
        dx = rx - px[None, :]
        dy = ry - py[None, :]
        xd = dx * ux + dy * uy
        yd = dx * vx + dy * vy
        ok = xd >= x_min
        sy, sz = briggs_urban(np.where(ok, xd, 1.0), cls)
        sy = np.sqrt(sy ** 2 + SIGY0 ** 2)
        sz = np.sqrt(sz ** 2 + SIGZ0 ** 2)
        k = np.where(ok,
                     np.exp(-0.5 * (yd / sy) ** 2) / (math.pi * u * sy * sz),
                     0.0)
        M[:, si] = k.sum(axis=1) * dl
    return M


def load_segments(csv_path):
    rows = list(csv.DictReader(open(csv_path)))
    return rows


def seg_key(r):
    return (r["edge"], int(r["bin"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", nargs="+", required=True,
                    help="segments_<scen>.csv files (one per scenario)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--wind-speed", type=float, default=1.0)
    ap.add_argument("--stability", default="D")
    ap.add_argument("--wind-step", type=float, default=10.0)
    ap.add_argument("--duration-s", type=float, default=3600.0)
    ap.add_argument("--sumo-totals", nargs="*", default=[],
                    help="emissions_<scen>.json files for the mass-feed check")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)

    # -------- canonical segment geometry (identical across scenarios) -------
    per_scen = {}
    canon = {}
    for p in a.segments:
        rows = load_segments(p)
        scen = rows[0]["scenario"]
        per_scen[scen] = rows
        for r in rows:
            canon.setdefault(seg_key(r), r)
    keys = sorted(canon)
    geom = np.array([[float(canon[k]["x0"]), float(canon[k]["y0"]),
                      float(canon[k]["x1"]), float(canon[k]["y1"]),
                      max(1e-3, float(canon[k]["length_m"]))] for k in keys])
    kind = [canon[k]["kind"] for k in keys]
    edge_of = [canon[k]["edge"] for k in keys]

    # -------- per-scenario source strengths, two variants -------------------
    # variant "segment"  : each 25 m segment keeps its own measured mass
    # variant "edgeavg"  : each EDGE's total mass spread uniformly per metre
    qL = {}          # (scen, variant, poll) -> array g/(m*s)
    massfeed = []
    for scen, rows in per_scen.items():
        idx = {seg_key(r): r for r in rows}
        for poll in POLL:
            m_seg = np.array([float(idx[k][f"{poll}_mg"]) if k in idx else 0.0
                              for k in keys])                     # mg per hour
            g_seg = m_seg / 1000.0                                # g
            qL[(scen, "segment", poll)] = g_seg / a.duration_s / geom[:, 4]
            # edge-average variant
            g_avg = g_seg.copy()
            for e in set(edge_of):
                sel = [i for i, ee in enumerate(edge_of) if ee == e]
                tot = g_seg[sel].sum()
                Ltot = geom[sel, 4].sum()
                if Ltot > 0:
                    g_avg[sel] = tot * geom[sel, 4] / Ltot
            qL[(scen, "edgeavg", poll)] = g_avg / a.duration_s / geom[:, 4]
            massfeed.append({"scenario": scen, "pollutant": poll,
                             "mass_fed_to_model_g": g_seg.sum(),
                             "mass_fed_edgeavg_g": g_avg.sum()})

    # -------- mass-feed reconciliation against SUMO's own totals ------------
    sumo_tot = {}
    for p in a.sumo_totals:
        d = json.load(open(p))
        sumo_tot[d["scenario"]] = d
    for row in massfeed:
        d = sumo_tot.get(row["scenario"])
        if not d:
            continue
        poll = row["pollutant"]
        r1 = d["R1_fleet_total_mg"][poll] / 1000.0
        r2 = d["reconciliation"][poll]["R2_edgeData_sum_mg"] / 1000.0
        row["sumo_R1_trajectory_g"] = r1
        row["sumo_R2_edgeData_g"] = r2
        row["rel_err_vs_R1"] = (row["mass_fed_to_model_g"] - r1) / r1 if r1 else 0.0
        row["rel_err_vs_R2"] = (row["mass_fed_to_model_g"] - r2) / r2 if r2 else 0.0
    with open(os.path.join(a.out_dir, "massfeed_check.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(massfeed[0]))
        w.writeheader()
        for r in massfeed:
            w.writerow(r)

    # -------- receptors and wind sweep --------------------------------------
    grid, axis, disc, disc_names = build_receptors()
    recept = np.vstack([grid, disc])
    ngrid = len(grid)
    winds = np.arange(0.0, 360.0, a.wind_step)

    conc = {}    # (scen, variant, poll) -> array [nwind, nrecept] in ug/m3
    for k in qL:
        conc[k] = np.zeros((len(winds), len(recept)))
    for wi, wd in enumerate(winds):
        M = kernel_matrix(recept, geom, wd, a.wind_speed, a.stability)
        for k, q in qL.items():
            conc[k][wi] = (M @ q) * 1e6          # g/m3 -> ug/m3
        print(f"  wind {wd:5.1f} deg done", flush=True)

    # -------- save ----------------------------------------------------------
    np.savez_compressed(os.path.join(a.out_dir, "grid_axis.npz"),
                        axis=axis, winds=winds, grid_xy=grid,
                        fine_half=FINE_HALF, fine_step=FINE_STEP,
                        seg_x0=geom[:, 0], seg_y0=geom[:, 1],
                        seg_x1=geom[:, 2], seg_y1=geom[:, 3])
    peak_rows, disc_rows = [], []
    for (scen, variant, poll), C in conc.items():
        np.savez_compressed(
            os.path.join(a.out_dir, f"grid_{scen}_{variant}_{poll}.npz"),
            conc=C[:, :ngrid].astype(np.float32), winds=winds, axis=axis)
        for wi, wd in enumerate(winds):
            g = C[wi, :ngrid]
            j = int(np.argmax(g))
            peak_rows.append({
                "scenario": scen, "variant": variant, "pollutant": poll,
                "wind_from_deg": wd,
                "peak_ugm3": float(g[j]),
                "peak_x_m": float(grid[j, 0]), "peak_y_m": float(grid[j, 1]),
                "peak_ppm_CO": float(g[j] / PPM_CO) if poll == "CO" else "",
            })
            for di, nm in enumerate(disc_names):
                disc_rows.append({
                    "scenario": scen, "variant": variant, "pollutant": poll,
                    "wind_from_deg": wd, "receptor": nm,
                    "x_m": float(disc[di, 0]), "y_m": float(disc[di, 1]),
                    "conc_ugm3": float(C[wi, ngrid + di]),
                    "conc_ppm_CO": float(C[wi, ngrid + di] / PPM_CO) if poll == "CO" else "",
                })
    with open(os.path.join(a.out_dir, "peak_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(peak_rows[0]))
        w.writeheader()
        for r in peak_rows:
            w.writerow(r)
    with open(os.path.join(a.out_dir, "discrete_receptors.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(disc_rows[0]))
        w.writeheader()
        for r in disc_rows:
            w.writerow(r)

    json.dump({"wind_speed_ms": a.wind_speed, "stability_class": a.stability,
               "wind_directions_deg": list(winds),
               "sigma_curves": "Briggs 1973 urban",
               "sigma_z0_m": SIGZ0, "sigma_y0_m": SIGY0, "roadway_width_m": ROAD_W,
               "x_min_m": X_MIN, "sub_elements_per_segment": SUBEL,
               "grid_half_m": GRID_HALF, "grid_step_m": GRID_STEP,
               "fine_grid_half_m": FINE_HALF, "fine_grid_step_m": FINE_STEP,
               "setbacks_m": SETBACKS, "halfroad_m": HALFROAD,
               "averaging_period_s": a.duration_s,
               "ppm_CO_conversion_ugm3_per_ppm": PPM_CO,
               "scenarios": sorted(per_scen), "variants": ["segment", "edgeavg"],
               "pollutants": POLL,
               "n_segments": len(keys), "n_grid_receptors": ngrid,
               "discrete_receptors": disc_names},
              open(os.path.join(a.out_dir, "dispersion_config.json"), "w"), indent=2)
    print("wrote", a.out_dir)


if __name__ == "__main__":
    main()
