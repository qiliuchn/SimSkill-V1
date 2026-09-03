#!/usr/bin/env python3
"""
H3 access-design analysis: weaving friction near managed-lane gates.

Reads --lanechange-output and the SSM device log from a run directory and produces:
  * lane changes binned by ABSOLUTE corridor position (m), not edge identity
  * managed-lane ingress (lane 2 -> 3) and egress (3 -> 2) counts, and where they happen
  * a spatial concentration ratio (max 250 m-bin share of all ML-related changes)
  * SSM conflict counts (minTTC < 3 s, maxDRAC > 3 m/s2) normalised per 1000 equipped veh
"""
import csv
import gzip
import json
import os
import sys
import xml.etree.ElementTree as ET


def xopen(path):
    if os.path.exists(path):
        return open(path, "rb")
    return gzip.open(path + ".gz", "rb")


def xexists(path):
    return os.path.exists(path) or os.path.exists(path + ".gz")

sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402

BIN = 250.0
GATE_EDGES = {"m2", "m5", "m8", "m11"}


def edge_offsets(netfile):
    net = sumolib.net.readNet(netfile)
    off, x = {}, 0.0
    for i in range(1, 15):
        e = f"m{i}"
        off[e] = x
        x += net.getEdge(e).getLength()
    return off, x


def analyze_h3(rundir, netfile):
    off, corridor_len = edge_offsets(netfile)
    lc = os.path.join(rundir, "lanechanges.xml")
    bins, ml_bins = {}, {}
    n_total = n_ing = n_egr = 0
    reasons = {}
    for _, el in ET.iterparse(xopen(lc), events=("end",)):
        if el.tag != "change":
            el.clear()
            continue
        fr, to = el.get("from"), el.get("to")
        fe, fl = fr.rsplit("_", 1)
        te, tl = to.rsplit("_", 1)
        if fe in off:
            x = off[fe] + float(el.get("pos"))
            b = int(x // BIN)
            bins[b] = bins.get(b, 0) + 1
            n_total += 1
            reasons[el.get("reason")] = reasons.get(el.get("reason"), 0) + 1
            if int(tl) == 3 and int(fl) == 2:
                ml_bins[b] = ml_bins.get(b, 0) + 1
                n_ing += 1
            elif int(fl) == 3 and int(tl) == 2:
                ml_bins[b] = ml_bins.get(b, 0) + 1
                n_egr += 1
        el.clear()

    n_ml = n_ing + n_egr
    top = max(ml_bins.values()) if ml_bins else 0
    nb = max(1, int(corridor_len // BIN))
    conc = (top / n_ml) / (1.0 / nb) if n_ml else float("nan")   # x uniform

    # share of ML-related changes that occur inside a designated gate segment
    gate_spans = []
    for g in GATE_EDGES:
        gate_spans.append((off[g], off[g] + (off.get(f"m{int(g[1:])+1}", corridor_len) - off[g])))
    in_gate = 0
    for b, c in ml_bins.items():
        xc = (b + 0.5) * BIN
        if any(lo <= xc < hi for lo, hi in gate_spans):
            in_gate += c
    res = {
        "run": os.path.basename(rundir),
        "lc_total": n_total,
        "ml_ingress": n_ing,
        "ml_egress": n_egr,
        "ml_changes": n_ml,
        "ml_change_concentration_vs_uniform": conc,
        "ml_changes_in_gate_share": in_gate / n_ml if n_ml else float("nan"),
        "lc_reasons": reasons,
        "lc_bins_250m": {int(k): v for k, v in sorted(bins.items())},
        "ml_bins_250m": {int(k): v for k, v in sorted(ml_bins.items())},
    }

    # ---- SSM ---------------------------------------------------------------
    ssm = os.path.join(rundir, "ssm.xml")
    if xexists(ssm):
        egos = set()
        n_ttc = n_drac = n_pet = 0
        min_ttc_vals = []
        for _, el in ET.iterparse(xopen(ssm), events=("end",)):
            if el.tag == "conflict":
                egos.add(el.get("ego"))
                for sub in el:
                    v = sub.get("value")
                    if v in (None, "NA"):
                        continue
                    if sub.tag == "minTTC" and float(v) < 3.0:
                        n_ttc += 1
                        min_ttc_vals.append(float(v))
                    elif sub.tag == "maxDRAC" and float(v) > 3.0:
                        n_drac += 1
                    elif sub.tag == "PET" and float(v) < 2.0:
                        n_pet += 1
            elif el.tag == "globalMeasures":
                egos.add(el.get("ego"))
            if el.tag in ("conflict", "globalMeasures"):
                el.clear()
        res.update({
            "ssm_equipped": len(egos),
            "ssm_ttc_conflicts": n_ttc,
            "ssm_drac_conflicts": n_drac,
            "ssm_pet_conflicts": n_pet,
            "ssm_ttc_per_1000_equipped": 1000.0 * n_ttc / max(1, len(egos)),
            "ssm_drac_per_1000_equipped": 1000.0 * n_drac / max(1, len(egos)),
            "ssm_min_ttc_p05": sorted(min_ttc_vals)[int(0.05 * len(min_ttc_vals))] if min_ttc_vals else float("nan"),
        })
    return res


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--net", required=True)
    a = ap.parse_args()
    print(json.dumps(analyze_h3(a.rundir, a.net), indent=1, default=str))
