#!/usr/bin/env python3
"""
Build two tlLogic programs per arterial signal (ax1..ax6):
  "base"     - coordinated baseline plan, unified cycle, offsets computed for
               an EB progression at PROG_SPEED.
  "incident" - the sub-goal-3 "S" module's arterial responsive diversion plan:
               extra through green at the two signals bracketing the detour
               (ax3, ax4 = interchanges 2 and 3), offset re-tuned for the
               (slower) diverted-platoon speed on that link.

Reuses netconvert's auto-generated conflict-free phase *state strings* per
junction (never hand-derived -- too easy to get wrong) and only rescales
phase *durations* to a unified cycle length, then sets *offset*. This keeps
every phase provably conflict-free while giving two coordination levers
(offset, through/side-street split).

Offset formula accounts for each signal's own EB-through green window START
time within its local (unshifted) cycle -- not simply "distance / speed" --
since that window does not start at local phase-time 0 for every junction
(verified: ax2/ax5 have a different phase count/order than ax1/ax3/ax4/ax6).
Let g_start_k = local time (after duration rescale) at which the EB-through
connection first turns green. For a platoon leaving the reference signal's
own EB-through green start and travelling at PROG_SPEED:
    offset_k = (dist_k / PROG_SPEED - g_start_k + g_start_ref) mod C

Usage: python build_signals.py --net corridor.net.xml --out tls.add.xml
"""
import argparse
import json
import xml.etree.ElementTree as ET

CYCLE = 80.0
MIN_GREEN = 2.0
PROG_SPEED = 25.0          # m/s (~90 km/h), == posted arterial speed
DIVERT_SPEED = 17.0         # m/s (~61 km/h) assumed diverted-platoon speed on ax3-ax4 detour link
# SUMO tlLogic offset convention, verified empirically (not assumed) by
# verify_offset_sign.py against a non-degenerate offset: local_phase_time =
# (t - offset) mod C. OFFSET_SIGN=+1 is that "subtract" convention.
OFFSET_SIGN = 1.0

# arterial signal x-positions (must match gen_corridor.ARTERIAL_X, signalized subset)
SIGNAL_X = {"ax1": 1000.0, "ax2": 2000.0, "ax3": 3000.0, "ax4": 5000.0, "ax5": 6000.0, "ax6": 7000.0}
REF = "ax1"
INCIDENT_BOOST = {"ax3", "ax4"}
BASE_THRU_FRAC = 0.72      # baseline coordinated plan: through movement gets 72% of cycle
INCIDENT_THRU_FRAC = 0.82   # module S diversion plan: pushed further at ax3/ax4


def find_eb_through_link(net_root, tls_id):
    """Return the linkIndex of the art_eb_X -> art_eb_{X+1} (straight EB
    through) connection controlled by this tls."""
    for conn in net_root.findall("connection"):
        if conn.get("tl") != tls_id:
            continue
        frm, to, direction = conn.get("from", ""), conn.get("to", ""), conn.get("dir", "")
        if frm.startswith("art_eb_") and to.startswith("art_eb_") and direction == "s":
            return int(conn.get("linkIndex"))
    raise RuntimeError(f"no EB-through link found for {tls_id}")


def rescale_phases(phases):
    total = sum(float(d) for d, s in phases)
    scale = CYCLE / total
    return [(float(d) * scale, s) for d, s in phases]


def green_window_start(rescaled, link_idx):
    """Local time at which state[link_idx] first becomes 'G'/'g', scanning
    phases in order from local time 0."""
    t = 0.0
    for d, s in rescaled:
        if s[link_idx] in ("G", "g"):
            return t
        t += d
    raise RuntimeError("through link never green in this program")


def set_through_green(rescaled, link_idx, target_frac):
    """Reallocate cycle time so the phase carrying the through-EB/WB green
    (link_idx) gets target_frac of the cycle, taking the difference
    proportionally from the OTHER green phases (never touching yellow safety
    phases), floored at MIN_GREEN each. This is the primary coordination
    lever for a corridor whose arterial exists specifically to serve
    through diversion traffic -- ramp and cross-street movements are
    secondary and can be compressed toward their minimum."""
    C = sum(d for d, s in rescaled)
    thru_phase = None
    for i, (d, s) in enumerate(rescaled):
        if s[link_idx] in ("G", "g"):
            thru_phase = i
            break
    if thru_phase is None:
        return rescaled
    other_green = [i for i, (d, s) in enumerate(rescaled) if "G" in s and i != thru_phase]
    target_dur = target_frac * C
    cur_dur = rescaled[thru_phase][0]
    needed = target_dur - cur_dur
    if needed <= 0 or not other_green:
        return rescaled
    avail = sum(rescaled[i][0] - MIN_GREEN for i in other_green if rescaled[i][0] > MIN_GREEN)
    if avail <= 0:
        return rescaled
    take = min(needed, avail)
    out = list(rescaled)
    for i in other_green:
        d, s = out[i]
        if d <= MIN_GREEN:
            continue
        share = (d - MIN_GREEN) / avail
        red = take * share
        out[i] = (d - red, s)
    d0, s0 = out[thru_phase]
    out[thru_phase] = (d0 + take, s0)
    return out


