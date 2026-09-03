#!/usr/bin/env python3
"""
Surrogate-safety analysis for H4 (`analyze-intersection-safety-with-ssm`), with
the collinear-opposing-left-turn artifact exclusion from
`compare-unsignalized-intersection-control-types`.

Encounter-type codes: 2,3,18 following / rear-end ; 6,7,8,19 merging ;
10-17 crossing / angle ; 111 an actual simulated collision.

The 111 flags between two OPPOSING LEFT movements (N-left vs S-left, E-left vs
W-left) whose paths are collinear in this geometry, with TTC/PET = 0 or NA, are a
known SUMO SSM degenerate computation, not a real near-miss.  They are counted
and reported separately, never mixed into the safety comparison.  This study
checks explicitly whether its own runs hit that artifact.
"""
import json
import os
import statistics as st
import sys
import xml.etree.ElementTree as ET

FOLLOW = {2, 3, 18}
MERGE = {6, 7, 8, 19}
CROSS = set(range(10, 18))
COLLISION = {111}
OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}


def fval(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def analyze(path, meta):
    if not os.path.exists(path):
        return None
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None
    out = {"n_conflicts": 0, "following": 0, "merging": 0, "crossing": 0,
           "flag111": 0, "flag111_opposing_left_artifact": 0,
           "flag111_other": 0, "ttc_lt_1_5": 0, "ttc_lt_1_0": 0,
           "pet_lt_1_0": 0, "min_ttc": None, "min_pet": None,
           "max_drac": None, "ttc_values": [], "artifact_examples": [],
           "crossing_ttc_lt_1_5": 0, "pairs111": {}}
    ttcs, pets, dracs = [], [], []
    for c in root.findall("conflict"):
        out["n_conflicts"] += 1
        ego, foe = c.get("ego"), c.get("foe")
        types = set()
        ttc = pet = drac = None
        for e in c:
            t = e.get("type")
            if t is not None:
                try:
                    types.add(int(t))
                except ValueError:
                    pass
            v = fval(e.get("value"))
            if e.tag == "minTTC":
                ttc = v
            elif e.tag == "PET":
                pet = v
            elif e.tag == "maxDRAC":
                drac = v
        cat = None
        if types & COLLISION:
            cat = "111"
        elif types & CROSS:
            cat = "crossing"
        elif types & MERGE:
            cat = "merging"
        elif types & FOLLOW:
            cat = "following"
        if cat == "111":
            out["flag111"] += 1
            me, mf = meta.get(ego), meta.get(foe)
            key = "?"
            if me and mf:
                key = "%s%s-%s%s" % (me["arm"], me["mv"], mf["arm"], mf["mv"])
                out["pairs111"][key] = out["pairs111"].get(key, 0) + 1
            degenerate = (ttc is None or ttc <= 0.01) and (pet is None or pet <= 0.01)
            opp_left = (me and mf and me["mv"] == "l" and mf["mv"] == "l"
                        and OPP.get(me["arm"]) == mf["arm"])
            if opp_left and degenerate:
                out["flag111_opposing_left_artifact"] += 1
                if len(out["artifact_examples"]) < 5:
                    out["artifact_examples"].append(
                        {"ego": ego, "foe": foe, "pair": key, "TTC": ttc, "PET": pet})
            else:
                out["flag111_other"] += 1
        elif cat:
            out[cat] += 1
        if ttc is not None and ttc >= 0:
            ttcs.append(ttc)
            if ttc < 1.5:
                out["ttc_lt_1_5"] += 1
                if cat == "crossing":
                    out["crossing_ttc_lt_1_5"] += 1
            if ttc < 1.0:
                out["ttc_lt_1_0"] += 1
        if pet is not None and pet >= 0:
            pets.append(pet)
            if pet < 1.0:
                out["pet_lt_1_0"] += 1
        if drac is not None:
            dracs.append(drac)
    if ttcs:
        s = sorted(ttcs)
        out["min_ttc"] = s[0]
        out["ttc_p05"] = s[int(0.05 * (len(s) - 1))]
        out["ttc_median"] = st.median(s)
        out["n_ttc"] = len(s)
    if pets:
        out["min_pet"] = min(pets)
    if dracs:
        out["max_drac"] = max(dracs)
    out.pop("ttc_values")
    return out


if __name__ == "__main__":
    d, mp = sys.argv[1], sys.argv[2]
    print(json.dumps(analyze(os.path.join(d, "ssm.xml"), json.load(open(mp))), indent=1))
