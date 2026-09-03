#!/usr/bin/env python3
"""
Spatial diagnostics for the system-interchange comparison:

  (a) TIME-SPACE maps of speed and occupancy along the EB-A carriageway, from the E1
      detector chain -- shows WHERE the failure originates and how it propagates.
  (b) LANE-CHANGE spatial concentration along EB-A, from --lanechange-output.
      Lane-change records carry (edge, pos), NOT an absolute coordinate, so each record
      is mapped onto an absolute station by walking the compiled lane polyline -- the
      binning gotcha documented in `model-freeway-weaving-segment`.
"""
import gzip
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
EPISODE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
NETDIR = os.path.join(EPISODE, "outputs", "networks")
RUNDIR = os.path.join(EPISODE, "outputs", "runs")
FIG = os.path.join(EPISODE, "outputs", "figures")
TAB = os.path.join(EPISODE, "outputs", "tables")
VARIANTS = ["clover", "cd", "flyover"]
LABEL = {"clover": "Full cloverleaf",
         "cd": "Cloverleaf + C-D roads",
         "flyover": "Par-clo + directional flyover"}
AXIS = {"EB": (0, 1), "WB": (0, -1), "NB": (1, 1), "SB": (1, -1)}


def open_xml(path):
    """Bulk SUMO outputs in this episode are stored gzipped to keep the episodic record
    small; accept either form transparently."""
    if os.path.exists(path):
        return path
    if os.path.exists(path + ".gz"):
        return gzip.open(path + ".gz", "rb")
    return None


def lane_station_map(variant):
    """lane id -> (carriageway, function pos->station).  Covers mainline lanes and the
    C-D lanes (which run parallel to their mainline and so share its station axis)."""
    root = ET.parse(os.path.join(NETDIR, variant, "%s.net.xml" % variant)).getroot()
    out = {}
    for e in root.iter("edge"):
        if e.get("function") == "internal":
            continue
        eid = e.get("id")
        cw = None
        for c in AXIS:
            if eid.startswith(c + "_") or eid.startswith("CD" + c + "_"):
                cw = c
                break
        if cw is None:
            continue
        axis, sign = AXIS[cw]
        for l in e.findall("lane"):
            pts = [tuple(float(v) for v in p.split(",")) for p in l.get("shape").split()]
            cum, acc = [0.0], 0.0
            for i in range(len(pts) - 1):
                acc += math.dist(pts[i][:2], pts[i + 1][:2])
                cum.append(acc)

            def f(pos, pts=pts, cum=cum, axis=axis, sign=sign):
                for i in range(len(cum) - 1):
                    if cum[i] <= pos <= cum[i + 1]:
                        seg = cum[i + 1] - cum[i]
                        t = 0.0 if seg <= 0 else (pos - cum[i]) / seg
                        return sign * (pts[i][axis] + t * (pts[i + 1][axis] - pts[i][axis]))
                return sign * pts[-1][axis]
            out[l.get("id")] = (cw, f, eid)
    return out


# ------------------------------------------------------------------ (a) time-space
def timespace(variant, scale, seed, cw="EB"):
    rd = os.path.join(RUNDIR, variant, "base_s%.2f_seed%d" % (scale, seed))
    f = open_xml(os.path.join(rd, "det_e1.xml"))
    if f is None:
        return None
    cell = defaultdict(lambda: dict(n=0.0, inv=0.0, occ=0.0, k=0))
    for iv in ET.parse(f).getroot().iter("interval"):
        did = iv.get("id")
        if not did.startswith("e1_" + cw + "_"):
            continue
        _, _, pos, _lane = did.split("_")
        t = float(iv.get("begin"))
        c = cell[(int(pos), t)]
        n = float(iv.get("nVehContrib"))
        v = float(iv.get("harmonicMeanSpeed"))
        c["n"] += n
        if v > 0:
            c["inv"] += n / v
        c["occ"] += float(iv.get("occupancy"))
        c["k"] += 1
    stations = sorted({k[0] for k in cell})
    times = sorted({k[1] for k in cell})
    spd = [[None] * len(times) for _ in stations]
    occ = [[None] * len(times) for _ in stations]
    for i, s in enumerate(stations):
        for j, t in enumerate(times):
            c = cell.get((s, t))
            # leave the cell EMPTY (NaN) when no vehicle passed, rather than plotting a
            # speed of 0: the drain-out period after the flows stop would otherwise read
            # as a solid jam across the whole corridor.
            if not c or c["k"] == 0 or c["n"] == 0 or c["inv"] <= 0:
                continue
            spd[i][j] = c["n"] / c["inv"]
            occ[i][j] = c["occ"] / c["k"]
    return dict(stations=stations, times=times, speed=spd, occ=occ)


