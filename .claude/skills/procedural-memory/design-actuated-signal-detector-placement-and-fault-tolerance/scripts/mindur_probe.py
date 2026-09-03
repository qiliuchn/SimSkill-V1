#!/usr/bin/env python3
"""Is the far-setback collapse a genuine BLIND-ZONE failure, or merely an
artifact of leaving minDur at 7 s?  A detector d metres upstream cannot see the
queue between itself and the stop line; raising minDur so that green is
guaranteed to outlast the blind-zone discharge is the textbook remedy.  If the
collapse is real, raising minDur should mitigate it but not for free.
"""
import csv, os, sys
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.environ.get("SUMO_HOME", ""), "tools"))
import cfgutil
from tls_common import GREEN_ORDER

def one(a):
    import run_cell
    sb, md, lv, s = a
    c = cfgutil.actuated_cfg(lv, sb, 3.0)
    c["min_dur"] = {gp: float(md) for gp in GREEN_ORDER}
    wd = os.path.join(cfgutil.WORK, "mindur", f"sb{sb}_md{md}__{lv}__s{s}")
    m = run_cell.run(wd, cfgutil.NET, cfgutil.rou(lv, s), c, s)
    p = m["phases"]["A_major_thru"]
    return dict(setback=sb, min_dur=md, level=lv, seed=s,
                delay=m["all"]["delay"], robust=m["delay_censor_robust"],
                completion=m["completion_rate"], throughput=m["throughput"],
                A_mean_green=p["mean_green"], A_f_cutQ=p["f_cut_with_blind_queue"],
                A_blind_slow=p["mean_blind_slow"])

if __name__ == "__main__":
    tasks = [(sb, md, lv, s) for sb in (25, 40, 60, 90)
             for md in (7, 15, 25, 35) for lv in ("med",) for s in (1,2,3,4,5)]
    with Pool(9) as p: res = p.map(one, tasks, chunksize=1)
    out = os.path.join(cfgutil.WORK, "mindur_probe.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(res[0].keys())); w.writeheader(); w.writerows(res)
    agg = {}
    for r in res: agg.setdefault((r["setback"], r["min_dur"]), []).append(r)
    print(f"{'sb':>3} {'minDur':>6} {'delay':>8} {'robust':>9} {'comp':>6} {'meanG':>6} {'f_cutQ':>7} {'blindQ':>7}")
    for k in sorted(agg):
        rs = agg[k]; n = len(rs)
        print(f"{k[0]:3d} {k[1]:6d} {sum(x['delay'] for x in rs)/n:8.1f} "
              f"{sum(x['robust'] for x in rs)/n:9.1f} {sum(x['completion'] for x in rs)/n:6.3f} "
              f"{sum(x['A_mean_green'] for x in rs)/n:6.1f} {sum(x['A_f_cutQ'] for x in rs)/n:7.3f} "
              f"{sum(x['A_blind_slow'] for x in rs)/n:7.2f}")
