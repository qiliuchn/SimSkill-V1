"""Report for the closure-representation question."""
import json
import os
from collections import defaultdict

import numpy as np

import wz_common as W
import stats_util as S

D = os.path.join(W.OUT, "representation")
res = json.load(open(os.path.join(D, "representation_results.json")))
runs, live = res["runs"], res.get("live_check", {})
g = defaultdict(list)
for r in runs:
    g[r["rep"]].append(r)
seeds = sorted({r["seed"] for r in runs})
ORDER = ["R1_rerouter", "R2_permission", "R3a_geom_prio", "R3b_geom_zip"]
NAME = {"R1_rerouter": "R1 rerouter closingLaneReroute",
        "R2_permission": "R2 disallow on the compiled net's lane",
        "R3a_geom_prio": "R3a rebuilt net, geometric lane drop, priority merge",
        "R3b_geom_zip": "R3b rebuilt net, geometric lane drop, zipper merge"}

L = ["# The representation question: three ways to close a lane", "",
     "Same closure (rightmost lane of the 1500 m activity area), same demand",
     "(3600 veh/h peak), same CRN seeds, dt 0.5 s / ballistic / actionStepLength 1.0 s.",
     "", "## 1. What each representation actually is, verified from the COMPILED net", "",
     "| representation | fD lanes | fE lanes | fE lane permissions in the .net.xml | fD->fE connection states |",
     "|---|---:|---:|---|---|"]
for rep in ORDER:
    if rep not in g:
        continue
    v = g[rep][0]["verify"]
    perms = {k: (val or "-") for k, val in v["fE_lane_disallow"].items()}
    L.append(f"| {NAME[rep]} | {v['fD_nlanes']} | {v['fE_nlanes']} | "
             f"{', '.join(f'{k}: {val}' for k, val in perms.items())} | "
             f"{', '.join(f'{a}->{b}:{s}' for a, b, s in v['fD_to_fE_states'])} |")

L += ["", "### The single most important verification result", "",
      "A `closingLaneReroute` is INVISIBLE in the compiled network -- the lane still has",
      "three lanes and no `disallow` attribute. Querying it live over TraCI instead:", "",
      "```json", json.dumps(live, indent=1), "```", ""]
if live:
    fe0 = live.get("fE_0", {})
    fe1 = live.get("fE_1", {})
    if isinstance(fe0, dict) and "passenger_blocked" in fe0:
        L.append(f"During the closure interval, `fE_0` has passenger vehicles blocked "
                 f"({fe0['disallowed_n']} vClasses disallowed) while `fE_1` does not "
                 f"({fe1.get('disallowed_n')} disallowed). **SUMO implements "
                 f"`closingLaneReroute` by mutating the lane's permissions at runtime "
                 f"-- it is the same mechanism as R2, applied dynamically rather than "
                 f"statically.**")

L += ["", "## 2. Measured behaviour", "",
      "| representation | WZ cap (pc/h/ln) 95% CI | mean dur (s) | mean depart delay (s) | hard brakes (near taper) | teleports | collisions | running-count freeze |",
      "|---|---|---:|---:|---:|---:|---:|---|"]
tab = {}
for rep in ORDER:
    rs = g.get(rep, [])
    if not rs:
        continue
    c = S.mean_ci([r["cap"] for r in rs])
    f = lambda m: float(np.nanmean([r.get(m, np.nan) for r in rs]))
    tab[rep] = dict(cap=c, dur=f("mean_duration"), dd=f("mean_departdelay"),
                    hb=f("hard_brakes"), hbt=f("hard_brakes_taper"),
                    tel=f("teleports"), coll=f("n_collisions"),
                    tstt=f("TSTT_vh"))
    t = tab[rep]
    L.append(f"| {NAME[rep]} | {c['mean']:.0f} [{c['lo']:.0f}, {c['hi']:.0f}] | "
             f"{t['dur']:.0f} | {t['dd']:.1f} | {t['hb']:.0f} ({t['hbt']:.0f}) | "
             f"{t['tel']:.1f} | {t['coll']:.1f} | "
             f"{any(r.get('freeze') for r in rs)} |")

L += ["", "### CRN-paired contrasts", "",
      "| contrast | d cap (pc/h/ln) | 95% CI | p | d mean duration (s) | p |",
      "|---|---:|---|---:|---:|---:|"]
def pr(a, b, m):
    ma = {r["seed"]: r.get(m, np.nan) for r in g.get(a, [])}
    mb = {r["seed"]: r.get(m, np.nan) for r in g.get(b, [])}
    xs = [s for s in seeds if s in ma and s in mb]
    return S.paired([ma[s] for s in xs], [mb[s] for s in xs])
for a, b in (("R1_rerouter", "R2_permission"), ("R2_permission", "R3a_geom_prio"),
             ("R3b_geom_zip", "R3a_geom_prio"), ("R1_rerouter", "R3a_geom_prio")):
    if a not in g or b not in g:
        continue
    dc, dd = pr(a, b, "cap"), pr(a, b, "mean_duration")
    L.append(f"| {a} - {b} | {dc['diff']:+.1f} | [{dc['lo']:+.1f}, {dc['hi']:+.1f}] | "
             f"{dc['p']:.4f} | {dd['diff']:+.1f} | {dd['p']:.4f} |")

L += ["", "## 3. Merge-position profile (where vehicles actually vacate the closing lane)",
      "", "Share of vehicles observed in the closing lane (lane 0) at each E2 station.",
      "In R3 the closing lane physically ends at the taper, so downstream stations have",
      "no lane 0 to report and the share is the share of the REMAINING lane 0.", "",
      "| distance (m) | " + " | ".join(NAME[r].split()[0] for r in ORDER if r in g) + " |",
      "|---:|" + "---:|" * len([r for r in ORDER if r in g])]
prof = {}
for rep in ORDER:
    if rep not in g:
        continue
    acc = defaultdict(list)
    for r in g[rep]:
        for p in r["merge_profile"]:
            acc[round(p["dist"] / 100) * 100].append(p["share_closing"])
    prof[rep] = {d: float(np.mean(v)) for d, v in acc.items()}
alld = sorted(set().union(*[set(p) for p in prof.values()])) if prof else []
for d in alld:
    if d > 7000:
        continue
    L.append(f"| {d} | " + " | ".join(
        f"{prof[r].get(d, float('nan')):.3f}" for r in ORDER if r in g) + " |")

json.dump(dict(table={k: dict(v, cap=v["cap"]) for k, v in tab.items()},
               profile={k: {str(d): s for d, s in v.items()} for k, v in prof.items()}),
          open(os.path.join(D, "representation_summary.json"), "w"), indent=1, default=str)
out = os.path.join(W.TABLES, "REPRESENTATION.md")
with open(out, "w") as f:
    f.write("\n".join(L) + "\n")
print("\n".join(L))
print("\nwrote", out)
