#!/usr/bin/env python3
"""Verify from the COMPILED net.net.xml (not the source intent):
  (a) grade separation  : no <connection> links a freeway edge directly to an arterial edge,
                          and there is no junction at the (0,0) freeway/arterial crossing point.
  (b) two signalized terminals : W and E are type="traffic_light" with a <tlLogic>.
  (c) unopposed-left signature : the arterial-to-on-ramp LEFT connection's foes bitstring
      does NOT include the opposing arterial-through connection in the DDI, but DOES in the
      conventional diamond.
Writes a human-readable report to outputs/verification_report.txt and returns structured data.
"""
import os, xml.etree.ElementTree as ET

OUT = "/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-30_09-43-42/attempts/attempt-1/outputs"

FREEWAY_PREFIX = "fw_"
ARTERIAL_EDGES = {"Aw_EB", "Aw_WB", "Ae_EB", "Ae_WB", "I_EB", "I_WB"}
RAMP_EDGES = {"SBon", "SBoff", "NBon", "NBoff"}

# The two heavy arterial-to-on-ramp LEFT movements and the opposing-through they would
# conflict with in a conventional diamond:
#   West terminal W : left  I_WB -> SBon   ; opposing through Aw_EB -> I_EB
#   East terminal E : left  I_EB -> NBon   ; opposing through Ae_WB -> I_WB
LEFTS = {
    "W": {"left": ("I_WB", "SBon"), "opp_through": ("Aw_EB", "I_EB")},
    "E": {"left": ("I_EB", "NBon"), "opp_through": ("Ae_WB", "I_WB")},
}


def foes_of(foes_str, idx):
    """Return the set of link indices that are foes of link `idx`, decoding the
    right-to-left SUMO foe bitstring (rightmost char = index 0)."""
    s = foes_str[::-1]  # now s[i] corresponds to link index i
    return {j for j, ch in enumerate(s) if ch == "1"}


def analyze(design):
    net = ET.parse(os.path.join(OUT, f"{design}.net.xml")).getroot()
    lines = [f"================ {design.upper()} net ({design}.net.xml) ================"]

    # ---- (a) grade separation ----
    bad = []
    for c in net.findall("connection"):
        fr, to = c.get("from"), c.get("to")
        fr_fw = fr.startswith(FREEWAY_PREFIX)
        to_fw = to.startswith(FREEWAY_PREFIX)
        fr_art = fr in ARTERIAL_EDGES
        to_art = to in ARTERIAL_EDGES
        if (fr_fw and to_art) or (fr_art and to_fw):
            bad.append((fr, to))
    junc_ids = {j.get("id") for j in net.findall("junction")}
    node_at_crossing = any(
        j.get("x") == "0.00" and j.get("y") == "0.00" for j in net.findall("junction")
    )
    lines.append("(a) GRADE SEPARATION")
    lines.append(f"    direct freeway<->arterial connections: {len(bad)} {'(NONE - OK)' if not bad else bad}")
    lines.append(f"    junction at crossing point (0,0): {node_at_crossing}  (freeway meets arterial only via ramps)")
    # confirm freeway junctions Fn/Fs are priority not signals
    fw_junc_types = {j.get("id"): j.get("type") for j in net.findall("junction") if j.get("id") in ("Fn", "Fs")}
    lines.append(f"    freeway junction types: {fw_junc_types}")

    # ---- (b) two signalized terminals ----
    term_types = {j.get("id"): j.get("type") for j in net.findall("junction") if j.get("id") in ("W", "E")}
    tls_ids = {t.get("id") for t in net.findall("tlLogic")}
    lines.append("(b) SIGNALIZED TERMINALS")
    lines.append(f"    terminal junction types: {term_types}")
    lines.append(f"    compiled tlLogic present for: {sorted(tls_ids)} "
                 f"(note: fixed-time programs are supplied separately as additional-files)")

    # ---- (c) unopposed-left signature ----
    lines.append("(c) UNOPPOSED-LEFT FOE SIGNATURE (arterial-to-on-ramp left vs opposing through)")
    result = {}
    for term in ("W", "E"):
        # link index map for connections controlled by this terminal's tls
        li = {}
        dirc = {}
        for c in net.findall("connection"):
            if c.get("tl") == term:
                key = (c.get("from"), c.get("to"))
                li.setdefault(key, []).append(int(c.get("linkIndex")))
                dirc[key] = c.get("dir")
        left_key = LEFTS[term]["left"]
        opp_key = LEFTS[term]["opp_through"]
        left_idxs = li.get(left_key, [])
        opp_idxs = set(li.get(opp_key, []))
        # find the junction requests
        junc = next(j for j in net.findall("junction") if j.get("id") == term)
        reqs = {int(r.get("index")): r.get("foes") for r in junc.findall("request")}
        opposed = False
        detail = []
        for lidx in left_idxs:
            fs = foes_of(reqs[lidx], lidx)
            overlap = fs & opp_idxs
            detail.append((lidx, sorted(fs), sorted(overlap)))
            if overlap:
                opposed = True
        result[term] = {
            "left_conn": f"{left_key[0]}->{left_key[1]}",
            "left_dir": dirc.get(left_key),
            "left_link_idxs": left_idxs,
            "opp_through_conn": f"{opp_key[0]}->{opp_key[1]}",
            "opp_link_idxs": sorted(opp_idxs),
            "opposed_by_through": opposed,
            "detail": detail,
        }
        lines.append(f"    Terminal {term}: LEFT {left_key[0]}->{left_key[1]} (dir={dirc.get(left_key)}, "
                     f"linkIdx={left_idxs}) vs opposing through {opp_key[0]}->{opp_key[1]} (linkIdx={sorted(opp_idxs)})")
        for lidx, fs, overlap in detail:
            lines.append(f"        link {lidx} foes={fs}  -> opposing-through in foes? "
                         f"{'YES (OPPOSED)' if overlap else 'NO (UNOPPOSED)'}  overlap={overlap}")
    return "\n".join(lines), result


def main():
    report = []
    data = {}
    for design in ("ddi", "conv"):
        txt, res = analyze(design)
        report.append(txt)
        data[design] = res

    # ---- summary contrast ----
    report.append("\n================ CONTRAST SUMMARY ================")
    for term in ("W", "E"):
        d = data["ddi"][term]["opposed_by_through"]
        c = data["conv"][term]["opposed_by_through"]
        report.append(f"Terminal {term}: DDI left opposed-by-through={d}  |  CONV left opposed-by-through={c}  "
                      f"-> {'DDI UNOPPOSED, CONV OPPOSED (as required)' if (not d and c) else 'CHECK!'}")

    text = "\n".join(report)
    print(text)
    with open(os.path.join(OUT, "verification_report.txt"), "w") as f:
        f.write(text + "\n")
    print("\nWrote verification_report.txt")


if __name__ == "__main__":
    main()
