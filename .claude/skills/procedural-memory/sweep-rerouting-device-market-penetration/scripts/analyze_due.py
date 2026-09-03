#!/usr/bin/env python3
"""Analyze the duaIterate dynamic-user-equilibrium reference for the disrupted case.

Reports, per iteration: the route split, and mean travel time per USED route on
two different cost definitions --

  1. in-network duration              -- the cost duaIterate's edge-weight router
                                         actually sees and optimizes against
  2. duration + departDelay           -- what a traveler really experiences,
                                         including time queued at the origin
                                         waiting to be inserted

These can disagree: the edge-weight router cannot see origin-insertion queueing,
so an equilibrium can satisfy Wardrop on in-network time while still leaving a
gap in total experienced time. Checking only the first overstates convergence.

IMPORTANT -- Wardrop must be checked PER DEPARTURE INTERVAL, not aggregated.
This scenario is time-varying: the incident only exists between 900 and 2400 s,
so vehicles departing outside that window correctly all use the main route while
those departing inside it split. Pooling every vehicle into one main-vs-alt
comparison mixes those regimes and reports a large spurious cost gap even at a
perfectly good equilibrium. The per-bin table below is the valid test; the
pooled row is printed only to show how misleading it is.
"""
import argparse
import glob
import gzip
import os
import statistics
import xml.etree.ElementTree as ET


def open_maybe_gz(p):
    return gzip.open(p, "rb") if p.endswith(".gz") else open(p, "rb")


def route_map(routefile):
    """vehicle id -> 'alt' | 'main', from the iteration's chosen-route file."""
    out = {}
    with open_maybe_gz(routefile) as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag == "vehicle":
                r = el.find("route")
                if r is not None:
                    e = " " + r.get("edges") + " "
                    out[el.get("id")] = "alt" if " AP " in e else "main"
                el.clear()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dua-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    iters = sorted(d for d in glob.glob(os.path.join(a.dua_dir, "[0-9][0-9][0-9]")) if os.path.isdir(d))
    lines = ["DYNAMIC USER EQUILIBRIUM REFERENCE (duaIterate, Gawron, incident active)",
             "demand 2500 veh/h, incident = one lane of CB closed 900-2400 s", ""]
    lines.append("iter  n_veh  alt_share |  in-network duration [s]      | total experienced (dur+departDelay) [s]")
    lines.append("                       |  main     alt      gap        | main     alt      gap")
    last = None
    for d in iters:
        it = os.path.basename(d)
        rf = os.path.join(d, "demand_%s.rou.xml.gz" % it)
        tf = os.path.join(d, "tripinfo_%s.xml" % it)
        if not (os.path.exists(rf) and os.path.exists(tf)):
            continue
        rm = route_map(rf)
        dur = {"main": [], "alt": []}
        tot = {"main": [], "alt": []}
        for ti in ET.parse(tf).getroot().findall("tripinfo"):
            r = rm.get(ti.get("id"))
            if r is None:
                continue
            dd = float(ti.get("duration"))
            dur[r].append(dd)
            tot[r].append(dd + float(ti.get("departDelay")))
        n = len(dur["main"]) + len(dur["alt"])
        if n == 0:
            continue
        share = len(dur["alt"]) / n
        f = lambda x: statistics.mean(x) if x else float("nan")
        gap_in = f(dur["alt"]) - f(dur["main"])
        gap_to = f(tot["alt"]) - f(tot["main"])
        lines.append("%s  %5d   %6.3f  | %7.1f %7.1f %+7.1f    | %7.1f %7.1f %+7.1f"
                     % (it, n, share, f(dur["main"]), f(dur["alt"]), gap_in,
                        f(tot["main"]), f(tot["alt"]), gap_to))
        last = (it, n, share, f(dur["main"]), f(dur["alt"]), gap_in,
                f(tot["main"]), f(tot["alt"]), gap_to, f(tot["main"] + tot["alt"]))
    lines.append("")
    if last:
        it, n, share, dm, da, gi, tm, ta, gt, overall = last
        rel_in = abs(gi) / ((dm + da) / 2) * 100
        rel_to = abs(gt) / ((tm + ta) / 2) * 100
        lines.append("FINAL ITERATION %s" % it)
        lines.append("  equilibrium alternate share      : %.1f%%" % (100 * share))
        lines.append("  network-wide mean total exp. time: %.1f s" % overall)
        lines.append("  POOLED (invalid) Wardrop check, in-network: %.1f s gap (%.1f%%)" % (gi, rel_in))
        lines.append("  POOLED (invalid) Wardrop check, total exp.: %.1f s gap (%.1f%%)" % (gt, rel_to))
        lines.append("  ^ pooled across all departure times, so it mixes the incident and")
        lines.append("    non-incident regimes; see the per-departure-bin table below instead.")

        # ---- valid, per-departure-interval Wardrop check on the final iteration ----
        d = os.path.join(a.dua_dir, it)
        rm = route_map(os.path.join(d, "demand_%s.rou.xml.gz" % it))
        bins = {}
        for ti in ET.parse(os.path.join(d, "tripinfo_%s.xml" % it)).getroot().findall("tripinfo"):
            r = rm.get(ti.get("id"))
            if r is None:
                continue
            b = int(float(ti.get("depart")) // 300) * 300
            dd = float(ti.get("duration"))
            tt = dd + float(ti.get("departDelay"))
            bins.setdefault(b, {"main": [[], []], "alt": [[], []]})
            bins[b][r][0].append(dd)
            bins[b][r][1].append(tt)
        lines.append("")
        lines.append("PER-DEPARTURE-INTERVAL WARDROP CHECK (final iteration, 300 s bins)")
        lines.append("  depart bin   n_main n_alt  alt%  | in-network: main   alt    gap    rel")
        worst = 0.0
        for b in sorted(bins):
            m, al = bins[b]["main"], bins[b]["alt"]
            nm, na = len(m[0]), len(al[0])
            if nm + na == 0:
                continue
            sh = na / (nm + na)
            if nm == 0 or na == 0:
                lines.append("  %5d-%-5d %6d %5d %5.1f%% | only one route used -- Wardrop check "
                             "not applicable" % (b, b + 300, nm, na, 100 * sh))
                continue
            mm, ma = statistics.mean(m[0]), statistics.mean(al[0])
            gap = ma - mm
            rel = abs(gap) / ((mm + ma) / 2) * 100
            worst = max(worst, rel)
            lines.append("  %5d-%-5d %6d %5d %5.1f%% | %8.1f %7.1f %+7.1f %5.1f%%"
                         % (b, b + 300, nm, na, 100 * sh, mm, ma, gap, rel))
        lines.append("")
        lines.append("  worst relative route-cost gap across bins where BOTH routes are used: %.1f%%"
                     % worst)
        lines.append("  -> Wardrop %s at the 5%% threshold on in-network cost."
                     % ("SATISFIED" if worst < 5 else "NOT satisfied"))
    txt = "\n".join(lines)
    print(txt)
    with open(a.out, "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
