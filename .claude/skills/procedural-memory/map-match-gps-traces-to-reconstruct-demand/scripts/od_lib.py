"""OD aggregation of matched routes via SUMO's own tools/route/route2OD.py.

Three tool mechanics that bite:
 1. route2OD.py only reads <vehicle>/<trip>/<flow> elements. tracemapper emits BARE
    <route id=".." edges=".."/> under a <routes> root, so route2OD finds ZERO
    vehicles in raw tracemapper output ("read 0 vehicles"). The routes must be
    wrapped in <vehicle> elements with a depart time, which tracemapper also does not
    emit -- we use the first probe timestamp, which is what a real feed gives you.
 2. route2OD assigns an edge's TAZ by `random.choice(edgeFromTaz[edge])` when an edge
    belongs to several TAZ, and DROPS the trip entirely when the edge belongs to none.
    A TAZ file built only from plausible trip-END edges therefore silently loses every
    trip whose matched origin/destination landed on some other edge. We build a
    full-coverage TAZ (every edge in exactly one district) so route2OD keeps
    everything, and separately count what the trip-end-only TAZ would have lost.
 3. route2OD.py ALWAYS exits with code 1, even on complete success: its main() has no
    return statement, so `if not main(get_options()): sys.exit(1)` at the bottom of
    the file fires unconditionally (verified in SUMO 1.27.1). Success must be judged
    from the output file and the "Wrote N OD-pairs" stdout line, never the exit code.

route2OD keys the OD on edges[0] and edges[-1] ONLY, so interior route error cannot
reach the OD matrix, while origin/destination snapping error passes straight through.
"""
import os, sys, json, subprocess, collections
sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
import numpy as np
import sumolib

R2OD = os.path.join(os.environ["SUMO_HOME"], "tools", "route", "route2OD.py")


def write_vehicle_routes(path, routes, departs):
    with open(path, "w") as f:
        f.write('<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n')
        for v in sorted(routes, key=lambda s: departs.get(s, 0.)):
            e = routes[v]
            if not e:
                continue
            f.write('    <vehicle id="%s" depart="%.2f">\n        <route edges="%s"/>\n    </vehicle>\n'
                    % (v, departs.get(v, 0.), " ".join(e)))
        f.write('</routes>\n')


def write_full_taz(path, edge2taz):
    z = collections.defaultdict(list)
    for e, t in edge2taz.items():
        z[t].append(e)
    with open(path, "w") as f:
        f.write('<additional>\n')
        for t in sorted(z):
            f.write('    <taz id="%s" edges="%s"/>\n' % (t, " ".join(sorted(z[t]))))
        f.write('</additional>\n')
    return sorted(z)


def run_route2od(routefile, tazfile, outfile):
    if os.path.exists(outfile):
        os.remove(outfile)
    p = subprocess.run([sys.executable, R2OD, "-r", routefile, "-a", tazfile,
                        "-o", outfile], capture_output=True, text=True)
    # NB: returncode is 1 even on success -- see module docstring note 3.
    if not os.path.exists(outfile) or "Wrote" not in p.stdout:
        raise RuntimeError("route2OD produced no OD (stdout=%r stderr=%r)"
                           % (p.stdout[-400:], p.stderr[-400:]))
    return p.stdout


def read_tazrelations(path):
    od = collections.defaultdict(float)
    for iv in sumolib.xml.parse(path, "interval"):
        if iv.tazRelation is None:
            continue
        for r in iv.tazRelation:
            od[(r.attr_from, r.to)] += float(r.count)
    return dict(od)


# ------------------------------------------------------------------ metrics
# geh / rmsn reused from the estimate-od-matrix-with-odme skill's odme_core.py
def geh(m, c):
    m, c = np.asarray(m, float), np.asarray(c, float)
    den = (m + c) / 2.0
    out = np.zeros_like(den)
    nz = den > 0
    out[nz] = np.sqrt((m[nz] - c[nz]) ** 2 / den[nz])
    return out


def rmsn(m, c):
    m, c = np.asarray(m, float), np.asarray(c, float)
    s = c.sum()
    return float("nan") if s <= 0 else 100.0 * np.sqrt(len(c) * np.sum((m - c) ** 2)) / s


def od_metrics(est, truth, scale=1.0):
    """est/truth: dict (o,d)->count. est is multiplied by `scale` (=1/penetration)."""
    cells = sorted(set(est) | set(truth))
    e = np.array([est.get(c, 0.) * scale for c in cells])
    t = np.array([truth.get(c, 0.) for c in cells])
    g = geh(e, t)
    T = t.sum()
    den = np.sqrt(np.sum((t - t.mean()) ** 2) * np.sum((e - e.mean()) ** 2))
    corr = float(np.sum((t - t.mean()) * (e - e.mean())) / den) if den > 0 else float("nan")
    return dict(
        n_cells=len(cells),
        cell_rmse=float(np.sqrt(np.mean((e - t) ** 2))),
        cell_rmsn_pct=float(rmsn(e, t)),
        cell_mae=float(np.abs(e - t).mean()),
        cell_corr=corr,
        geh_mean=float(g.mean()), geh_max=float(g.max()),
        geh_lt5_pct=100.0 * float((g < 5).mean()),
        total_est=float(e.sum()), total_true=float(T),
        total_flow_err_pct=100.0 * float(e.sum() - T) / T if T else float("nan"),
        share_misallocated_pct=100.0 * float(np.abs(e - t).sum() / (2 * T)) if T else float("nan"),
    )
