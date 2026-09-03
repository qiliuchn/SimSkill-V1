import sys, os, json
sys.path.insert(0, "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint/lib")
import net_lib as nl
import tls_lib as tl

WORK = "/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/07cb182d-88df-492d-b918-d753d888c5e5/scratchpad/bikeint/net"
LTS = ["--junctions.limit-turn-speed", "3.0"]   # validated in sub-goal 1c: no-op at r=10/15, real effect at r<=6
SETBACK_M = 4.0

os.makedirs(WORK, exist_ok=True)

# ---- pass 1: reference net (radius=10, no setback) to harvest baseline bike-through shapes ----
ref_spec = nl.VariantSpec("ref", bike_mode="dedicated", radius=10.0, arm_length=150.0)
ref_net, r = nl.build_variant_net(WORK, "ref", ref_spec, extra_netconvert_args=LTS)
assert r.returncode == 0, r.stderr
ref_lm = nl.parse_linkmap(ref_net)
base_shapes = {}
for c in ref_lm["connections"]:
    if c["movement"] == "through" and c["vtag"] == "bike":
        shp = nl.get_internal_lane_shape(ref_net, c["via"])
        base_shapes[c["approach"]] = shp
print("baseline bike-through shapes:", base_shapes)

# perpendicular push direction: bike lane is already offset to the "right of travel" side;
# pushing further the SAME sign moves it away from the vehicle lane (toward the outside/curb),
# which is what perp_offset's 'side'=-1 vs +1 controls. Determine sign empirically per approach
# by comparing distance-from-vehicle-via-lane under both signs and keeping the one that increases it.
def best_side_and_shape(approach, base_shape, veh_via_shape_str):
    vpts = [tuple(map(float, p.split(","))) for p in veh_via_shape_str.split()]
    vx = sum(p[0] for p in vpts) / len(vpts); vy = sum(p[1] for p in vpts) / len(vpts)
    best = None
    for side in (1.0, -1.0):
        shp = nl.make_setback_shape(base_shape, SETBACK_M, side=side)
        pts = [tuple(map(float, p.split(","))) for p in shp.split()]
        mx = sum(p[0] for p in pts) / len(pts); my = sum(p[1] for p in pts) / len(pts)
        d = ((mx - vx) ** 2 + (my - vy) ** 2) ** 0.5
        if best is None or d > best[0]:
            best = (d, side, shp)
    return best[2]

veh_via_shapes = {}
for c in ref_lm["connections"]:
    if c["movement"] == "right" and c["vtag"] == "veh":
        veh_via_shapes[c["approach"]] = nl.get_internal_lane_shape(ref_net, c["via"])

setback_shapes = {a: best_side_and_shape(a, base_shapes[a], veh_via_shapes[a]) for a in nl.ARMS}
print("setback shapes:", json.dumps(setback_shapes, indent=2))

# ---- variant definitions ----
VARIANTS = {
    "A": dict(bike_mode="mixed",     radius=10.0, setback=False, treatment="base"),
    "B": dict(bike_mode="dedicated", radius=10.0, setback=False, treatment="base"),
    "C": dict(bike_mode="dedicated", radius=3.0,  setback=True,  treatment="base"),
    "D": dict(bike_mode="dedicated", radius=3.0,  setback=True,  treatment="exclusive"),
    "E": dict(bike_mode="dedicated", radius=10.0, setback=False, treatment="lbi"),
    "C_radius_only":  dict(bike_mode="dedicated", radius=3.0,  setback=False, treatment="base"),
    "C_setback_only": dict(bike_mode="dedicated", radius=10.0, setback=True,  treatment="base"),
}

manifest = {}
for name, cfg in VARIANTS.items():
    spec = nl.VariantSpec(name, bike_mode=cfg["bike_mode"], radius=cfg["radius"], arm_length=150.0)
    shapes = setback_shapes if (cfg["setback"] and cfg["bike_mode"] == "dedicated") else None
    net_raw, r = nl.build_variant_net(WORK, name, spec, extra_netconvert_args=LTS,
                                       bike_through_shapes=shapes)
    if r.returncode != 0:
        print(name, "NETCONVERT FAILED"); print(r.stderr[-3000:]); continue
    lm = nl.parse_linkmap(net_raw)
    n_links = lm["n_links"]
    phases = tl.build_program(n_links, lm["linkmap"], lm["crossings"], cfg["treatment"])
    net_final = os.path.join(WORK, f"{name}.final.net.xml")
    tl.rewrite_tls(net_raw, net_final, phases)
    manifest[name] = dict(cfg=cfg, net=net_final, n_links=n_links,
                           cycle_len=sum(d for d, s in phases),
                           n_phases=len(phases))
    print(name, "OK  cycle=", manifest[name]["cycle_len"], "phases=", len(phases))

with open(os.path.join(WORK, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)
with open(os.path.join(WORK, "setback_shapes.json"), "w") as f:
    json.dump(setback_shapes, f, indent=2)
print("DONE")
