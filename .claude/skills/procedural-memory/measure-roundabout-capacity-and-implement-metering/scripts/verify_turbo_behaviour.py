"""
BEHAVIOURAL proof that the turbo variant's circulatory lane-change prohibition is
real, not merely drawn that way.  Structural proof (verify_networks.py [5]) shows
the attribute is present in the compiled net; this shows SUMO actually obeys it.

Protocol (manipulation + negative control, per
`design-actuated-signal-detector-placement-and-fault-tolerance`):
  * run the SAME demand, seed and step length on `two` and `turbo`
  * capture --lanechange-output and count lane-change events BY EDGE
  * PASS requires: ring-edge lane changes > 0 on `two` (so the demand genuinely
    provokes weaving) AND exactly 0 on `turbo`
  * NEGATIVE CONTROL: lane changes on the *approach* edges (in_X, which carry no
    changeLeft/changeRight restriction in either variant) must remain non-zero in
    BOTH, proving the prohibition is scoped to the circulatory roadway and did not
    just disable lane changing globally.
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import write_flows, run_sumo, ARMS, EXIT_ORDER

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(HERE, "networks")
OUT = os.path.join(HERE, "results", "turbo_behaviour")
RING = {"rg_" + a for a in ARMS} | {"rl_" + a for a in ARMS}


def count_lc(path):
    ring = app = other = 0
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "change":
            e = el.get("from", "").rsplit("_", 1)[0]
            if e in RING:
                ring += 1
            elif e.startswith("in_") or e.startswith("ap_"):
                app += 1
            else:
                other += 1
            el.clear()
    return ring, app, other


def main():
    os.makedirs(OUT, exist_ok=True)
    # heavy, well-mixed demand so weaving is genuinely provoked on the ring
    vol = {}
    for o in ARMS:
        for k, d in enumerate(EXIT_ORDER[o]):
            vol[(o, d)] = [220, 300, 220][k]
    rou = os.path.join(OUT, "demand.rou.xml")
    write_flows(rou, vol, 0, 1800)

    res = {}
    for v in ["two", "turbo"]:
        d = os.path.join(OUT, v)
        lcf = os.path.join(d, "lanechanges.xml")
        os.makedirs(d, exist_ok=True)
        run_sumo(os.path.join(NET, v + ".net.xml"), rou, d, end=2100, seed=1,
                 step=0.5, lanechange=lcf)
        res[v] = count_lc(lcf)

    print(f"{'variant':8s} {'ring LC':>9s} {'approach LC':>12s} {'other LC':>9s}")
    for v in ["two", "turbo"]:
        print(f"{v:8s} {res[v][0]:9d} {res[v][1]:12d} {res[v][2]:9d}")
    ok = res["two"][0] > 0 and res["turbo"][0] == 0 and res["two"][1] > 0 and res["turbo"][1] > 0
    print("\nring weaving provoked on conventional :", res["two"][0] > 0)
    print("ring weaving eliminated on turbo      :", res["turbo"][0] == 0)
    print("NEGATIVE CONTROL - approach lane changes still occur in BOTH:",
          res["two"][1] > 0 and res["turbo"][1] > 0)
    print("\nRESULT:", "TURBO RING LANE-CHANGE PROHIBITION BEHAVIOURALLY VERIFIED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
