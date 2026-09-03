"""TLS phase construction for the bicycle-intersection variants, keyed off a compiled
net's own linkmap (never hand-typed state strings)."""
import re

Y = 3.0     # yellow
AR = 2.0    # all-red
LBI = 5.0   # leading bicycle interval, per LPI precedent (evaluate-right-turn-on-red-and-leading-pedestrian-interval)
NS_GREEN = 34.0
EW_GREEN = 24.0
EXCL_BIKE_GREEN = 10.0
EXCL_BIKE_Y = 3.0
EXCL_BIKE_AR = 1.5


def _blank(n):
    return ["r"] * n


def _apply(state, linkmap, crossings, preds):
    """preds: list of (predicate_fn(approach,movement,vtag) -> char or None)"""
    for (approach, mv, vtag), li in linkmap.items():
        for pred in preds:
            ch = pred(approach, mv, vtag)
            if ch is not None:
                state[li] = ch
    return state


def ns_ew_predicates(green_axis):
    """green_axis: 'NS' or 'EW'. Returns predicate for through/left/right = G/g, other axis stays r."""
    axis_arms = {"N", "S"} if green_axis == "NS" else {"E", "W"}
    def pred(approach, mv, vtag):
        if approach not in axis_arms:
            return None
        if mv == "through":
            return "G"
        if mv in ("left", "right"):
            return "g"
        return None
    return pred


def crossing_state(n_links, crossings, green_legs):
    """green_legs: set of arm names whose crossing should walk (parallel to the OTHER axis' green)."""
    extra = {}
    for c in crossings:
        # crossing 'to' internal edge id encodes leg via crossingEdges (e.g. out_N/in_N -> leg N)
        leg = None
        for e in c["crossingEdges"]:
            if e.startswith("in_") or e.startswith("out_"):
                leg = e.split("_", 1)[1]
                break
        extra[c["linkIndex"]] = "G" if leg in green_legs else "r"
    return extra


def build_phase_state(n_links, linkmap, crossings, green_axis, bike_mode="normal",
                       lbi_axis=None, all_red_bikes_axis=None, exclusive_bike=False):
    """
    bike_mode: 'normal' (bike follows its axis phase), 'lbi_hold' (bike green, ALL vehicle
      links red on lbi_axis), 'excl_only' (only bikes on all 4 approaches green, all vehicles red).
    """
    state = _blank(n_links)
    if exclusive_bike:
        for (approach, mv, vtag), li in linkmap.items():
            if vtag == "bike" and mv == "through":
                state[li] = "G"
        # vehicles & crossings stay r
        return "".join(state)

    if bike_mode == "lbi_hold":
        # only the bikes on lbi_axis go green; everything else (incl. that axis's vehicles) red;
        # cross-axis stays exactly as it was on red (no change) -- this phase is inserted, not overlapped
        for (approach, mv, vtag), li in linkmap.items():
            if vtag == "bike" and mv == "through" and approach in ({"N", "S"} if lbi_axis == "NS" else {"E", "W"}):
                state[li] = "G"
        return "".join(state)

    # normal through-green phase
    pred = ns_ew_predicates(green_axis)
    _apply(state, linkmap, crossings, [pred])
    # bikes follow their own axis, green with the vehicles (unless this call is for the
    # LBI-shortened remainder phase where bikes have already had their head start -- still green here)
    for (approach, mv, vtag), li in linkmap.items():
        if vtag == "bike" and mv == "through":
            axis = "NS" if approach in ("N", "S") else "EW"
            if axis == green_axis:
                state[li] = "G"
    # crossings: legs perpendicular to vehicle green walk
    green_legs = {"E", "W"} if green_axis == "NS" else {"N", "S"}
    cross_extra = crossing_state(n_links, crossings, green_legs)
    for li, ch in cross_extra.items():
        state[li] = ch
    return "".join(state)


def yellow_of(state, active_chars=("G", "g")):
    return "".join("y" if c in active_chars else c for c in state)


def allred_of(state):
    return "".join("r" if c not in ("G", "g", "G", "s") else "r" for c in state)  # everything red


def build_program(n_links, linkmap, crossings, treatment):
    """treatment in {'base','lbi','exclusive'}. Returns list of (duration, state) phases."""
    ns = build_phase_state(n_links, linkmap, crossings, "NS")
    ew = build_phase_state(n_links, linkmap, crossings, "EW")
    ns_y = yellow_of(ns); ns_ar = "r" * n_links
    ew_y = yellow_of(ew); ew_ar = "r" * n_links

    if treatment == "base":
        return [
            (NS_GREEN, ns), (Y, ns_y), (AR, ns_ar),
            (EW_GREEN, ew), (Y, ew_y), (AR, ew_ar),
        ]
    elif treatment == "lbi":
        ns_lbi = build_phase_state(n_links, linkmap, crossings, "NS", bike_mode="lbi_hold", lbi_axis="NS")
        ew_lbi = build_phase_state(n_links, linkmap, crossings, "EW", bike_mode="lbi_hold", lbi_axis="EW")
        return [
            (LBI, ns_lbi), (NS_GREEN - LBI, ns), (Y, ns_y), (AR, ns_ar),
            (LBI, ew_lbi), (EW_GREEN - LBI, ew), (Y, ew_y), (AR, ew_ar),
        ]
    elif treatment == "exclusive":
        excl = build_phase_state(n_links, linkmap, crossings, "NS", exclusive_bike=True)
        excl_y = yellow_of(excl, active_chars=("G",))
        excl_ar = "r" * n_links
        return [
            (NS_GREEN, ns), (Y, ns_y), (AR, ns_ar),
            (EW_GREEN, ew), (Y, ew_y), (AR, ew_ar),
            (EXCL_BIKE_GREEN, excl), (EXCL_BIKE_Y, excl_y), (EXCL_BIKE_AR, excl_ar),
        ]
    else:
        raise ValueError(treatment)


def rewrite_tls(net_path, out_path, phases, program_id="0"):
    body = "".join(f'    <phase duration="{d}" state="{s}"/>\n' for d, s in phases)
    new_tllogic = f'  <tlLogic id="center" type="static" programID="{program_id}" offset="0">\n{body}  </tlLogic>\n'
    with open(net_path) as f:
        txt = f.read()
    new_txt = re.sub(r'  <tlLogic id="center".*?</tlLogic>\n', new_tllogic, txt, flags=re.S)
    assert new_txt != txt, "tlLogic replacement failed"
    with open(out_path, "w") as f:
        f.write(new_txt)
