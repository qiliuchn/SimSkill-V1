#!/usr/bin/env python3
"""
Bake the Webster-sized plan (from tlsCycleAdaptation.py) into every compiled
network variant, by rewriting phase DURATIONS in place.

This is done instead of loading the .tll.xml as an additional file because SUMO
refuses a second tlLogic with the same id+programID ("Another logic with id X and
programID '0' exists").  Rewriting durations is safe here and is *verified* safe:
the phase STATE strings are byte-identical between the Webster file and every net
variant (checked below), i.e. the permission edits did not change link indices.
"""
import os, json
import xml.etree.ElementTree as ET
from common import *   # noqa

W = os.path.join(NET, "webster.tll.xml")


def load_prog(f):
    d = {}
    for tl in ET.parse(f).getroot().iter("tlLogic"):
        d[tl.get("id")] = [(p.get("duration"), p.get("state")) for p in tl if p.tag == "phase"]
    return d


def main():
    web = load_prog(W)
    manifest = json.load(open(os.path.join(NET, "net_manifest.json")))
    report = {}
    for tag in manifest:
        f = os.path.join(NET, "%s.net.xml" % tag)
        tree = ET.parse(f)
        root = tree.getroot()
        n_ok, n_mismatch = 0, 0
        for tl in root.iter("tlLogic"):
            tid = tl.get("id")
            if tid not in web:
                continue
            phases = [p for p in tl if p.tag == "phase"]
            wp = web[tid]
            if len(phases) != len(wp) or any(p.get("state") != s for p, (_, s) in zip(phases, wp)):
                n_mismatch += 1
                continue
            for p, (dur, _) in zip(phases, wp):
                p.set("duration", dur)
            n_ok += 1
        tree.write(f, encoding="UTF-8", xml_declaration=True)
        report[tag] = dict(patched=n_ok, state_mismatch=n_mismatch)
        print("%-14s webster phases applied to %d tlLogics (mismatched: %d)"
              % (tag, n_ok, n_mismatch))
    json.dump(report, open(os.path.join(NET, "webster_apply_report.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
