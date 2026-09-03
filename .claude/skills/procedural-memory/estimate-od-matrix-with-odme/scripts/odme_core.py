"""Shared core for the ODME pipeline: O-format IO, SUMO plumbing, metrics.

Scenario-agnostic. Zone list and OD-pair ordering are always derived from the
seed matrix file, so every array in the pipeline stays aligned.
"""
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import numpy as np


# ------------------------------------------------------------------ binaries
def sumo_bin(name):
    """PATH -> next to `sumo` -> $SUMO_HOME/bin. SUMO tools are often not all on PATH."""
    from shutil import which
    p = which(name)
    if p:
        return p
    s = which("sumo")
    if s:
        c = os.path.join(os.path.dirname(s), name)
        if os.path.exists(c):
            return c
    sh = os.environ.get("SUMO_HOME", "")
    for c in (os.path.join(sh, "bin", name),
              os.path.join(os.path.dirname(sh.rstrip("/")), "bin", name)):
        if sh and os.path.exists(c):
            return c
    raise RuntimeError("cannot locate SUMO binary %r" % name)


def run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        sys.stderr.write("FAILED: %s\n%s\n%s\n" % (" ".join(map(str, cmd)),
                                                   r.stdout[-3000:], r.stderr[-3000:]))
        raise RuntimeError("command failed: %s" % cmd[0])
    return r


# ------------------------------------------------------------------ O-format
def read_od(path):
    """Read an O-format ($OR;D2) matrix. Returns (pairs, values, header_lines)."""
    with open(path) as f:
        raw = [l.rstrip("\n") for l in f]
    data = [l.strip() for l in raw if l.strip() and not l.strip().startswith("*")]
    if not data or not data[0].startswith("$O"):
        raise ValueError("%s is not an O-format matrix ($OR;D2 header expected)" % path)
    tag, time_line, factor_line = data[0], data[1], data[2]
    pairs, vals = [], []
    for l in data[3:]:
        p = l.split()
        if len(p) >= 3:
            pairs.append((p[0], p[1]))
            vals.append(float(p[2]))
    return pairs, np.array(vals), (tag, time_line, factor_line)


def write_od(path, pairs, vals, header, comment=""):
    tag, time_line, factor_line = header
    with open(path, "w") as f:
        f.write(tag + "\n")
        if comment:
            f.write("* %s\n" % comment)
        f.write("* From-Time  To-Time\n%s\n* Factor\n%s\n" % (time_line, factor_line))
        for (o, d), v in zip(pairs, vals):
            f.write("%s %s %.4f\n" % (o, d, max(0.0, float(v))))


# ------------------------------------------------------------------ counts IO
def read_edgedata(path, attr="entered"):
    """SUMO edgeData output -> {edge: value}, summed over all intervals.

    Use `entered` (not `left`) for link counts: under congestion, teleports remove
    vehicles mid-edge, so `left` under-counts while `entered` stays consistent with
    the routes actually driven.
    """
    counts = {}
    for iv in ET.parse(path).getroot().iter("interval"):
        for e in iv.iter("edge"):
            counts[e.get("id")] = counts.get(e.get("id"), 0.0) + float(e.get(attr, 0) or 0)
    return counts


def read_e1(path):
    counts = {}
    for iv in ET.parse(path).getroot().iter("interval"):
        counts[iv.get("id")] = counts.get(iv.get("id"), 0.0) + float(iv.get("nVehContrib", 0) or 0)
    return counts


def read_counts_file(path, edges=None, attr="entered"):
    """Accept either an edgeData XML or a two-column CSV `edge,count`."""
    if path.lower().endswith((".xml", ".xml.gz")):
        d = read_edgedata(path, attr)
    else:
        d = {}
        with open(path) as f:
            for line in f:
                parts = [p.strip() for p in re.split(r"[,;\t]", line.strip()) if p.strip()]
                if len(parts) >= 2:
                    try:
                        d[parts[0]] = float(parts[1])
                    except ValueError:
                        continue          # header row
    if edges is None:
        edges = sorted(d)
    return edges, np.array([d.get(e, 0.0) for e in edges], float)


# ------------------------------------------------------------------ pipeline
def route_matrix(net, taz, od_file, out_prefix, workdir, seed="7",
                 random_factor="1.4", extra_od2trips=(), extra_duarouter=()):
    """od2trips + duarouter. `random_factor` > 1 spreads each OD pair over several
    routes, which is what makes the assignment-proportion matrix non-degenerate."""
    os.makedirs(workdir, exist_ok=True)
    trips = os.path.join(workdir, out_prefix + ".trips.xml")
    rou = os.path.join(workdir, out_prefix + ".rou.xml")
    run([sumo_bin("od2trips"), "-n", taz, "-d", od_file, "-o", trips,
         "--seed", str(seed), "--no-step-log", *extra_od2trips])
    run([sumo_bin("duarouter"), "-n", net, "-r", trips, "-o", rou,
         "--weights.random-factor", str(random_factor), "--seed", str(seed),
         "--ignore-errors", "--no-step-log", "--routing-threads", "4", *extra_duarouter])
    return trips, rou


