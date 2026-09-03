#!/usr/bin/env python3
"""H6 SPILLBACK COLLAPSE - coordination benefit dies when links fill.

Short blocks (L = 200 m and 300 m, so each arterial link has only ~180 m /
~280 m of storage) plus rising arterial demand. At each demand level the MAXBAND-coordinated plan and
the all-zero-offset uncoordinated plan are run under CRN, with an E2 lane-area
detector spanning every arterial link so queue length is observed directly
rather than inferred from delay.

Reported per level:
  * max / mean E2 jam length as a fraction of link storage, per direction
  * fraction of measurement intervals with jam length >= 90% of storage
  * the paired coordinated-minus-uncoordinated benefit in corridor-through time
    loss and in total network time loss, SIGNED, with CIs
  * full teleport and loaded/inserted/arrived/still-running accounting, since
    every one of those becomes a live validity threat at this demand
"""
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402
import expbase as B          # noqa: E402
import runner as R           # noqa: E402
import scenario as S         # noqa: E402

SPACINGS = [200.0, 300.0]
LEVELS = [700.0, 900.0, 1100.0, 1300.0, 1500.0, 1700.0, 1900.0, 2100.0]
CROSS = 300.0
SEEDS = [1, 2, 3, 4]


def e2_summary(path, link_len):
    """max/mean jam length and near-full share, split by direction."""
    agg = {"EB": [], "WB": []}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != "interval":
            el.clear()
            continue
        did = el.get("id", "")
        # id is e2_<edge>_<lane>; EB edges run W->J0->..->E
        try:
            jam = float(el.get("maxJamLengthInMeters", 0))
        except (TypeError, ValueError):
            jam = 0.0
        e = did[3:].rsplit("_", 1)[0]
        a, b = e.split("to")
        def xi(nid):
            return -1 if nid == "W" else (99 if nid == "E" else int(nid[1:]))
        d = "EB" if xi(b) > xi(a) else "WB"
        agg[d].append(jam)
        el.clear()
    out = {}
    for d, v in agg.items():
        if not v:
            out[d] = dict(max=0.0, mean=0.0, near_full=0.0)
            continue
        out[d] = dict(max=max(v), mean=sum(v) / len(v),
                      near_full=sum(1 for x in v if x >= 0.9 * link_len) / len(v))
    return out


def sim_one(thru=None, seed=None, offs=None, tag=None, L=None):
    sc = S.get(L=L, seed=seed, thru=thru, cross=CROSS, side=B.SIDE0)
    p = B.plan(offs=offs)
    d = os.path.join(B.WORK, "h6", "L%d_q%d_%s_s%d" % (L, thru, tag, seed))
    res = R.evaluate(sc, p, d, seed=seed, warm=B.WARM, fcd=True, e2=True)
    st, m = res["stats"], res["meas"]
    link_len = R.net_of(sc).getEdge("J0toJ1").getLength()
    e2 = e2_summary(os.path.join(d, "e2.out.xml"), link_len)
    return dict(thru=thru, seed=seed, tag=tag, L=L, link_len=link_len,
                jam_max_EB=e2["EB"]["max"], jam_mean_EB=e2["EB"]["mean"],
                nearfull_EB=e2["EB"]["near_full"],
                jam_max_WB=e2["WB"]["max"], jam_mean_WB=e2["WB"]["mean"],
                nearfull_WB=e2["WB"]["near_full"],
                zeroEB=m["EB"]["zero_frac"], zeroWB=m["WB"]["zero_frac"],
                tl_thruE=st["thruE"]["timeLoss"], tl_thruW=st["thruW"]["timeLoss"],
                tl_all=st["all"]["timeLoss"],
                total_tl=st["all"]["total_timeLoss"],
                n_all=st["all"]["n"],
                loaded=res["loaded"], inserted=res["inserted"],
                arrived=res["arrived"], running=res["still_running"],
                completed_share=res["completed_share"],
                teleports=res["n_teleport_events"], tele_share=st["all"]["tele"])


def main():
    plans = {}
    for L in SPACINGS:
        xs = [i * L for i in range(B.N_INT)]
        p0 = B.plan()
        o_max, bE, bW = A.maxband(p0, xs, B.VPROG, objective="min",
                                  restarts=20, seed=9)
        plans[L] = dict(offsets=o_max, b_in=bE, b_out=bW, gT=p0.gT, C=p0.C)
        print("L=%.0f MAXBAND two-way band %.2f/%.2f (gT=%.0f)"
              % (L, bE, bW, p0.gT))
    json.dump({str(k): v for k, v in plans.items()},
              open(os.path.join(B.DATA, "h6_plan.json"), "w"), indent=1)

    jobs = []
    for L in SPACINGS:
        for q in LEVELS:
            for seed in SEEDS:
                S.get(L=L, seed=seed, thru=q, cross=CROSS, side=B.SIDE0)
                jobs.append(dict(thru=q, seed=seed, tag="maxband", L=L,
                                 offs=plans[L]["offsets"]))
                jobs.append(dict(thru=q, seed=seed, tag="uncoord", L=L,
                                 offs=[0.0] * B.N_INT))
    print("running %d simulations" % len(jobs))
    rows = B.pmap(sim_one, jobs)
    bad = [r for r in rows if "error" in r]
    if bad:
        print(bad[0]["tb"][:3000])
        raise SystemExit(1)
    A.write_csv(os.path.join(B.DATA, "h6_raw.csv"), rows)

    agg = []
    for L in SPACINGS:
      for q in LEVELS:
        arms = {}
        for tag in ("maxband", "uncoord"):
            g = sorted([r for r in rows if r["thru"] == q and r["tag"] == tag
                        and r["L"] == L], key=lambda r: r["seed"])
            arms[tag] = g
            row = dict(L=L, thru=q, tag=tag, n_rep=len(g),
                       link_len=g[0]["link_len"])
            for f in ("jam_max_EB", "jam_mean_EB", "nearfull_EB", "jam_max_WB",
                      "jam_mean_WB", "nearfull_WB", "zeroEB", "zeroWB",
                      "tl_thruE", "tl_thruW", "tl_all", "completed_share"):
                m, hw, sd, n = A.tconf([r[f] for r in g])
                row[f], row[f + "_hw"] = m, hw
            row["teleports"] = sum(r["teleports"] for r in g)
            row["tele_share_max"] = max(r["tele_share"] for r in g)
            row["running_max"] = max(r["running"] for r in g)
            row["storage_ratio_EB"] = row["jam_max_EB"] / row["link_len"]
            row["storage_ratio_WB"] = row["jam_max_WB"] / row["link_len"]
            agg.append(row)
        for f in ("tl_thruE", "tl_thruW", "tl_all", "zeroEB", "zeroWB",
                  "completed_share"):
            # SIGNED benefit: uncoordinated minus coordinated, so a POSITIVE
            # value means coordination reduced that quantity (helped).
            d = A.paired([r[f] for r in arms["maxband"]],
                         [r[f] for r in arms["uncoord"]])
            agg.append(dict(L=L, thru=q, tag="BENEFIT uncoord-minus-coord:" + f,
                            n_rep=d["n"], jam_max_EB=d["mean"],
                            jam_max_EB_hw=d["hw"], jam_mean_EB=d["p"],
                            nearfull_EB=d["corr"]))
    A.write_csv(os.path.join(B.DATA, "h6_agg.csv"), agg)
    print("H6 done")


if __name__ == "__main__":
    main()
