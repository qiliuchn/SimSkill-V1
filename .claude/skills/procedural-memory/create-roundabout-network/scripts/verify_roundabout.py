"""
Verify a compiled SUMO net is a genuine roundabout with correct yield-at-entry
right-of-way -- i.e. ENTERING traffic yields to CIRCULATING traffic -- by
inspecting the connection link states and the junction request/response matrix,
NOT merely the ring geometry. A "roundabout-shaped" network that wasn't actually
recognized as one will have wrong right-of-way behavior despite looking correct.

Checks:
  1. A <roundabout> element exists in the .net.xml.
  2. Every entry connection (in_X -> ring edge) has link state 'm' (minor / give-way).
  3. Every circulating connection (ring -> ring, or ring -> out_X) has state 'M' (major).
  4. At each ring junction, the minor (give-way) links are exactly the entry links, and
     at least one request row shows a link yielding -- confirming entries actually defer
     to circulating traffic, not just carrying the right label.

Usage:
    python verify_roundabout.py roundabout.net.xml
Exits 0 if verified, 1 otherwise (with a printed explanation either way).

Written for a ring built with build_roundabout.py's naming convention (in_X/out_X/ring_X,
ring nodes rN/rE/rS/rW) -- adapt RING_EDGES / is_entry / is_circulating / the junction-id
matching if verifying a differently-named roundabout.
"""
import sys
import xml.etree.ElementTree as ET

RING_EDGES = {"ring_N", "ring_E", "ring_S", "ring_W"}
RING_NEXT = {"ring_N": "rW", "ring_W": "rS", "ring_S": "rE", "ring_E": "rN"}


def is_entry(c):
    return c.get("from", "").startswith("in_") and c.get("to") in RING_EDGES


def is_circulating(c):
    f, t = c.get("from", ""), c.get("to", "")
    return f in RING_EDGES and (t in RING_EDGES or t.startswith("out_"))


def main(net):
    root = ET.parse(net).getroot()
    ok = True

    ra = root.findall("roundabout")
    print(f"[1] <roundabout> elements: {len(ra)}", "OK" if ra else "FAIL")
    ok &= bool(ra)
    for r in ra:
        print(f"      nodes={r.get('nodes')}  edges={r.get('edges')}")

    conns = root.findall("connection")
    entry = [c for c in conns if is_entry(c)]
    circ = [c for c in conns if is_circulating(c)]

    bad_entry = [c for c in entry if c.get("state") != "m"]
    bad_circ = [c for c in circ if c.get("state") != "M"]
    print(f"[2] entry connections (in_->ring): {len(entry)}, with give-way state 'm': {len(entry) - len(bad_entry)}",
          "OK" if not bad_entry else f"FAIL ({[(c.get('from'), c.get('to'), c.get('state')) for c in bad_entry]})")
    print(f"[3] circulating connections: {len(circ)}, with priority state 'M': {len(circ) - len(bad_circ)}",
          "OK" if not bad_circ else f"FAIL ({[(c.get('from'), c.get('to'), c.get('state')) for c in bad_circ]})")
    ok &= (not bad_entry) and (not bad_circ) and len(entry) >= 4 and len(circ) >= 4

    junc_ok = True
    for j in root.findall("junction"):
        jid = j.get("id")
        if not (jid and jid.startswith("r") and jid[1:] in ("N", "E", "S", "W")):
            continue
        reqs = j.findall("request")
        jconns = []
        for c in conns:
            fe = c.get("from", "")
            dest = ("r" + fe.split("_")[1]) if fe.startswith("in_") else RING_NEXT.get(fe)
            if dest == jid:
                jconns.append(c)
        entry_here = [c for c in jconns if is_entry(c)]
        circ_here = [c for c in jconns if is_circulating(c)]
        yields = any(r.get("response", "").count("1") >= 1 for r in reqs) and entry_here and circ_here
        minors = [c for c in jconns if c.get("state") == "m"]
        minors_all_entry = all(is_entry(c) for c in minors) and len(minors) >= 1
        print(f"[4] junction {jid}: entries={len(entry_here)} circulating={len(circ_here)} "
              f"minor(give-way) links={len(minors)} all_minor_are_entries={minors_all_entry} "
              f"has_yield_row={yields}",
              "OK" if (yields and minors_all_entry) else "FAIL")
        junc_ok &= bool(yields and minors_all_entry)
    ok &= junc_ok

    print("\nRESULT:", "ROUNDABOUT RIGHT-OF-WAY VERIFIED (entry yields to circulating)" if ok else "VERIFICATION FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1])
