#!/usr/bin/env python3
"""One-call scenario+plan evaluation used by every hypothesis script."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arterial_lib as A     # noqa: E402
import fcdband               # noqa: E402
import sumolib               # noqa: E402

_NET_CACHE = {}


def net_of(scen):
    if scen["net"] not in _NET_CACHE:
        _NET_CACHE[scen["net"]] = sumolib.net.readNet(scen["net"])
    return _NET_CACHE[scen["net"]]


def evaluate(scen, plan, outdir, seed=1, warm=600.0, fcd=False, e2=False,
             extra_adds=(), ttt=300.0, keep_fcd=False):
    """Run one (scenario, signal plan, seed) and return every measurement layer."""
    outdir = os.path.abspath(outdir)
    os.makedirs(outdir, exist_ok=True)
    nt = net_of(scen)
    n = scen["n_int"]
    add = plan.write_add(nt, os.path.join(outdir, "plan.add.xml")) \
        if plan is not None else None
    adds = ([add] if add else []) + list(extra_adds)
    extra = []
    fcd_path = None
    if fcd:
        filt = A.write_edge_filter(os.path.join(outdir, "arterial.sel.txt"),
                                   A.arterial_edges(n))
        fcd_path = os.path.join(outdir, "fcd.xml")
        extra += ["--fcd-output.filter-edges.input-file", filt,
                  "--fcd-output.attributes", "x,y,speed,lane",
                  "--device.fcd.begin", "%.0f" % warm]
    if e2:
        e2f = A.write_e2(nt, os.path.join(outdir, "e2.add.xml"), n,
                         out_xml=os.path.join(outdir, "e2.out.xml"))
        adds.append(e2f)
    r = A.run_sumo(scen["net"], scen["rou"], adds, outdir, seed=seed,
                   end=scen["end"], fcd=fcd_path, extra=extra, ttt=ttt)
    tele = A.teleport_ids(r["stderr"])
    rows = A.parse_tripinfo(r["tripinfo"])
    st = A.stats(rows, t0=warm, teleported=tele)
    summ = A.parse_summary(r["summary"])
    res = dict(stats=st, summary=summ, n_teleport_events=len(tele),
               teleport_ids=sorted(tele), dir=outdir,
               loaded=summ.get("loaded"), inserted=summ.get("inserted"),
               arrived=summ.get("arrived"), still_running=summ.get("running"),
               completed_share=(summ.get("arrived", 0) /
                                max(summ.get("inserted", 1), 1)))
    if fcd:
        seen, missing = A.verify_fcd_edges(fcd_path, A.arterial_edges(n))
        res["fcd_edges_seen"] = len(seen)
        res["fcd_edges_missing"] = missing
        rec = fcdband.analyse(fcd_path, scen["xs"], plan.C, t0=warm)
        res["meas"] = {d: fcdband.band_stats(rec[d], plan.C) for d in ("EB", "WB")}
        res["fcd_records"] = rec
        if not keep_fcd:
            os.remove(fcd_path)
        else:
            res["fcd"] = fcd_path
    return res


def analytic(plan, scen, v):
    bE, _ = A.band(plan, scen["xs"], v, "EB")
    bW, _ = A.band(plan, scen["xs"], v, "WB")
    return bE, bW
