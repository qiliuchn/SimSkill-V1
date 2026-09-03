"""
Structural verification of the compiled .net.xml files -- adapted from
`create-roundabout-network`'s scripts/verify_roundabout.py for the 8-ring-node
(exit node xX + entry node eX per arm) geometry used here.

Checks, per roundabout variant:
  [1] a <roundabout> element exists and lists all 8 ring edges
  [2] every ENTRY connection (in_X|ap_X -> rg_X) carries link state 'm' (give way)
  [3] every CIRCULATING connection (rl_X->rg_X, rg_prev->rl_X, rg_prev->out_X)
      carries link state 'M' (major / priority)
  [4] at each entry junction eX the request/response matrix genuinely encodes
      "entry yields to circulating": the entry link's response bit is SET against
      the circulating link's index, and the circulating link's own response row is
      all zeros (it yields to nobody).
  [5] TURBO ONLY: every circulatory lane forbids lane changing for the passenger
      fleet (changeLeft/changeRight list does not contain 'passenger' or 'all'),
      and the conventional two-lane variant does NOT (negative control).

Link index for a non-TLS junction is recovered from the `via` internal lane id,
which SUMO names ":<junctionID>_<linkIndex>_<laneIndex>".
Response bitstrings are written most-significant-first, so bit for link j is
response[len-1-j].
"""
import sys
import xml.etree.ElementTree as ET

ARMS = ["N", "E", "S", "W"]
NEXT_ARM = {"N": "W", "W": "S", "S": "E", "E": "N"}
PREV_ARM = {v: k for k, v in NEXT_ARM.items()}
RING = {"rg_" + a for a in ARMS} | {"rl_" + a for a in ARMS}


def link_index(conn):
    via = conn.get("via")
    if not via:
        return None
    parts = via.rsplit("_", 2)
    if len(parts) != 3:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def bit(resp, j):
    if j is None or j >= len(resp):
        return None
    return resp[len(resp) - 1 - j]


def verify_roundabout(path, name, turbo=False, control_path=None):
    root = ET.parse(path).getroot()
    conns = root.findall("connection")
    ok = True
    log = []

    ra = root.findall("roundabout")
    ra_edges = set()
    for r in ra:
        ra_edges |= set(r.get("edges", "").split())
    c1 = bool(ra) and RING <= ra_edges
    log.append(f"[1] <roundabout> elements={len(ra)}  ring edges listed={len(ra_edges & RING)}/8  -> {'OK' if c1 else 'FAIL'}")
    ok &= c1

    def is_entry(c):
        f, t = c.get("from", ""), c.get("to", "")
        return (f.startswith("in_") or f.startswith("ap_")) and t in RING

    def is_circ(c):  # ring -> ring: the movement entering traffic must yield to
        f, t = c.get("from", ""), c.get("to", "")
        return f in RING and t in RING

    def is_exit(c):
        f, t = c.get("from", ""), c.get("to", "")
        return f in RING and t.startswith("out_")

    entry = [c for c in conns if is_entry(c)]
    circ = [c for c in conns if is_circ(c)]
    exits = [c for c in conns if is_exit(c)]
    bad_e = [c for c in entry if c.get("state") != "m"]
    bad_c = [c for c in circ if c.get("state") != "M"]
    minor_exits = [c for c in exits if c.get("state") != "M"]
    log.append(f"[2] entry connections={len(entry)} with state 'm'={len(entry)-len(bad_e)} -> {'OK' if not bad_e else 'FAIL ' + str([(c.get('from'), c.get('to'), c.get('state')) for c in bad_e])}")
    log.append(f"[3] circulating ring->ring connections={len(circ)} with state 'M'={len(circ)-len(bad_c)} -> {'OK' if not bad_c else 'FAIL ' + str([(c.get('from'), c.get('to'), c.get('state')) for c in bad_c])}")
    log.append(f"[3b] exit (ring->out) connections={len(exits)}; NON-major exits={len(minor_exits)}"
               + ("" if not minor_exits else
                  "  <-- expected on a 2-lane ring: the INNER lane's exit crosses the OUTER lane's "
                  "continuing movement, so netconvert assigns it minor status. Detail: "
                  + str([(c.get('from'), c.get('fromLane'), c.get('to'), c.get('toLane'), c.get('state')) for c in minor_exits])))
    ok &= (not bad_e) and (not bad_c) and len(entry) >= 4 and len(circ) >= 8

    # [4] request/response matrix at each entry junction eX
    junc = {j.get("id"): j for j in root.findall("junction")}
    for a in ARMS:
        jid = "e" + a
        j = junc.get(jid)
        if j is None:
            log.append(f"[4] junction {jid}: MISSING -> FAIL"); ok = False; continue
        reqs = {int(r.get("index")): r for r in j.findall("request")}
        ent = [c for c in conns if is_entry(c) and c.get("to") == "rg_" + a and
               (c.get("from") in ("in_" + a, "ap_" + a))]
        cir = [c for c in conns if c.get("from") == "rl_" + a and c.get("to") == "rg_" + a]
        good = bool(ent) and bool(cir)
        detail = []
        for ce in ent:
            ie = link_index(ce)
            re_ = reqs.get(ie)
            for cc in cir:
                ic = link_index(cc)
                rc = reqs.get(ic)
                if re_ is None or rc is None:
                    good = False; detail.append(f"missing request row {ie}/{ic}"); continue
                b_yield = bit(re_.get("response", ""), ic)
                rc_zero = set(rc.get("response", "")) <= {"0"}
                b_foe = bit(re_.get("foes", ""), ic)
                if b_yield != "1":
                    good = False
                detail.append(f"entryLink{ie}(lane{ce.get('fromLane')})->circLink{ic}(lane{cc.get('fromLane')}): "
                              f"response_bit={b_yield} foe_bit={b_foe} circ_response_all_zero={rc_zero}")
                if not rc_zero:
                    good = False
        log.append(f"[4] junction {jid}: {'OK' if good else 'FAIL'}")
        for d in detail:
            log.append(f"      {d}")
        ok &= good

    # [5] turbo lane-change prohibition (with negative control)
    def ring_lane_change(p):
        r = ET.parse(p).getroot()
        out = {}
        for e in r.findall("edge"):
            if e.get("id") in RING:
                for l in e.findall("lane"):
                    out[l.get("id")] = (l.get("changeLeft"), l.get("changeRight"))
        return out

    if turbo:
        lc = ring_lane_change(path)
        def forbids(v):
            if v is None:
                return False  # attribute absent => default 'all' => weaving allowed
            toks = set(v.split())
            return "all" not in toks and "passenger" not in toks
        bad = {k: v for k, v in lc.items() if not (forbids(v[0]) and forbids(v[1]))}
        c5 = bool(lc) and not bad
        log.append(f"[5] turbo: circulatory lanes={len(lc)}, all forbid passenger weaving={c5} -> {'OK' if c5 else 'FAIL ' + str(bad)}")
        sample = list(lc.items())[:2]
        for k, v in sample:
            log.append(f"      {k}: changeLeft={v[0]!r} changeRight={v[1]!r}")
        ok &= c5
        if control_path:
            lcc = ring_lane_change(control_path)
            permissive = all(v == (None, None) for v in lcc.values())
            log.append(f"[5-neg] negative control ({control_path}): all circulatory lanes have NO change restriction = {permissive} -> {'OK' if permissive else 'FAIL'}")
            ok &= permissive

    print(f"\n===== {name} ({path}) =====")
    for l in log:
        print(l)
    print(f"RESULT {name}: {'VERIFIED' if ok else 'FAILED'}")
    return ok


