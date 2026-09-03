#!/usr/bin/env python3
"""
04_verify_crn_and_teleports.py

(1) CRN VERIFICATION -- the prerequisite for the whole study.  Every sensing arm
    must have byte-identical underlying traffic, so that all differences are
    attributable to OBSERVATION, not traffic stochasticity.  We test this the
    hard way: SHA1 of each arm's tripinfo.xml (which records every vehicle's
    depart/arrival/route/timeLoss) after stripping only the <tripinfos> header
    line (which contains the invoking command line and therefore always differs).

(2) TELEPORT-ARTIFACT CHECK -- per skill
    `validate-congested-scenario-results-against-teleport-artifacts`:
      * teleport count read as the LAST cumulative value of summary's `teleports`
        (never summed),
      * a --time-to-teleport sweep {-1,120,300,600} as a treatment variable,
      * a running-vehicle-count freeze check on the ttt=-1 arm (survivorship
        censoring detector).

(3) COMPLETED-vs-RUNNING accounting for ground truth.
"""
import glob
import hashlib
import json
import os
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.abspath(os.path.join(HERE, "..", "..", "runs"))
RES = os.path.abspath(os.path.join(HERE, "..", "results"))
os.makedirs(RES, exist_ok=True)


# CRITICAL: tripinfo's `devices` attribute records WHICH DEVICES were attached to
# each vehicle -- including the fcd device.  It therefore differs between probe
# arms BY CONSTRUCTION, with no difference in the traffic whatsoever.  Hashing it
# produces a FALSE CRN FAILURE (verified: with `devices` included, all 8
# penetration levels hash differently; with it excluded, they are byte-identical
# and every per-vehicle duration difference is exactly 0.0 s).
CRN_EXCLUDE_ATTRS = {"devices"}


def tripinfo_hash(path, exclude=CRN_EXCLUDE_ATTRS):
    """SHA1 over the canonicalised per-vehicle records, excluding observation-layer
    bookkeeping attributes (see CRN_EXCLUDE_ATTRS)."""
    h = hashlib.sha1()
    n = 0
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "tripinfo":
            key = "|".join(f"{k}={el.get(k)}" for k in sorted(el.keys()) if k not in exclude)
            h.update(key.encode())
            n += 1
            el.clear()
    return h.hexdigest(), n


def summary_last(path):
    last = None
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            last = dict(el.attrib)
            el.clear()
    return last


def summary_series(path):
    t, run, halt, arr = [], [], [], []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "step":
            t.append(float(el.get("time")))
            run.append(int(el.get("running")))
            halt.append(int(el.get("halting")))
            arr.append(int(el.get("ended", el.get("arrived", 0))))
            el.clear()
    return t, run, halt, arr


def main():
    out = {}

    # ---------------------------------------------------------------- (1) CRN
    arms = sorted(glob.glob(os.path.join(RUNS, "p*_T*")))
    arms = [os.path.basename(a) for a in arms]
    ref = "master"
    ref_hash, ref_n = tripinfo_hash(os.path.join(RUNS, ref, "tripinfo.xml"))
    crn = {ref: dict(hash=ref_hash, n=ref_n, matches_master=True)}
    for a in arms + ["pilot", "ttt300"]:
        p = os.path.join(RUNS, a, "tripinfo.xml")
        if not os.path.exists(p):
            continue
        hh, nn = tripinfo_hash(p)
        crn[a] = dict(hash=hh, n=nn, matches_master=(hh == ref_hash and nn == ref_n))
    out["crn"] = crn
    n_match = sum(1 for v in crn.values() if v["matches_master"])
    print(f"CRN: {n_match}/{len(crn)} runs byte-identical to master tripinfo "
          f"(hash {ref_hash[:12]}, n={ref_n})")
    for k, v in sorted(crn.items()):
        if not v["matches_master"]:
            print(f"   MISMATCH: {k} hash={v['hash'][:12]} n={v['n']}")

    # ------------------------------------------------------- (2) teleports
    tel = {}
    for name in ["master", "ttt-1", "ttt120", "ttt300", "ttt600"]:
        sp = os.path.join(RUNS, name, "summary.xml")
        if not os.path.exists(sp):
            continue
        last = summary_last(sp)
        t, run, halt, arr = summary_series(sp)
        # frozen-tail detection: running count constant AND no arrivals for the tail
        tail = 600
        idx = [i for i, x in enumerate(t) if x >= t[-1] - tail]
        frozen = (len(set(run[i] for i in idx)) == 1) and (arr[idx[0]] == arr[idx[-1]])
        hh, nn = tripinfo_hash(os.path.join(RUNS, name, "tripinfo.xml"))
        tel[name] = dict(teleports_last_cumulative=int(last["teleports"]),
                         inserted=int(last["inserted"]),
                         running_at_end=int(last["running"]),
                         ended=int(last.get("ended", -1)),
                         max_running=max(run), max_halting=max(halt),
                         frozen_tail=bool(frozen),
                         tripinfo_hash=hh, tripinfo_n=nn)
        print(f"  {name:8s} teleports={tel[name]['teleports_last_cumulative']:4d} "
              f"inserted={tel[name]['inserted']} running_end={tel[name]['running_at_end']} "
              f"max_running={tel[name]['max_running']} frozen_tail={frozen}")
    out["teleport_sweep"] = tel

    # ------------------------------------- (3) completed vs running accounting
    tp = os.path.join(RUNS, "master", "tripinfo.xml")
    comp, unfin = 0, 0
    dur_c, dur_u = [], []
    eb_c, eb_u = 0, 0
    for _, el in ET.iterparse(tp, events=("end",)):
        if el.tag != "tripinfo":
            continue
        vid = el.get("id")
        arr = float(el.get("arrival"))
        d = float(el.get("duration"))
        if arr < 0:
            unfin += 1
            dur_u.append(d)
            if vid.startswith("f_eb"):
                eb_u += 1
        else:
            comp += 1
            dur_c.append(d)
            if vid.startswith("f_eb"):
                eb_c += 1
        el.clear()
    out["accounting"] = dict(
        completed=comp, unfinished=unfin,
        unfinished_share=unfin / (comp + unfin),
        eb_completed=eb_c, eb_unfinished=eb_u,
        mean_duration_completed=sum(dur_c) / len(dur_c),
        mean_duration_unfinished=(sum(dur_u) / len(dur_u)) if dur_u else None,
    )
    print(f"  accounting: completed={comp} unfinished={unfin} "
          f"({100*unfin/(comp+unfin):.2f}%)  EB completed={eb_c} unfinished={eb_u}")

    json.dump(out, open(os.path.join(RES, "crn_and_teleport_verification.json"), "w"), indent=1)
    print("wrote", os.path.join(RES, "crn_and_teleport_verification.json"))


if __name__ == "__main__":
    main()