def build_program_block(tls_id, program_id, offset, rescaled):
    lines = [f'    <tlLogic id="{tls_id}" type="static" programID="{program_id}" offset="{offset:.1f}">']
    for d, s in rescaled:
        lines.append(f'        <phase duration="{d:.1f}" state="{s}"/>')
    lines.append('    </tlLogic>')
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--audit-out", default=None)
    args = ap.parse_args()

    tree = ET.parse(args.net)
    root = tree.getroot()
    tls_by_id = {tl.get("id"): tl for tl in root.findall("tlLogic") if tl.get("id") in SIGNAL_X}

    # pass 1: rescale + locate EB-through green-window start for every signal
    info = {}
    for tls_id, tls in tls_by_id.items():
        phases = [(p.get("duration"), p.get("state")) for p in tls.findall("phase")]
        link_idx = find_eb_through_link(root, tls_id)
        resc_base = set_through_green(rescale_phases(phases), link_idx, BASE_THRU_FRAC)
        g_start = green_window_start(resc_base, link_idx)
        thru_inc_frac = INCIDENT_THRU_FRAC if tls_id in INCIDENT_BOOST else BASE_THRU_FRAC
        resc_inc = set_through_green(rescale_phases(phases), link_idx, thru_inc_frac)
        g_start_inc = green_window_start(resc_inc, link_idx)
        info[tls_id] = dict(resc_base=resc_base, resc_inc=resc_inc, link_idx=link_idx,
                             g_start=g_start, g_start_inc=g_start_inc)

    g_start_ref = info[REF]["g_start"]
    g_start_ref_inc = info[REF]["g_start_inc"]

    out_lines = ["<additional>"]
    audit = []
    for tls_id, x in sorted(SIGNAL_X.items(), key=lambda kv: kv[1]):
        dist = x - SIGNAL_X[REF]
        g_start = info[tls_id]["g_start"]
        base_offset = (OFFSET_SIGN * (dist / PROG_SPEED - g_start + g_start_ref)) % CYCLE

        if tls_id in INCIDENT_BOOST:
            dist_from_ax3 = x - SIGNAL_X["ax3"]
            g_start_inc = info[tls_id]["g_start_inc"]
            g_start_ax3_inc = info["ax3"]["g_start_inc"]
            t_at_ax3 = OFFSET_SIGN * ((SIGNAL_X["ax3"] - SIGNAL_X[REF]) / PROG_SPEED - g_start_ax3_inc + g_start_ref_inc)
            inc_offset = (t_at_ax3 + OFFSET_SIGN * (dist_from_ax3 / DIVERT_SPEED - g_start_inc + g_start_ax3_inc)) % CYCLE
        else:
            g_start_inc = info[tls_id]["g_start_inc"]
            inc_offset = (OFFSET_SIGN * (dist / PROG_SPEED - g_start_inc + g_start_ref_inc)) % CYCLE

        # NOTE write order matters: SUMO activates the *last*-loaded tlLogic
        # program for a given id as the default program at simulation start
        # (verified empirically) -- "incident" is written first, "base" last,
        # so the corridor starts in the coordinated baseline. Module S
        # switches to "incident" explicitly via traci.trafficlight.setProgram.
        out_lines.append(build_program_block(tls_id, "incident", inc_offset, info[tls_id]["resc_inc"]))
        out_lines.append(build_program_block(tls_id, "base", base_offset, info[tls_id]["resc_base"]))

        resc = info[tls_id]["resc_base"]
        resc2 = info[tls_id]["resc_inc"]
        audit.append(dict(tls=tls_id, x=x, link_idx=info[tls_id]["link_idx"],
                           g_start_base=round(g_start, 1), g_start_incident=round(info[tls_id]["g_start_inc"], 1),
                           base_offset=round(base_offset, 1), incident_offset=round(inc_offset, 1),
                           n_phases=len(resc),
                           cycle_base=round(sum(d for d, s in resc), 1),
                           cycle_incident=round(sum(d for d, s in resc2), 1),
                           thru_green_base=round(sum(d for d, s in resc if s[info[tls_id]["link_idx"]] in ("G", "g")), 1),
                           thru_green_incident=round(sum(d for d, s in resc2 if s[info[tls_id]["link_idx"]] in ("G", "g")), 1)))
    out_lines.append("</additional>")

    with open(args.out, "w") as f:
        f.write("\n".join(out_lines) + "\n")
    print("wrote", args.out)
    for a in audit:
        print(a)
    if args.audit_out:
        with open(args.audit_out, "w") as f:
            json.dump(audit, f, indent=2)


if __name__ == "__main__":
    main()
