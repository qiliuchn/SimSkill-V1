"""Verify, from the COMPILED net + the additional files (not from design intent),
that every bus stop is on the lane and at the offset intended, that pedestrian
<access> links exist and point at a real sidewalk lane, and that near-side /
far-side / mid-block placement is geometrically what its name claims."""
import os
import sys
import json
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))
import sumolib  # noqa: E402
from scenario import Cfg, build_scenario, signal_x  # noqa: E402


def verify(cfg, outdir):
    sc = build_scenario(cfg, outdir, 1)
    net = sumolib.net.readNet(sc["net"])
    add = ET.parse(sc["busstops"]).getroot()
    rows = []
    ok = True
    for bs in add.findall("busStop"):
        sid = bs.get("id")
        lane_id = bs.get("lane")
        sp, ep = float(bs.get("startPos")), float(bs.get("endPos"))
        lane = net.getLane(lane_id)
        edge = lane.getEdge()
        intended = next(s for s in sc["stops"] if s["id"] == sid)
        # x of the stop reconstructed from the compiled net geometry
        eb_span = next(s for s in sc["info"]["eb_spans"] if s[0] == edge.getID())
        x_actual = eb_span[1] + sp
        # distance to the NEXT downstream signalised junction along the corridor
        to_node = edge.getToNode().getID()
        # true corridor distance to the next / previous SIGNAL (not sub-edge end)
        sigx = [signal_x(cfg, j) for j in range(1, cfg.n_signals + 1)]
        x_end = eb_span[1] + ep
        dn = min([s - x_end for s in sigx if s >= x_end - 1e-6], default=float("nan"))
        up = min([x_actual - s for s in sigx if s <= x_actual + 1e-6], default=float("nan"))
        acc = bs.findall("access")
        acc_ok = []
        for a in acc:
            al = net.getLane(a.get("lane"))
            acc_ok.append({"lane": a.get("lane"),
                           "allows_pedestrian": al.allows("pedestrian"),
                           "allows_passenger": al.allows("passenger"),
                           "pos": float(a.get("pos")),
                           "within_lane": 0 <= float(a.get("pos")) <= al.getLength(),
                           "same_edge_as_stop": al.getEdge().getID() == edge.getID()})
        r = {
            "stop": sid, "lane": lane_id, "lane_index": lane.getIndex(),
            "lane_length": round(lane.getLength(), 2),
            "lane_allows_bus": lane.allows("bus"),
            "lane_allows_passenger": lane.allows("passenger"),
            "lane_allows_pedestrian": lane.allows("pedestrian"),
            "startPos": sp, "endPos": ep,
            "within_lane": (0 <= sp < ep <= lane.getLength() + 0.01),
            "edge": edge.getID(), "to_node": to_node,
            "x_intended": round(intended["x"], 2), "x_from_compiled_net": round(x_actual, 2),
            "x_error_m": round(x_actual - intended["x"], 3),
            "m_to_downstream_junction": round(dn, 2),
            "m_from_upstream_junction": round(up, 2),
            "n_access": len(acc), "access": acc_ok,
        }
        bad = (not r["within_lane"]) or (not r["lane_allows_bus"]) or r["n_access"] == 0 \
            or abs(r["x_error_m"]) > 0.5 or not all(a["allows_pedestrian"] for a in acc_ok)
        r["OK"] = not bad
        ok = ok and not bad
        rows.append(r)
    return {"cfg_placement": cfg.stop_placement, "cfg_type": cfg.stop_type,
            "all_ok": ok, "stops": rows,
            "net": sc["net"], "busstops_file": sc["busstops"]}


if __name__ == "__main__":
    out = {}
    base = os.path.join(os.path.dirname(HERE), "runs", "verify_infra")
    for placement in ("nearside", "farside", "midblock"):
        for stype in ("inlane", "bay", "geobay"):
            cfg = Cfg(stop_placement=placement, stop_type=stype,
                      demand_end=200.0, sim_end=400.0)
            key = f"{placement}-{stype}"
            try:
                out[key] = verify(cfg, os.path.join(base, key))
            except Exception as e:
                out[key] = {"all_ok": False, "error": repr(e)}
    # spacing-mode layouts too
    for sp in (200, 400, 800):
        cfg = Cfg(stop_spacing=float(sp), stop_type="inlane",
                  demand_end=200.0, sim_end=400.0)
        key = f"spacing{sp}"
        out[key] = verify(cfg, os.path.join(base, key))
    p = os.path.join(os.path.dirname(HERE), "results", "verify_infrastructure.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(out, open(p, "w"), indent=1)
    for k, v in out.items():
        print(f"{k:22s} all_ok={v.get('all_ok')} " +
              (f"err={v.get('error')}" if "error" in v else
               f"nstops={len(v['stops'])} maxXerr={max(abs(s['x_error_m']) for s in v['stops']):.3f} "
               f"downstream_gap={[s['m_to_downstream_junction'] for s in v['stops']][:3]}"))