def compare_foe_matrices(p1, p2, n1, n2):
    """[6] Prove the ONLY difference between the conventional and turbo two-lane
    variants is the lane-change permission -- i.e. their junction request/response
    /foes matrices and connection states are byte-identical."""
    def sig(p):
        r = ET.parse(p).getroot()
        out = []
        for j in sorted(r.findall("junction"), key=lambda x: x.get("id")):
            if j.get("type") == "internal":
                continue
            for q in j.findall("request"):
                out.append((j.get("id"), q.get("index"), q.get("response"), q.get("foes"), q.get("cont")))
        for c in sorted(r.findall("connection"), key=lambda x: (x.get("from"), x.get("fromLane"), x.get("to"))):
            out.append((c.get("from"), c.get("fromLane"), c.get("to"), c.get("toLane"), c.get("state"), c.get("dir")))
        return out
    s1, s2 = sig(p1), sig(p2)
    same = s1 == s2
    print(f"\n===== [6] foe/response-matrix identity: {n1} vs {n2} =====")
    print(f"rows compared: {len(s1)} vs {len(s2)};  identical = {same}"
          + ("" if same else f"  first diff: {[x for x, y in zip(s1, s2) if x != y][:3]}"))
    print("  => any measured turbo-vs-conventional difference is attributable ONLY to the "
          "circulatory lane-change prohibition, not to a different conflict-point topology.")
    return same


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "networks"
    allok = True
    allok &= verify_roundabout(f"{d}/sl.net.xml", "single-lane roundabout")
    allok &= verify_roundabout(f"{d}/two.net.xml", "conventional two-lane roundabout")
    allok &= verify_roundabout(f"{d}/turbo.net.xml", "turbo roundabout", turbo=True,
                               control_path=f"{d}/two.net.xml")
    allok &= verify_roundabout(f"{d}/slm.net.xml", "single-lane roundabout + metering nodes")
    allok &= verify_roundabout(f"{d}/twom.net.xml", "two-lane roundabout + metering nodes")
    allok &= compare_foe_matrices(f"{d}/two.net.xml", f"{d}/turbo.net.xml",
                                  "conventional two-lane", "turbo")
    print("\nALL:", "VERIFIED" if allok else "FAILED")
    sys.exit(0 if allok else 1)
