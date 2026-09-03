#!/usr/bin/env python3
"""Derive the tlLogic linkIndex map from a COMPILED SUMO net.

Everything downstream (state strings, TraCI instrumentation, conflict pairing)
is keyed on this map; nothing is hand-typed.
"""
import xml.etree.ElementTree as ET

APPROACH_OF = {"in_N": "N", "in_E": "E", "in_S": "S", "in_W": "W"}
PAIRS = {"NS": ("N", "S"), "EW": ("E", "W")}
DIRNAME = {"r": "right", "s": "through", "l": "left"}


class LinkMap:
    def __init__(self, netfile, tls_id="C"):
        self.netfile = netfile
        self.tls_id = tls_id
        root = ET.parse(netfile).getroot()
        self.root = root

        self.crossing_spans = {}          # crossing edge id -> [edges spanned]
        for e in root.findall("edge"):
            if e.get("function") == "crossing":
                self.crossing_spans[e.get("id")] = e.get("crossingEdges", "").split()

        self.veh = {}      # linkIndex -> dict(from,to,dir,fromLane,toLane,via)
        self.xing = {}     # linkIndex -> dict(crossing edge id, spans)
        for c in root.findall("connection"):
            if c.get("tl") != tls_id:
                continue
            li = int(c.get("linkIndex"))
            to = c.get("to")
            if to in self.crossing_spans:
                self.xing[li] = {"edge": to, "spans": self.crossing_spans[to],
                                 "from": c.get("from")}
            else:
                self.veh[li] = {"from": c.get("from"), "to": to,
                                "dir": c.get("dir"),
                                "fromLane": int(c.get("fromLane")),
                                "toLane": int(c.get("toLane")),
                                "via": c.get("via")}
        self.n = len(self.veh) + len(self.xing)

        # movement (approach, dir) -> linkIndex
        self.mv = {}
        for li, d in self.veh.items():
            a = APPROACH_OF.get(d["from"])
            if a:
                self.mv[(a, d["dir"])] = li
        # approach -> its crossing (the one spanning that leg)
        self.leg_xing = {}
        for li, d in self.xing.items():
            for a in "NESW":
                if set(d["spans"]) == {f"in_{a}", f"out_{a}"}:
                    self.leg_xing[a] = li

    # --- convenience accessors -------------------------------------------
    def right(self, a):   return self.mv[(a, "r")]
    def thru(self, a):    return self.mv[(a, "s")]
    def left(self, a):    return self.mv[(a, "l")]

    def rights(self):     return {a: self.right(a) for a in "NESW"}

    def parallel_crossings(self, pair):
        """Crossings that run PARALLEL to the vehicle movement of `pair`
        (i.e. the crossings on the legs of the *other* pair)."""
        other = "EW" if pair == "NS" else "NS"
        return [self.leg_xing[a] for a in PAIRS[other]]

    def leg_crossings(self, pair):
        return [self.leg_xing[a] for a in PAIRS[pair]]

    def foe_crossings_of_right(self, a):
        """Crossings a right turn from approach `a` physically traverses:
        the crossing on its own approach leg and on its receiving leg."""
        li = self.right(a)
        frm, to = self.veh[li]["from"], self.veh[li]["to"]
        out = []
        for xli, d in self.xing.items():
            if frm in d["spans"] or to in d["spans"]:
                out.append(xli)
        return sorted(out)

    def state_len_check(self):
        tls = self.root.find("tlLogic")
        lens = {len(p.get("state")) for p in tls.findall("phase")}
        return (len(lens) == 1 and lens.pop() == self.n), self.n, len(self.veh), len(self.xing)

    def describe(self):
        rows = []
        for li in range(self.n):
            if li in self.veh:
                d = self.veh[li]
                rows.append(f"{li:3d}  {d['from']:>6s} -> {d['to']:<6s}  "
                            f"{DIRNAME.get(d['dir'], d['dir']):<8s} "
                            f"fromLane={d['fromLane']} toLane={d['toLane']} via={d['via']}")
            else:
                d = self.xing[li]
                rows.append(f"{li:3d}  {d['from']:>6s} -> {d['edge']:<6s}  "
                            f"crossing spans {d['spans']}")
        return "\n".join(rows)


if __name__ == "__main__":
    import sys
    lm = LinkMap(sys.argv[1])
    print(lm.describe())
    print("state-len check:", lm.state_len_check())
    print("rights:", lm.rights())
    print("leg crossings:", lm.leg_xing)
    print("NS parallel crossings:", lm.parallel_crossings("NS"))
    print("EW parallel crossings:", lm.parallel_crossings("EW"))
    for a in "NESW":
        print(f"foe crossings of {a}-right:", lm.foe_crossings_of_right(a))
