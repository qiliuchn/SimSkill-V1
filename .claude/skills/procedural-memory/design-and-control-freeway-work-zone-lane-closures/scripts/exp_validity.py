"""Validity layer, required throughout by this project's conventions.

(1) COMPILED-NET VERIFICATION of every geometry variant actually used -- lane counts,
    lengths, speeds, permissions, and the fD->fE connection states -- read back out of
    the compiled .net.xml, never from the source XML.

(2) TELEPORT-ARTIFACT CHECK per
    `validate-congested-scenario-results-against-teleport-artifacts`:
      - --time-to-teleport must exceed the longest legitimate wait (here the arterial
        red, 32 s) -- trivially satisfied at 300 s
      - sweep ttt in {120, 300, -1} on the most congested cells
      - at ttt=-1, check the running-vehicle count for a permanent FREEZE (the
        survivorship-censoring signature) before trusting any travel-time number
      - report the teleport-affected share against the 2 %-of-completed-trips threshold

(3) COMPLETED / STILL-RUNNING / NOT-INSERTED accounting for every cell.
"""
import json
import os
import glob

import numpy as np

import wz_common as W
import batch
import analyze

OUTD = os.path.join(W.OUT, "validity")
os.makedirs(OUTD, exist_ok=True)


def verify_all_nets():
    rows = []
    for nf in sorted(glob.glob(os.path.join(W.NETS, "*.net.xml"))):
        t = W.net_lane_table(nf)
        if "fE" not in t:
            continue
        conns = W.net_connections(nf, "fD", "fE")
        rows.append(dict(
            net=os.path.basename(nf),
            fC=(len(t["fC"]), round(t["fC"][0][1], 1), round(t["fC"][0][2], 2)),
            fD=(len(t["fD"]), round(t["fD"][0][1], 1), round(t["fD"][0][2], 2)),
            fE=(len(t["fE"]), round(t["fE"][0][1], 1), round(t["fE"][0][2], 2)),
            fF=(len(t["fF"]), round(t["fF"][0][1], 1), round(t["fF"][0][2], 2)),
            fE_disallow={ln[0]: ln[4] for ln in t["fE"] if ln[4]},
            fD_fE_states="".join(c["state"] for c in conns),
            n_conn=len(conns)))
    return rows


def teleport_sweep(peak=4400, seeds=(1, 2, 3), arms=("donothing", "late")):
    cs = []
    for ttt in (120, 300, -1):
        for arm in arms:
            for sd in seeds:
                cs.append(dict(label=f"tel_{arm}_ttt{ttt}_s{sd}", outroot=OUTD,
                               arm=arm, rep="geom",
                               merge=("zipper" if arm in ("late", "dynamic") else "priority"),
                               peak=peak, seed=sd, demand_seed=300 + sd, ttt=ttt,
                               params=dict(lanes_closed=1), tagname=f"{arm}_ttt{ttt}"))
    return batch.run_cells(cs, os.path.join(OUTD, "teleport_sweep.json"), nproc=6)


def teleport_report(rows):
    L = ["# Validity checks", "", "## Teleport-artifact sweep (peak 4400 veh/h, 1 lane closed)",
         "",
         "| arm | time-to-teleport | teleports | completed | still running | not inserted | teleport share of completed | mean dur (s) | TSTT (veh-h) | running-count FREEZE |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for arm in sorted({r["arm"] for r in rows if r.get("ok")}):
        for ttt in (120, 300, -1):
            rs = [r for r in rows if r.get("ok") and r["arm"] == arm and r["ttt"] == ttt]
            if not rs:
                continue
            f = lambda m: float(np.nanmean([r.get(m, np.nan) for r in rs]))
            ni = f("loaded") - f("inserted")
            share = 100.0 * f("teleports") / max(f("n"), 1)
            L.append(f"| {arm} | {ttt} | {f('teleports'):.1f} | {f('n'):.0f} | "
                     f"{f('running'):.1f} | {ni:.0f} | {share:.2f}% | "
                     f"{f('mean_duration'):.0f} | {f('TSTT_vh'):.1f} | "
                     f"{any(r.get('freeze') for r in rs)} |")
    return "\n".join(L)


if __name__ == "__main__":
    nets = verify_all_nets()
    L = ["# Compiled-net verification of every geometry variant", "",
         "Read back out of the compiled `.net.xml`, not the source XML.",
         "Tuples are (lanes, length m, speed m/s).", "",
         "| net | fC | fD (taper) | fE (activity area) | fF | fE disallow | fD->fE states |",
         "|---|---|---|---|---|---|---|"]
    for r in nets:
        L.append(f"| {r['net']} | {r['fC']} | {r['fD']} | {r['fE']} | {r['fF']} | "
                 f"{r['fE_disallow'] or '-'} | `{r['fD_fE_states']}` |")
    L += ["", "`Z` = zipper (cooperative alternating), `M` = major/right-of-way,",
          "`m` = minor (must yield).  A 3-lane -> 2-lane drop with a zipper node shows",
          "`ZZM`: the two lanes contesting the surviving lane both get `Z`, the",
          "uncontested lane keeps `M`.  With a priority node the same drop shows `MMM`",
          "on the full-geometry variants (3->3, nothing contested) and `mMM`/`MMM` on the",
          "geometric drop depending on netconvert's choice of which approach yields.", ""]
    print("\n".join(L[:40]))
    rows = teleport_sweep()
    L.append(teleport_report(rows))
    out = os.path.join(W.TABLES, "VALIDITY.md")
    with open(out, "w") as f:
        f.write("\n".join(L) + "\n")
    json.dump(dict(nets=nets), open(os.path.join(OUTD, "net_verification.json"), "w"),
              indent=1, default=str)
    print(teleport_report(rows))
    print("\nwrote", out)
