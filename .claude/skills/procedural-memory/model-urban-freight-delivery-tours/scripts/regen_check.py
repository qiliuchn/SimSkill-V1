#!/usr/bin/env python3
"""
Regenerate EVERY arm's freight demand with the fixed gen_freight.py into a scratch
directory and diff it byte-for-byte against the demand that is on disk (from
attempt 1).  Prints exactly which arms changed, so only those need re-simulating.
"""
import os, sys, json, hashlib, shutil, tempfile
from common import *   # noqa
import gen_freight as gf
import experiments as ex

SCRATCH = os.path.join(DEMAND, "_regen_check")
os.makedirs(SCRATCH, exist_ok=True)


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def main():
    arms = ex.build_arms()
    changed, missing, same = [], [], []
    for a in arms:
        if a.get("caronly") or a["scale"] == 0:
            continue
        old_rou = os.path.join(DEMAND, "f_%s.rou.xml" % a["arm"])
        if not os.path.exists(old_rou):
            missing.append(a["arm"])
            continue
        new_add = os.path.join(SCRATCH, "f_%s.add.xml" % a["arm"])
        new_rou = os.path.join(SCRATCH, "f_%s.rou.xml" % a["arm"])
        new_lg = os.path.join(SCRATCH, "f_%s.ledger.json" % a["arm"])
        gf.generate(os.path.join(NET, "%s.net.xml" % a["net"]), ex.ADDRS,
                    new_add, new_rou, seed=a["seed"], fleet_mix=a["fleet"],
                    paradigm=a["paradigm"], freight_scale=a["scale"],
                    night_fraction=a["night"], night_offset=ex.NIGHT_OFFSET,
                    bay_ids=ex.bay_ids(a["bay_frac"]), ledger_path=new_lg,
                    stop_caps=a.get("stop_caps"))
        (changed if md5(old_rou) != md5(new_rou) else same).append(a["arm"])
    print("arms unchanged : %d" % len(same))
    print("arms CHANGED   : %d" % len(changed))
    print("arms missing   : %d %s" % (len(missing), missing[:5]))
    groups = {}
    for c in changed:
        groups.setdefault(c.rsplit("_s", 1)[0], []).append(c)
    for g, v in sorted(groups.items()):
        print("   %-24s %d seeds" % (g, len(v)))
    json.dump(dict(changed=sorted(changed), unchanged=sorted(same)),
              open(os.path.join(TAB, "regen_check.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