def simulate(net, rou, add_file, workdir, prefix, begin, end, seed="101"):
    """Run sumo. Returns output paths + run statistics.

    GOTCHA: SUMO resolves the `file=` attribute inside an additional file relative
    to that additional file's OWN directory, not the process cwd. The master
    additional file is copied into the run directory so outputs land there and every
    run provably uses byte-identical detector definitions.
    """
    d = os.path.join(workdir, prefix + "_sim")
    os.makedirs(d, exist_ok=True)
    add = os.path.join(d, os.path.basename(add_file))
    shutil.copyfile(add_file, add)
    tri = os.path.join(d, "tripinfo.out.xml")
    r = run([sumo_bin("sumo"), "-n", net, "-r", rou, "-a", add,
             "--begin", str(begin), "--end", str(end), "--tripinfo-output", tri,
             "--seed", str(seed), "--no-step-log", "--duration-log.statistics",
             "--xml-validation", "never", "--time-to-teleport", "300"], cwd=d)
    log = r.stdout + r.stderr

    def grab(pat, cast=float, default=0):
        m = re.search(pat, log)
        return cast(m.group(1)) if m else default

    n_fin = sum(1 for _, el in ET.iterparse(tri, events=("end",)) if el.tag == "tripinfo")
    return dict(dir=d, tripinfo=tri, log=log, finished=n_fin,
                inserted=grab(r"Inserted:\s+(\d+)", int),
                teleports=grab(r"Teleports:\s+(\d+)", int),
                collisions=grab(r"Collisions:\s+(\d+)", int),
                mean_speed=grab(r"Speed:\s+([\d.]+)"),
                time_loss=grab(r"TimeLoss:\s+([\d.]+)"),
                depart_delay=grab(r"DepartDelay:\s+([\d.]+)"))


def counts_from_routes(rou_file, edges):
    """Link traversal counts implied by a routed .rou.xml (assignment, no dynamics)."""
    idx = {e: i for i, e in enumerate(edges)}
    v = np.zeros(len(edges))
    for _, veh in ET.iterparse(rou_file, events=("end",)):
        if veh.tag != "vehicle":
            continue
        for e in veh.find("route").get("edges").split():
            if e in idx:
                v[idx[e]] += 1
        veh.clear()
    return v


# ------------------------------------------------------------------ metrics
def geh(m, c):
    m, c = np.asarray(m, float), np.asarray(c, float)
    den = (m + c) / 2.0
    out = np.zeros_like(den)
    nz = den > 0
    out[nz] = np.sqrt((m[nz] - c[nz]) ** 2 / den[nz])
    return out


def rmsn(m, c):
    """%RMSN = sqrt(N * sum((m-c)^2)) / sum(c) * 100."""
    m, c = np.asarray(m, float), np.asarray(c, float)
    s = c.sum()
    return float("nan") if s <= 0 else 100.0 * np.sqrt(len(c) * np.sum((m - c) ** 2)) / s


def count_fit(model, obs):
    g = geh(model, obs)
    return dict(rmsn_pct=round(rmsn(model, obs), 3), geh_mean=round(float(g.mean()), 3),
                geh_max=round(float(g.max()), 3),
                geh_lt5_pct=round(100.0 * float((g < 5).mean()), 1), n_links=len(obs))


def marginals(pairs, vals):
    zones = sorted({z for p in pairs for z in p})
    zi = {z: i for i, z in enumerate(zones)}
    rows, cols = np.zeros(len(zones)), np.zeros(len(zones))
    for (o, d), v in zip(pairs, vals):
        rows[zi[o]] += v
        cols[zi[d]] += v
    return zones, rows, cols


def od_recovery(pairs, est, truth):
    """OD-space accuracy. Only computable when a ground-truth matrix exists."""
    est, truth = np.asarray(est, float), np.asarray(truth, float)
    T = truth.sum()
    _, r_e, c_e = marginals(pairs, est)
    _, r_t, c_t = marginals(pairs, truth)
    den = np.sqrt(np.sum((truth - truth.mean()) ** 2) * np.sum((est - est.mean()) ** 2))
    corr = float(np.sum((truth - truth.mean()) * (est - est.mean())) / den) if den > 0 else float("nan")
    return dict(cell_rmsn_pct=round(rmsn(est, truth), 3),
                cell_mae=round(float(np.abs(est - truth).mean()), 3),
                cell_corr=round(corr, 4),
                total_demand_err_pct=round(100.0 * (est.sum() - T) / T, 3),
                row_marginal_mape_pct=round(float(100 * np.mean(np.abs(r_e - r_t) / np.maximum(r_t, 1e-9))), 3),
                col_marginal_mape_pct=round(float(100 * np.mean(np.abs(c_e - c_t) / np.maximum(c_t, 1e-9))), 3),
                share_misallocated_pct=round(float(100.0 * np.abs(est - truth).sum() / (2 * T)), 3))