# ------------------------------------------------------------------ (b) lane changes
def lanechange_profile(variant, scale, seed, cw="EB", binw=50.0):
    """Lane changes along carriageway `cw`, binned by absolute station and SPLIT BY
    ROADWAY.  The split matters: the whole claim of the C-D design is that the weaving
    lane changes still happen, but on the collector-distributor rather than on the
    mainline, so a single combined profile would hide exactly the effect under test."""
    rd = os.path.join(RUNDIR, variant, "base_s%.2f_seed%d" % (scale, seed))
    f = open_xml(os.path.join(rd, "lanechanges.xml"))
    if f is None:
        return None
    lmap = lane_station_map(variant)
    bins = {"mainline": defaultdict(int), "cd": defaultdict(int)}
    total = {"mainline": 0, "cd": 0}
    for ch in ET.parse(f).getroot().iter("change"):
        rec = lmap.get(ch.get("from"))
        if rec is None or rec[0] != cw:
            continue
        road = "cd" if rec[2].startswith("CD") else "mainline"
        stn = rec[1](float(ch.get("pos")))
        bins[road][math.floor(stn / binw) * binw] += 1
        total[road] += 1
    return dict(bins={k: dict(sorted(v.items())) for k, v in bins.items()},
                total=total, binw=binw)


def main():
    scale = float(sys.argv[1]) if len(sys.argv) > 1 else 1.10
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 11
    os.makedirs(FIG, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize

    ts = {v: timespace(v, scale, seed) for v in VARIANTS}
    ts = {k: v for k, v in ts.items() if v}
    if ts:
        fig, axes = plt.subplots(2, len(ts), figsize=(5.2 * len(ts), 8.4), squeeze=False)
        for j, (v, d) in enumerate(ts.items()):
            for row, (key, cmap, lab, vmin, vmax) in enumerate(
                    [("speed", "RdYlGn", "space-mean speed (m/s)", 0, 34),
                     ("occ", "inferno_r", "occupancy (%)", 0, 60)]):
                M = [[(x if x is not None else float("nan")) for x in r] for r in d[key]]
                ax = axes[row][j]
                im = ax.imshow(M, aspect="auto", origin="lower", cmap=cmap,
                               norm=Normalize(vmin, vmax),
                               extent=[d["times"][0], d["times"][-1],
                                       d["stations"][0], d["stations"][-1]])
                for s, c, t in [(-440, "c", "outer off"), (-77, "w", "loop on"),
                                (77, "w", "loop off"), (440, "c", "outer on")]:
                    ax.axhline(s, color=c, lw=0.8, ls="--", alpha=.8)
                ax.axvline(600, color="k", lw=0.8)
                ax.axvline(2400, color="k", lw=0.8)
                ax.set_title("%s\n%s" % (LABEL[v], lab), fontsize=9)
                ax.set_xlabel("simulation time (s)")
                if j == 0:
                    ax.set_ylabel("station along EB-A (m from crossing)")
                fig.colorbar(im, ax=ax, fraction=.046)
        fig.suptitle("EB-A time-space maps at demand scale %.2f (seed %d).  "
                     "Dashed lines = ramp gores; vertical lines = measurement window."
                     % (scale, seed), fontsize=10)
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        p = os.path.join(FIG, "timespace_EB_scale%.2f.png" % scale)
        fig.savefig(p, dpi=130)
        print("wrote", p)

    lc = {v: lanechange_profile(v, scale, seed) for v in VARIANTS}
    lc = {k: v for k, v in lc.items() if v}
    if lc:
        fig, ax = plt.subplots(figsize=(11, 4.6))
        colors = {"clover": "#c0392b", "cd": "#2980b9", "flyover": "#27ae60"}
        stats = {}
        for v, d in lc.items():
            stats[v] = {}
            for road, lsty in (("mainline", "-"), ("cd", ":")):
                b = d["bins"][road]
                if not b:
                    continue
                xs = sorted(b)
                ax.plot(xs, [b[x] for x in xs], lsty, color=colors[v], lw=1.4,
                        label="%s - %s (n=%d)" % (LABEL[v], road, d["total"][road]))
                inzone = sum(c for s, c in b.items() if -100 <= s < 100)
                outzone = d["total"][road] - inzone
                stats[v][road] = dict(
                    total=d["total"][road], in_weave_zone=inzone,
                    per_100m_in_zone=round(inzone / 2.0, 1),
                    per_100m_elsewhere=round(outzone / ((6400 - 200) / 100.0), 1))
                stats[v][road]["concentration_ratio"] = round(
                    stats[v][road]["per_100m_in_zone"]
                    / max(stats[v][road]["per_100m_elsewhere"], 1e-9), 2)
        for s, t in [(-440, "outer off"), (-77, "loop on"), (77, "loop off"), (440, "outer on")]:
            ax.axvline(s, color="grey", ls="--", lw=.8)
        ax.set_xlim(-1500, 1500)
        ax.set_xlabel("station along EB-A (m from crossing)")
        ax.set_ylabel("lane changes per %.0f m bin" % lc[list(lc)[0]]["binw"])
        ax.set_title("Lane-change spatial concentration on EB-A, demand scale %.2f" % scale)
        ax.legend(fontsize=8); ax.grid(alpha=.3)
        fig.tight_layout()
        p = os.path.join(FIG, "lanechange_profile_scale%.2f.png" % scale)
        fig.savefig(p, dpi=130)
        with open(os.path.join(TAB, "lanechange_concentration_scale%.2f.json" % scale), "w") as fh:
            json.dump(stats, fh, indent=1)
        print("wrote", p)
        print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
